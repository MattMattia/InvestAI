"""
Pruebas unitarias herméticas para dependencias de seguridad y control RBAC (Módulo 5.3 - Fase 1).
Verifica extracción de Bearer Tokens, resolución y coerción de UserModel, validación de estado activo
y jerarquía de autorización RBAC (VIEWER, TRADER, ADMIN).
"""

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.deps import (
    get_current_active_user,
    get_current_token_payload,
    get_current_user,
    require_admin,
    require_trader_or_admin,
)
from app.core.security import create_access_token, create_refresh_token
from app.models.user import UserModel
from app.schemas.token import TokenPayload, TokenType
from app.schemas.user import UserRole
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.unit
class TestSecurityDependenciesUnit(unittest.IsolatedAsyncioTestCase):
    """Suite de pruebas unitarias herméticas para dependencias de seguridad OAuth2 y RBAC."""

    # -------------------------------------------------------------------------
    # 1. Pruebas de get_current_token_payload
    # -------------------------------------------------------------------------

    async def test_get_current_token_payload_valid_token(self) -> None:
        """Verifica la decodificación y mapeo exitoso de un token válido a TokenPayload."""
        user_uuid = uuid.uuid4()
        token = create_access_token(
            subject=str(user_uuid),
            role=UserRole.TRADER,
            email="trader@investai.internal",
        )

        payload = await get_current_token_payload(token=token)

        self.assertIsInstance(payload, TokenPayload)
        self.assertEqual(payload.sub, str(user_uuid))
        self.assertEqual(payload.role, UserRole.TRADER)
        self.assertEqual(payload.type, TokenType.ACCESS)
        self.assertEqual(payload.email, "trader@investai.internal")

    async def test_get_current_token_payload_expired_token_raises_401(self) -> None:
        """Verifica que un token expirado lance HTTP 401 con cabecera WWW-Authenticate adecuada."""
        token = create_access_token(
            subject="expired_subject",
            role=UserRole.VIEWER,
            expires_delta=timedelta(seconds=-10),
        )

        with self.assertRaises(HTTPException) as ctx:
            await get_current_token_payload(token=token)

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(ctx.exception.detail, "Token has expired")
        self.assertIn("WWW-Authenticate", ctx.exception.headers)
        auth_header = ctx.exception.headers["WWW-Authenticate"]
        self.assertIn('Bearer error="invalid_token"', auth_header)
        self.assertIn('error_description="The token has expired"', auth_header)

    async def test_get_current_token_payload_tampered_token_raises_401(self) -> None:
        """Verifica que un token con firma alterada lance HTTP 401 con WWW-Authenticate."""
        token = create_access_token(
            subject="valid_subject",
            role=UserRole.VIEWER,
        )
        tampered_token = token[:-6] + "BADSIG"

        with self.assertRaises(HTTPException) as ctx:
            await get_current_token_payload(token=tampered_token)

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(ctx.exception.detail, "Could not validate credentials")
        self.assertIn("WWW-Authenticate", ctx.exception.headers)
        self.assertEqual(
            ctx.exception.headers["WWW-Authenticate"],
            'Bearer error="invalid_token"',
        )

    async def test_get_current_token_payload_refresh_token_rejected_raises_401(self) -> None:
        """Verifica que un refresh token sea rechazado al esperar un access token."""
        refresh_token = create_refresh_token(
            subject="subject_with_refresh",
            role=UserRole.ADMIN,
        )

        with self.assertRaises(HTTPException) as ctx:
            await get_current_token_payload(token=refresh_token)

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(ctx.exception.detail, "Could not validate credentials")
        self.assertIn("WWW-Authenticate", ctx.exception.headers)

    # -------------------------------------------------------------------------
    # 2. Pruebas de get_current_user
    # -------------------------------------------------------------------------

    async def test_get_current_user_found_with_uuid_sub(self) -> None:
        """Verifica resolución exitosa de usuario en DB cuando el claim 'sub' es UUID."""
        user_uuid = uuid.uuid4()
        payload = TokenPayload(
            sub=str(user_uuid),
            role=UserRole.TRADER,
            type=TokenType.ACCESS,
            exp=datetime.now(UTC) + timedelta(minutes=15),
            iat=datetime.now(UTC),
            jti=str(uuid.uuid4()),
            email="trader@investai.internal",
        )

        mock_user = MagicMock(spec=UserModel)
        mock_user.id = user_uuid
        mock_user.email = "trader@investai.internal"
        mock_user.role = UserRole.TRADER
        mock_user.is_active = True

        mock_db_result = MagicMock()
        mock_db_result.scalar_one_or_none.return_value = mock_user

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value = mock_db_result

        resolved_user = await get_current_user(payload=payload, db=mock_session)

        self.assertEqual(resolved_user, mock_user)
        mock_session.execute.assert_awaited_once()

    async def test_get_current_user_found_with_legacy_string_sub(self) -> None:
        """Verifica tolerancia y coerción ante 'sub' en formato string legado (no UUID)."""
        legacy_sub = "legacy_string_user_id_42"
        payload = TokenPayload(
            sub=legacy_sub,
            role=UserRole.VIEWER,
            type=TokenType.ACCESS,
            exp=datetime.now(UTC) + timedelta(minutes=15),
            iat=datetime.now(UTC),
            jti=str(uuid.uuid4()),
        )

        mock_user = MagicMock(spec=UserModel)
        mock_user.id = legacy_sub
        mock_user.role = UserRole.VIEWER
        mock_user.is_active = True

        mock_db_result = MagicMock()
        mock_db_result.scalar_one_or_none.return_value = mock_user

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value = mock_db_result

        resolved_user = await get_current_user(payload=payload, db=mock_session)

        self.assertEqual(resolved_user, mock_user)
        mock_session.execute.assert_awaited_once()

    async def test_get_current_user_not_found_raises_401(self) -> None:
        """Verifica que si el usuario no existe en DB, se arroje HTTP 401 con cabecera Bearer."""
        non_existent_uuid = uuid.uuid4()
        payload = TokenPayload(
            sub=str(non_existent_uuid),
            role=UserRole.TRADER,
            type=TokenType.ACCESS,
            exp=datetime.now(UTC) + timedelta(minutes=15),
            iat=datetime.now(UTC),
            jti=str(uuid.uuid4()),
        )

        mock_db_result = MagicMock()
        mock_db_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value = mock_db_result

        with self.assertRaises(HTTPException) as ctx:
            await get_current_user(payload=payload, db=mock_session)

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(ctx.exception.detail, "User not found")
        self.assertEqual(ctx.exception.headers.get("WWW-Authenticate"), "Bearer")

    # -------------------------------------------------------------------------
    # 3. Pruebas de get_current_active_user
    # -------------------------------------------------------------------------

    async def test_get_current_active_user_success(self) -> None:
        """Verifica retorno exitoso del usuario cuando is_active es True."""
        active_user = MagicMock(spec=UserModel)
        active_user.is_active = True
        active_user.role = UserRole.TRADER

        result = await get_current_active_user(current_user=active_user)
        self.assertEqual(result, active_user)

    async def test_get_current_active_user_inactive_raises_403(self) -> None:
        """Verifica bloqueo con HTTP 403 ('Inactive user account') cuando is_active es False."""
        inactive_user = MagicMock(spec=UserModel)
        inactive_user.is_active = False
        inactive_user.role = UserRole.ADMIN

        with self.assertRaises(HTTPException) as ctx:
            await get_current_active_user(current_user=inactive_user)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ctx.exception.detail, "Inactive user account")

    # -------------------------------------------------------------------------
    # 4. Pruebas de RoleChecker y Jerarquía de Seguridad
    # -------------------------------------------------------------------------

    async def test_role_checker_allows_authorized_roles(self) -> None:
        """Verifica que require_trader_or_admin permita acceso a roles TRADER y ADMIN."""
        trader_user = MagicMock(spec=UserModel)
        trader_user.role = UserRole.TRADER
        trader_user.is_active = True

        admin_user = MagicMock(spec=UserModel)
        admin_user.role = UserRole.ADMIN
        admin_user.is_active = True

        res_trader = await require_trader_or_admin(current_user=trader_user)
        self.assertEqual(res_trader, trader_user)

        res_admin = await require_trader_or_admin(current_user=admin_user)
        self.assertEqual(res_admin, admin_user)

    async def test_role_checker_unauthorized_role_raises_403(self) -> None:
        """Verifica denegación de acceso con HTTP 403 ante rol no autorizado (VIEWER)."""
        viewer_user = MagicMock(spec=UserModel)
        viewer_user.role = UserRole.VIEWER
        viewer_user.is_active = True

        with self.assertRaises(HTTPException) as ctx:
            await require_trader_or_admin(current_user=viewer_user)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            ctx.exception.detail,
            "Operation not permitted. Insufficient permissions",
        )

    async def test_role_checker_hierarchy_inactive_admin_blocked(self) -> None:
        """
        Verifica la jerarquía de seguridad: una cuenta inactiva con rol ADMIN es bloqueada
        por get_current_active_user antes de que se evalúe el rol RBAC.
        """
        inactive_admin = MagicMock(spec=UserModel)
        inactive_admin.role = UserRole.ADMIN
        inactive_admin.is_active = False

        # El pipeline de dependencias evalúa primero el estado de la cuenta
        with self.assertRaises(HTTPException) as ctx:
            await get_current_active_user(current_user=inactive_admin)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ctx.exception.detail, "Inactive user account")

    async def test_require_admin_allows_admin_and_blocks_trader_and_viewer(self) -> None:
        """Verifica que require_admin sea exclusivo de ADMIN y deniegue acceso a TRADER y VIEWER."""
        admin_user = MagicMock(spec=UserModel)
        admin_user.role = UserRole.ADMIN

        trader_user = MagicMock(spec=UserModel)
        trader_user.role = UserRole.TRADER

        viewer_user = MagicMock(spec=UserModel)
        viewer_user.role = UserRole.VIEWER

        # ADMIN permitido
        res = await require_admin(current_user=admin_user)
        self.assertEqual(res, admin_user)

        # TRADER denegado
        with self.assertRaises(HTTPException) as ctx_trader:
            await require_admin(current_user=trader_user)
        self.assertEqual(ctx_trader.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            ctx_trader.exception.detail,
            "Operation not permitted. Insufficient permissions",
        )

        # VIEWER denegado
        with self.assertRaises(HTTPException) as ctx_viewer:
            await require_admin(current_user=viewer_user)
        self.assertEqual(ctx_viewer.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            ctx_viewer.exception.detail,
            "Operation not permitted. Insufficient permissions",
        )
