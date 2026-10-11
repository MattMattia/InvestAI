"""
Suite de pruebas unitarias herméticas para el motor criptográfico de tokens JWT (Módulo 5.2 - Fase 1).
Verifica generación, firma, verificación de claims RFC 7519, expiración, detección de tampering,
mitigación de Algorithm Confusion, tolerancia de reloj (leeway) y validación de tipos de token.
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
    decode_token,
)
from app.schemas.token import TokenPayload, TokenResponse, TokenType
from app.schemas.user import UserRole


@pytest.mark.unit
class TestSecurityJWT(unittest.TestCase):
    """Pruebas unitarias para creación, firma y decodificación de tokens JWT."""

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

    def test_token_expiration_raises_expired_token_error(self):
        """Valida que un token expirado en el pasado arroje ExpiredTokenError (subclase de TokenSecurityError)."""
        user_id = str(uuid.uuid4())
        # Emitir con delta negativo en el pasado (-30 segundos)
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

        # Alterar los últimos caracteres de la firma
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
        # Intentar crear token sin firma (alg="none")
        unsecured_token = jwt.encode(payload, key="", algorithm="none")

        with self.assertRaises(InvalidTokenError) as ctx:
            decode_token(unsecured_token)

        self.assertIn("Token is invalid or corrupted", str(ctx.exception))

    def test_clock_leeway_tolerance(self):
        """Valida que pequeñas asimetrías de reloj (leeway de 10s) en nbf/iat no fallen."""
        now = datetime.now(timezone.utc)
        # Token emitido 5 segundos en el futuro (dentro del leeway de 10s)
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

        # Debe decodificar exitosamente gracias a leeway=10
        payload = decode_token(skewed_token)
        self.assertEqual(payload.sub, "skewed_user")

    def test_token_type_validation(self):
        """Valida que un token con type='refresh' sea rechazado al esperar TokenType.ACCESS."""
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

        # Esperando ACCESS: debe fallar con InvalidTokenError
        with self.assertRaises(InvalidTokenError) as ctx:
            decode_token(refresh_token, expected_type=TokenType.ACCESS)
        self.assertIn("Invalid token type: expected access, got refresh", str(ctx.exception))

        # Esperando REFRESH: debe decodificar exitosamente
        decoded_refresh = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        self.assertEqual(decoded_refresh.type, TokenType.REFRESH)

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
            # Faltan exp, iat, jti, type
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
        """Valida inmutabilidad (frozen), rechazo de campos extras y serialización de contratos de token."""
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

        # TokenResponse serialization
        token_str = "eyJhbGciOiJIUzI1NiJ9.sample.signature"
        resp = TokenResponse(
            access_token=token_str,
            token_type="bearer",
            expires_in=1800,
        )
        dumped = resp.model_dump()
        self.assertEqual(dumped["access_token"], token_str)
        self.assertEqual(dumped["token_type"], "bearer")
        self.assertEqual(dumped["expires_in"], 1800)


if __name__ == "__main__":
    unittest.main()

