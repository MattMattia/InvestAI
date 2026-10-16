"""
Suite de pruebas de integración herméticas para el controlador REST de Autenticación (/api/v1/auth/*)
(Módulo 5.4 - Fase 1).
Valida registro con bloqueo de Mass Assignment, login con mitigación de Timing Attacks / enumeración (CWE-204),
rotación criptográfica de Refresh Tokens, prevención de Token Confusion y perfil de sesión activa (/me)
bajo el contrato Universal Envelope (APIResponse / APIErrorResponse).
"""
from datetime import timedelta
import unittest
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # Registra todos los modelos declarativos SQLAlchemy
from app.api.deps import get_db_session
from app.core.database import Base
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
)
from app.main import app as fastapi_app
from app.models.user import UserModel
from app.schemas.token import TokenType
from app.schemas.user import UserRole


@pytest.mark.integration
class TestApiAuthIntegration(unittest.IsolatedAsyncioTestCase):
    """Pruebas de integración E2E para los endpoints de identidad y sesión (/api/v1/auth)."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Sembrar usuarios de prueba con rounds=4 para optimizar velocidad de ejecución
        self.raw_password = "InstitutionalPassword!2026"
        pw_hash = get_password_hash(self.raw_password, rounds=4)

        self.active_user = UserModel(
            id=uuid.uuid4(),
            email="trader.auth@investai.internal",
            hashed_password=pw_hash,
            full_name="Active Trader User",
            role=UserRole.TRADER,
            is_active=True,
        )
        self.inactive_user = UserModel(
            id=uuid.uuid4(),
            email="suspended.auth@investai.internal",
            hashed_password=pw_hash,
            full_name="Suspended Trader User",
            role=UserRole.TRADER,
            is_active=False,
        )

        async with self.SessionLocal() as session:
            session.add_all([self.active_user, self.inactive_user])
            await session.commit()

        async def _override_get_db():
            async with self.SessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()

        fastapi_app.dependency_overrides[get_db_session] = _override_get_db
        self.transport = httpx.ASGITransport(app=fastapi_app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            await self.client.aclose()
        fastapi_app.dependency_overrides.clear()
        if hasattr(self, "engine") and self.engine is not None:
            await self.engine.dispose()

    async def test_register_user_success_201(self) -> None:
        """
        Registro válido crea usuario con rol VIEWER e is_active=True,
        retorna HTTP 201 bajo APIResponse y no expone password ni hashed_password.
        """
        payload = {
            "email": "  New.Investor@InvestAI.com  ",
            "full_name": "Mattia Risso",
            "password": "StrongRegisterPass!99",
        }
        res = await self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 201)

        body = res.json()
        self.assertTrue(body["success"])
        self.assertIn("meta", body)
        self.assertIn("request_id", body["meta"])

        user_data = body["data"]
        self.assertEqual(user_data["email"], "new.investor@investai.com")
        self.assertEqual(user_data["full_name"], "Mattia Risso")
        self.assertEqual(user_data["role"], "VIEWER")
        self.assertTrue(user_data["is_active"])
        self.assertIn("id", user_data)
        self.assertIn("created_at", user_data)
        self.assertIn("updated_at", user_data)
        self.assertNotIn("password", user_data)
        self.assertNotIn("hashed_password", user_data)

    async def test_register_mass_assignment_role_rejected_422(self) -> None:
        """
        Enviar 'role': 'ADMIN' o 'is_active': False en el JSON de /api/v1/auth/register
        es rechazado automáticamente con HTTP 422 (extra='forbid').
        """
        # Intento 1: escalación de privilegio inyectando role=ADMIN
        res_role = await self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "attacker.role@investai.com",
                "full_name": "Attacker Role",
                "password": "ValidPassword!123",
                "role": "ADMIN",
            },
        )
        self.assertEqual(res_role.status_code, 422)
        body_role = res_role.json()
        self.assertFalse(body_role["success"])
        self.assertEqual(body_role["error"]["code"], "VALIDATION_ERROR")

        # Intento 2: inyección de atributo is_active
        res_active = await self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "attacker.active@investai.com",
                "full_name": "Attacker Active",
                "password": "ValidPassword!123",
                "is_active": False,
            },
        )
        self.assertEqual(res_active.status_code, 422)
        body_active = res_active.json()
        self.assertFalse(body_active["success"])
        self.assertEqual(body_active["error"]["code"], "VALIDATION_ERROR")

    async def test_register_duplicate_email_409(self) -> None:
        """
        Intentar registrar un email ya existente (incluso variando mayúsculas/espacios)
        retorna HTTP 409 Conflict dentro del APIErrorResponse envelope.
        """
        res = await self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "  TRADER.AUTH@INVESTAI.INTERNAL ",
                "full_name": "Duplicate Attempt",
                "password": "ValidPassword!123",
            },
        )
        self.assertEqual(res.status_code, 409)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "CONFLICT")
        self.assertEqual(body["error"]["message"], "Email already registered")
        self.assertIn("request_id", body["meta"])

    async def test_login_success_200(self) -> None:
        """
        Login con credenciales válidas retorna HTTP 200 con access_token,
        refresh_token, token_type='bearer' y expires_in.
        """
        res = await self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "  TRADER.AUTH@investai.internal ",
                "password": self.raw_password,
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["token_type"], "bearer")
        self.assertGreater(data["expires_in"], 0)

        # Verificar claims de los tokens emitidos
        access_payload = decode_token(data["access_token"], expected_type=TokenType.ACCESS)
        refresh_payload = decode_token(data["refresh_token"], expected_type=TokenType.REFRESH)
        self.assertEqual(access_payload.sub, str(self.active_user.id))
        self.assertEqual(refresh_payload.sub, str(self.active_user.id))
        self.assertNotEqual(access_payload.jti, refresh_payload.jti)

    async def test_login_wrong_password_401(self) -> None:
        """
        Contraseña errónea retorna HTTP 401 con 'Incorrect email or password'
        y cabecera WWW-Authenticate.
        """
        res = await self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.active_user.email,
                "password": "WrongPassword!999",
            },
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)
        self.assertIn("Bearer", res.headers["WWW-Authenticate"])
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(body["error"]["message"], "Incorrect email or password")

    async def test_login_nonexistent_email_401(self) -> None:
        """
        Email no registrado retorna exactamente el mismo HTTP 401
        'Incorrect email or password' (anti-enumeración CWE-204).
        """
        res = await self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "ghost.unknown@investai.internal",
                "password": "SomePassword!123",
            },
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)
        self.assertIn("Bearer", res.headers["WWW-Authenticate"])
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(body["error"]["message"], "Incorrect email or password")

    async def test_login_inactive_user_403(self) -> None:
        """
        Usuario con is_active=False y contraseña correcta recibe HTTP 403
        'Inactive user account'.
        """
        res = await self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.inactive_user.email,
                "password": self.raw_password,
            },
        )
        self.assertEqual(res.status_code, 403)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "FORBIDDEN")
        self.assertEqual(body["error"]["message"], "Inactive user account")

    async def test_refresh_token_rotation_success_200(self) -> None:
        """
        Enviar un refresh_token válido a /api/v1/auth/refresh emite un nuevo par
        de tokens con JTIs renovados.
        """
        initial_refresh = create_refresh_token(
            subject=self.active_user.id,
            role=self.active_user.role,
            email=self.active_user.email,
        )
        initial_payload = decode_token(initial_refresh, expected_type=TokenType.REFRESH)

        res = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": initial_refresh},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        data = body["data"]

        new_access_payload = decode_token(data["access_token"], expected_type=TokenType.ACCESS)
        new_refresh_payload = decode_token(data["refresh_token"], expected_type=TokenType.REFRESH)

        self.assertEqual(new_access_payload.sub, str(self.active_user.id))
        self.assertEqual(new_refresh_payload.sub, str(self.active_user.id))
        self.assertNotEqual(new_refresh_payload.jti, initial_payload.jti)
        self.assertNotEqual(new_access_payload.jti, new_refresh_payload.jti)

    async def test_refresh_with_access_token_rejected_401(self) -> None:
        """
        Enviar un access_token al endpoint /api/v1/auth/refresh es bloqueado
        con HTTP 401 (anti-token confusion).
        """
        access_token = create_access_token(
            subject=self.active_user.id,
            role=self.active_user.role,
            email=self.active_user.email,
        )
        res = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("WWW-Authenticate", res.headers)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(body["error"]["message"], "Invalid refresh token")

    async def test_refresh_expired_or_tampered_token_401(self) -> None:
        """
        Enviar un refresh token expirado o adulterado retorna HTTP 401
        con cabecera WWW-Authenticate.
        """
        # Caso 1: Refresh token expirado (más allá del leeway de 10s)
        expired_refresh = create_refresh_token(
            subject=self.active_user.id,
            role=self.active_user.role,
            email=self.active_user.email,
            expires_delta=timedelta(seconds=-60),
        )
        res_exp = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": expired_refresh},
        )
        self.assertEqual(res_exp.status_code, 401)
        self.assertIn("WWW-Authenticate", res_exp.headers)
        self.assertEqual(res_exp.json()["error"]["message"], "Refresh token has expired")

        # Caso 2: Refresh token con firma adulterada
        valid_refresh = create_refresh_token(
            subject=self.active_user.id,
            role=self.active_user.role,
        )
        tampered_refresh = valid_refresh[:-5] + "XXXXX"
        res_tampered = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tampered_refresh},
        )
        self.assertEqual(res_tampered.status_code, 401)
        self.assertIn("WWW-Authenticate", res_tampered.headers)
        self.assertEqual(res_tampered.json()["error"]["message"], "Invalid refresh token")

    async def test_refresh_inactive_user_rejected_403(self) -> None:
        """
        Si el usuario está desactivado en DB después de emitir el refresh token,
        /api/v1/auth/refresh rechaza la renovación con HTTP 403.
        """
        inactive_refresh = create_refresh_token(
            subject=self.inactive_user.id,
            role=self.inactive_user.role,
            email=self.inactive_user.email,
        )
        res = await self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": inactive_refresh},
        )
        self.assertEqual(res.status_code, 403)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "FORBIDDEN")
        self.assertEqual(body["error"]["message"], "Inactive user account")

    async def test_get_me_authenticated_200_and_unauthenticated_401(self) -> None:
        """
        Con Authorization: Bearer <access_token> retorna HTTP 200 con el perfil en /api/v1/auth/me;
        sin token o con un refresh token retorna HTTP 401.
        """
        access_token = create_access_token(
            subject=self.active_user.id,
            role=self.active_user.role,
            email=self.active_user.email,
        )
        refresh_token = create_refresh_token(
            subject=self.active_user.id,
            role=self.active_user.role,
            email=self.active_user.email,
        )

        # 1. Con Access Token válido -> 200 OK
        res_ok = await self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(res_ok.status_code, 200)
        body_ok = res_ok.json()
        self.assertTrue(body_ok["success"])
        self.assertEqual(body_ok["data"]["id"], str(self.active_user.id))
        self.assertEqual(body_ok["data"]["email"], self.active_user.email)
        self.assertEqual(body_ok["data"]["role"], "TRADER")
        self.assertNotIn("hashed_password", body_ok["data"])

        # 2. Sin cabecera Authorization -> 401 Unauthorized
        res_no_token = await self.client.get("/api/v1/auth/me")
        self.assertEqual(res_no_token.status_code, 401)
        self.assertFalse(res_no_token.json()["success"])

        # 3. Con Refresh Token en vez de Access Token -> 401 Unauthorized
        res_refresh_as_access = await self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        self.assertEqual(res_refresh_as_access.status_code, 401)
        self.assertFalse(res_refresh_as_access.json()["success"])


if __name__ == "__main__":
    unittest.main()

