"""
Suite de pruebas unitarias herméticas para el motor criptográfico de tokens JWT (Módulo 5.2 - Fases 1 & 2).
Verifica generación, firma, verificación de claims RFC 7519, expiración, detección de tampering,
mitigación de Algorithm Confusion, tolerancia de reloj (leeway), validación de tipos de token (access y refresh),
factoría atómica create_token_pair, contratos RefreshTokenRequest y prevención de Token Confusion.
"""
from datetime import datetime, timedelta, timezone
import unittest
import uuid
import jwt
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.security import (
    ExpiredTokenError,
    InvalidTokenError,
    SecurityError,
    TokenSecurityError,
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_token,
)
from app.schemas.token import (
    RefreshTokenRequest,
    TokenPayload,
    TokenResponse,
    TokenType,
)
from app.schemas.user import UserRole


@pytest.mark.unit
class TestSecurityJWT(unittest.TestCase):
    """Pruebas unitarias para creación, firma, refresh y decodificación de tokens JWT."""

    def test_create_and_decode_access_token_success(self):
        """Valida emisión y decodificación completa de un access token con UUID y UserRole.TRADER."""
        user_id = uuid.uuid4()
        email = "trader.quant@investai.com"

        token = create_access_token(
            subject=user_id,
            role=UserRole.TRADER,
            email=email,
        )

        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

        payload = decode_token(token, expected_type=TokenType.ACCESS)
        self.assertIsInstance(payload, TokenPayload)
        self.assertEqual(payload.sub, str(user_id))
        self.assertEqual(payload.role, UserRole.TRADER)
        self.assertEqual(payload.type, TokenType.ACCESS)
        self.assertEqual(payload.email, email)
        self.assertTrue(len(payload.jti) > 10)
        self.assertEqual(payload.exp.tzinfo, timezone.utc)
        self.assertEqual(payload.iat.tzinfo, timezone.utc)
        self.assertTrue(payload.exp > payload.iat)

    def test_create_and_decode_refresh_token_success(self):
        """Valida emisión y decodificación exitosa de un refresh token con claims y duración en días."""
        user_id = uuid.uuid4()
        email = "investor@investai.com"

        token = create_refresh_token(
            subject=user_id,
            role=UserRole.VIEWER,
            email=email,
        )

        self.assertIsInstance(token, str)
        payload = decode_token(token, expected_type=TokenType.REFRESH)

        self.assertEqual(payload.sub, str(user_id))
        self.assertEqual(payload.role, UserRole.VIEWER)
        self.assertEqual(payload.type, TokenType.REFRESH)
        self.assertEqual(payload.email, email)
        self.assertTrue(len(payload.jti) > 10)

        # Verificar duración aproximada en días (default REFRESH_TOKEN_EXPIRE_DAYS = 7)
        delta_seconds = (payload.exp - payload.iat).total_seconds()
        expected_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
        self.assertAlmostEqual(delta_seconds, expected_seconds, delta=10)

    def test_token_confusion_cross_validation_mitigation(self):
        """
        Valida que un refresh token sea rechazado al esperar access,
        y que un access token sea rechazado al esperar refresh (mitigación de Token Confusion).
        """
        user_id = "test_user_confusion"
        access_tok = create_access_token(subject=user_id, role=UserRole.TRADER)
        refresh_tok = create_refresh_token(subject=user_id, role=UserRole.TRADER)

        # 1. Refresh token presentado como Access token
        with self.assertRaises(InvalidTokenError) as ctx_1:
            decode_token(refresh_tok, expected_type=TokenType.ACCESS)
        self.assertIn("Invalid token type: expected access, got refresh", str(ctx_1.exception))

        # 2. Access token presentado como Refresh token
        with self.assertRaises(InvalidTokenError) as ctx_2:
            decode_token(access_tok, expected_type=TokenType.REFRESH)
        self.assertIn("Invalid token type: expected refresh, got access", str(ctx_2.exception))

    def test_create_token_pair_atomic_factory(self):
        """
        Valida la emisión atómica del par (access + refresh) garantizando
        identificadores JTI independientes, claims esperados y cálculo de expiración.
        """
        user_id = uuid.uuid4()
        email = "pair.tester@investai.com"

        pair = create_token_pair(
            subject=user_id,
            role=UserRole.ADMIN,
            email=email,
        )

        self.assertIsInstance(pair, TokenResponse)
        self.assertIsNotNone(pair.access_token)
        self.assertIsNotNone(pair.refresh_token)
        self.assertEqual(pair.token_type, "bearer")
        self.assertEqual(pair.expires_in, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

        # Decodificar ambos tokens
        access_payload = decode_token(pair.access_token, expected_type=TokenType.ACCESS)
        refresh_payload = decode_token(pair.refresh_token, expected_type=TokenType.REFRESH)

        self.assertEqual(access_payload.type, TokenType.ACCESS)
        self.assertEqual(refresh_payload.type, TokenType.REFRESH)
        self.assertEqual(access_payload.sub, str(user_id))
        self.assertEqual(refresh_payload.sub, str(user_id))

        # JTI estrictamente independientes para aislamiento de revocación
        self.assertNotEqual(access_payload.jti, refresh_payload.jti)

        # Con deltas personalizados
        custom_pair = create_token_pair(
            subject=user_id,
            role=UserRole.ADMIN,
            access_expires_delta=timedelta(minutes=15),
            refresh_expires_delta=timedelta(days=14),
        )
        self.assertEqual(custom_pair.expires_in, 900)

    def test_refresh_token_expiration_raises_expired_token_error(self):
        """Valida que un refresh token emitido en el pasado arroje ExpiredTokenError."""
        user_id = "expired_refresh_user"
        expired_refresh = create_refresh_token(
            subject=user_id,
            role=UserRole.VIEWER,
            expires_delta=timedelta(days=-1),
        )

        with self.assertRaises(ExpiredTokenError) as ctx:
            decode_token(expired_refresh, expected_type=TokenType.REFRESH)

        self.assertIn("Token has expired", str(ctx.exception))

    def test_refresh_token_request_schema_validation(self):
        """Valida el contrato de petición RefreshTokenRequest con límites y extra='forbid'."""
        valid_raw = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy.signature"
        req = RefreshTokenRequest(refresh_token=valid_raw)
        self.assertEqual(req.refresh_token, valid_raw)

        # Rechazo de token vacío o de solo espacios
        with self.assertRaises(ValidationError):
            RefreshTokenRequest(refresh_token="")

        with self.assertRaises(ValidationError):
            RefreshTokenRequest(refresh_token="   ")

        # Rechazo de token que exceda 4096 caracteres
        oversized = "x" * 4097
        with self.assertRaises(ValidationError):
            RefreshTokenRequest(refresh_token=oversized)

        # Aceptación en frontera de 4096 caracteres
        boundary_4096 = "y" * 4096
        req_boundary = RefreshTokenRequest(refresh_token=boundary_4096)
        self.assertEqual(len(req_boundary.refresh_token), 4096)

        # Extra forbidden
        with self.assertRaises(ValidationError):
            RefreshTokenRequest(
                refresh_token=valid_raw,
                unauthorized_extra="payload",
            )

    def test_create_refresh_token_empty_subject_rejected(self):
        """Valida que create_refresh_token rechace sujetos vacíos o solo espacios."""
        for bad_sub in ["", "   "]:
            with self.assertRaises(ValueError) as ctx:
                create_refresh_token(subject=bad_sub, role=UserRole.VIEWER)
            self.assertEqual(str(ctx.exception), "Subject (sub) cannot be empty")

    def test_token_expiration_raises_expired_token_error(self):
        """Valida que un access token expirado en el pasado arroje ExpiredTokenError."""
        user_id = str(uuid.uuid4())
        expired_token = create_access_token(
            subject=user_id,
            role=UserRole.VIEWER,
            expires_delta=timedelta(seconds=-30),
        )

        with self.assertRaises(ExpiredTokenError) as ctx:
            decode_token(expired_token)

        self.assertIn("Token has expired", str(ctx.exception))
        self.assertIsInstance(ctx.exception, TokenSecurityError)
        self.assertIsInstance(ctx.exception, SecurityError)

    def test_tampered_token_raises_invalid_token_error(self):
        """Valida que alterar la firma o el payload de un token arroje InvalidTokenError."""
        token = create_access_token(
            subject="valid_user_id",
            role=UserRole.VIEWER,
        )

        tampered_token = token[:-4] + "wxyz"

        with self.assertRaises(InvalidTokenError) as ctx:
            decode_token(tampered_token)

        self.assertIn("Token is invalid or corrupted", str(ctx.exception))

    def test_wrong_secret_key_raises_invalid_token_error(self):
        """Valida que decodificar un token firmado con una clave secreta ajena arroje InvalidTokenError."""
        now = datetime.now(timezone.utc)
        foreign_payload = {
            "sub": "attacker_user",
            "role": "ADMIN",
            "type": "access",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        foreign_secret = "different-secret-key-with-at-least-32-bytes-long-padding"
        foreign_token = jwt.encode(foreign_payload, foreign_secret, algorithm="HS256")

        with self.assertRaises(InvalidTokenError) as ctx:
            decode_token(foreign_token)

        self.assertIn("Token is invalid or corrupted", str(ctx.exception))

    def test_algorithm_confusion_mitigation_none_rejected(self):
        """Valida que un token con encabezado alg='none' sea rechazado defensivamente por PyJWT."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "fake_admin",
            "role": "ADMIN",
            "type": "access",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        unsecured_token = jwt.encode(payload, key="", algorithm="none")

        with self.assertRaises(InvalidTokenError) as ctx:
            decode_token(unsecured_token)

        self.assertIn("Token is invalid or corrupted", str(ctx.exception))

    def test_clock_leeway_tolerance(self):
        """Valida que pequeñas asimetrías de reloj (leeway de 10s) en nbf/iat no fallen."""
        now = datetime.now(timezone.utc)
        future_skew_payload = {
            "sub": "skewed_user",
            "role": "VIEWER",
            "type": "access",
            "iat": int((now + timedelta(seconds=5)).timestamp()),
            "nbf": int((now + timedelta(seconds=5)).timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        skewed_token = jwt.encode(
            future_skew_payload,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm=settings.JWT_ALGORITHM,
        )

        payload = decode_token(skewed_token)
        self.assertEqual(payload.sub, "skewed_user")

    def test_token_type_validation(self):
        """Valida que la decodificación respete expected_type."""
        now = datetime.now(timezone.utc)
        refresh_payload = {
            "sub": "user_id_123",
            "role": "TRADER",
            "type": "refresh",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        refresh_token = jwt.encode(
            refresh_payload,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm=settings.JWT_ALGORITHM,
        )

        # Sin restricción de tipo (expected_type=None)
        decoded_agnostic = decode_token(refresh_token, expected_type=None)
        self.assertEqual(decoded_agnostic.type, TokenType.REFRESH)

    def test_empty_and_invalid_token_strings_rejected(self):
        """Valida que tokens vacíos, cadenas de espacios o tipos no válidos arrojen InvalidTokenError."""
        invalid_inputs = ["", "   ", None, 12345, "not_a_jwt_string"]
        for bad_token in invalid_inputs:
            with self.assertRaises(InvalidTokenError):
                decode_token(bad_token)  # type: ignore

    def test_missing_required_claims_rejected(self):
        """Valida que un token sin claims obligatorios (exp, iat, sub, type, jti) arroje InvalidTokenError."""
        incomplete_payload = {
            "sub": "user_without_jti",
            "role": "VIEWER",
        }
        incomplete_token = jwt.encode(
            incomplete_payload,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm=settings.JWT_ALGORITHM,
        )

        with self.assertRaises(InvalidTokenError) as ctx:
            decode_token(incomplete_token)
        self.assertIn("Token is invalid or corrupted", str(ctx.exception))

    def test_create_access_token_empty_subject_rejected(self):
        """Valida que create_access_token rechace sujetos vacíos o solo de espacios en blanco."""
        empty_subjects = ["", "   "]
        for bad_sub in empty_subjects:
            with self.assertRaises(ValueError) as ctx:
                create_access_token(subject=bad_sub, role=UserRole.VIEWER)
            self.assertEqual(str(ctx.exception), "Subject (sub) cannot be empty")

    def test_token_payload_and_response_schemas_immutability(self):
        """Valida inmutabilidad (frozen), rechazo de campos extras y serialización de contratos de token con y sin refresh."""
        now = datetime.now(timezone.utc)
        payload = TokenPayload(
            sub="user_abc",
            role=UserRole.ADMIN,
            type=TokenType.ACCESS,
            exp=now + timedelta(minutes=30),
            iat=now,
            jti=str(uuid.uuid4()),
            email="admin@investai.com",
        )

        # Frozen: mutación rechazada
        with self.assertRaises(ValidationError):
            payload.sub = "mutated_user"  # type: ignore

        # Extra forbidden
        with self.assertRaises(ValidationError):
            TokenPayload(
                sub="user_abc",
                role=UserRole.ADMIN,
                exp=now + timedelta(minutes=30),
                iat=now,
                jti=str(uuid.uuid4()),
                unauthorized_claim="malicious",
            )

        # TokenResponse serialization sin refresh_token
        token_str = "eyJhbGciOiJIUzI1NiJ9.sample.access"
        resp = TokenResponse(
            access_token=token_str,
            token_type="bearer",
            expires_in=1800,
        )
        dumped = resp.model_dump()
        self.assertEqual(dumped["access_token"], token_str)
        self.assertIsNone(dumped["refresh_token"])
        self.assertEqual(dumped["token_type"], "bearer")
        self.assertEqual(dumped["expires_in"], 1800)

        # TokenResponse serialization con refresh_token
        refresh_str = "eyJhbGciOiJIUzI1NiJ9.sample.refresh"
        resp_with_refresh = TokenResponse(
            access_token=token_str,
            refresh_token=refresh_str,
            token_type="bearer",
            expires_in=1800,
        )
        dumped_with_refresh = resp_with_refresh.model_dump()
        self.assertEqual(dumped_with_refresh["access_token"], token_str)
        self.assertEqual(dumped_with_refresh["refresh_token"], refresh_str)

    def test_malformed_claim_types_and_timestamp_overflow_raise_invalid_token_error(self):
        """
        Valida que un token firmado con tipos de claims corruptos (ej. role inválido,
        sub vacío o timestamps fuera de rango C time_t) arroje InvalidTokenError y nunca 500.
        """
        now = datetime.now(timezone.utc)
        # Caso 1: Rol inexistente en el enum UserRole
        bad_role_payload = {
            "sub": "user_123",
            "role": "SUPER_HACKER_ROOT",
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        tok_bad_role = jwt.encode(
            bad_role_payload,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm=settings.JWT_ALGORITHM,
        )
        with self.assertRaises(InvalidTokenError):
            decode_token(tok_bad_role)

        # Caso 2: Timestamp exp desbordado (10**16 segundos -> OverflowError / OSError en fromtimestamp)
        overflow_exp_payload = {
            "sub": "user_123",
            "role": "VIEWER",
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": 10**16,
            "jti": str(uuid.uuid4()),
        }
        tok_overflow = jwt.encode(
            overflow_exp_payload,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithm=settings.JWT_ALGORITHM,
        )
        with self.assertRaises(InvalidTokenError):
            decode_token(tok_overflow)


if __name__ == "__main__":
    unittest.main()

