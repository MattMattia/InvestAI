"""
Suite de pruebas unitarias para contratos canónicos de identidad y usuario (Módulo 5.1 - Fase 1).
Verifica validación de contraseñas (largo y UTF-8 byte boundary para bcrypt DoS),
enmascaramiento SecretStr, validación RFC de email, inmutabilidad y política extra='forbid'.
"""

import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserResponse,
    UserRole,
)
from pydantic import SecretStr, ValidationError


@pytest.mark.unit
class TestUserContracts(unittest.TestCase):
    """Pruebas unitarias de esquemas y validaciones de identidad."""

    def test_valid_user_create(self):
        """Valida creación exitosa de UserCreate con defaults correctos."""
        user = UserCreate(
            email="  Trader.Quant@InvestAI.com  ",
            full_name="Quant Trader",
            password=SecretStr("StrongP@ssw0rd!"),
        )
        assert user.email == "trader.quant@investai.com"
        assert user.full_name == "Quant Trader"
        assert user.role == UserRole.VIEWER
        assert user.is_active is True
        assert isinstance(user.password, SecretStr)
        assert user.password.get_secret_value() == "StrongP@ssw0rd!"

    def test_password_minimum_length_rejected(self):
        """Valida que contraseñas menores a 8 caracteres sean rechazadas."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="user@investai.com",
                full_name="Short Pass",
                password=SecretStr("1234567"),  # 7 chars
            )
        assert "Password must be at least 8 characters long" in str(exc_info.value)

    def test_password_maximum_bytes_utf8_rejected(self):
        """
        Valida que contraseñas que exceden 72 bytes en UTF-8 sean rechazadas.
        Protección fundamental contra ataques de denegación de servicio (DoS) en bcrypt.
        """
        # 73 caracteres ASCII = 73 bytes
        long_ascii = "A" * 73
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="user@investai.com",
                full_name="Long Pass",
                password=SecretStr(long_ascii),
            )
        assert "Password cannot exceed 72 bytes" in str(exc_info.value)

        # Caracteres multi-byte: cada emoji es 4 bytes en UTF-8. 19 emojis = 76 bytes (> 72 bytes)
        multibyte_pass = "🔒" * 19
        assert len(multibyte_pass.encode("utf-8")) == 76
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="user@investai.com",
                full_name="Unicode Pass",
                password=SecretStr(multibyte_pass),
            )
        assert "Password cannot exceed 72 bytes" in str(exc_info.value)

    def test_password_boundary_at_72_bytes_accepted(self):
        """Valida que una contraseña de exactamente 72 bytes sea aceptada."""
        exact_72_bytes = "B" * 72
        user = UserCreate(
            email="user@investai.com",
            full_name="Boundary Pass",
            password=SecretStr(exact_72_bytes),
        )
        assert len(user.password.get_secret_value().encode("utf-8")) == 72

    def test_password_secret_str_masking(self):
        """
        Garantiza que el valor de la contraseña jamás sea expuesto en logs,
        representaciones textuales (str / repr) o dump serializado.
        """
        raw_secret = "VerySecretPassword123!"
        user = UserCreate(
            email="security@investai.com",
            full_name="Security Officer",
            password=SecretStr(raw_secret),
        )

        # str() y repr() deben contener la máscara de asteriscos
        assert raw_secret not in str(user.password)
        assert raw_secret not in repr(user.password)
        assert "**********" in str(user.password)

        # repr(user) tampoco debe mostrar el texto plano
        assert raw_secret not in repr(user)

        # model_dump() expone SecretStr, no el string plano
        dumped = user.model_dump()
        assert isinstance(dumped["password"], SecretStr)
        assert raw_secret not in str(dumped["password"])

    def test_email_normalization_and_formatting(self):
        """Valida normalización a minúsculas, strip de espacios y soporte de subdominios y tags."""
        valid_emails = [
            ("  admin@investai.com  ", "admin@investai.com"),
            ("Trader.One+tag@sub.domain.co", "trader.one+tag@sub.domain.co"),
            ("user_name-123@host-server.net", "user_name-123@host-server.net"),
        ]
        for raw, expected in valid_emails:
            user = UserBase(
                email=raw,
                full_name="Valid Email Test",
            )
            assert user.email == expected

    def test_invalid_email_formats_rejected(self):
        """Valida que correos sin formato RFC 5321/5322 sean rechazados con ValueError."""
        invalid_emails = [
            "plainaddress",
            "@missingusername.com",
            "username@.com",
            "username@com",
            "user name@domain.com",
            "user@domain..com",
            "",
        ]
        for bad_email in invalid_emails:
            with pytest.raises(ValidationError) as exc_info:
                UserBase(email=bad_email, full_name="Invalid Email Test")
            assert "Invalid email format" in str(exc_info.value) or "email" in str(exc_info.value)

    def test_user_response_serialization_excludes_secrets(self):
        """
        Garantiza que UserResponse jamás contenga campos de credenciales
        como password o hashed_password.
        """
        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        response_dto = UserResponse(
            id=user_id,
            email="investor@investai.com",
            full_name="Carlos Investor",
            role=UserRole.TRADER,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        dumped = response_dto.model_dump()
        assert "password" not in dumped
        assert "hashed_password" not in dumped
        assert dumped["id"] == user_id
        assert dumped["role"] == UserRole.TRADER
        assert dumped["email"] == "investor@investai.com"

        # Verificar campos declarados en el modelo
        assert "password" not in UserResponse.model_fields
        assert "hashed_password" not in UserResponse.model_fields

    def test_extra_fields_forbidden(self):
        """Valida que campos no declarados sean estrictamente rechazados (extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="user@investai.com",
                full_name="Extra Fields",
                password=SecretStr("ValidPassword123"),
                unauthorized_field="malicious_payload",
            )
        assert "extra_forbidden" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            UserResponse(
                id=uuid.uuid4(),
                email="user@investai.com",
                full_name="Extra Response",
                role=UserRole.VIEWER,
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                hashed_password="forbidden_hash",
            )
        assert "extra_forbidden" in str(exc_info.value)

    def test_timestamp_utc_enforcement(self):
        """Valida que los timestamps naive se conviertan a UTC explícito."""
        user_id = uuid.uuid4()
        naive_now = datetime(2026, 10, 10, 12, 0, 0)  # Naive (sin tzinfo)
        response_dto = UserResponse(
            id=user_id,
            email="utc@investai.com",
            full_name="UTC Test",
            created_at=naive_now,
            updated_at=naive_now,
        )
        assert response_dto.created_at.tzinfo == UTC
        assert response_dto.updated_at.tzinfo == UTC

        # Con timezone no-UTC (UTC-3)
        tz_art = timezone(timedelta(hours=-3))
        aware_now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=tz_art)
        response_dto_aware = UserResponse(
            id=user_id,
            email="utc2@investai.com",
            full_name="UTC Test Aware",
            created_at=aware_now,
            updated_at=aware_now,
        )
        assert response_dto_aware.created_at.tzinfo == UTC
        assert response_dto_aware.created_at.hour == 15  # 12:00 -03:00 == 15:00 UTC


if __name__ == "__main__":
    unittest.main()
