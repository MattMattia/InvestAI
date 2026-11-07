"""
Esquemas canónicos de autenticación (Módulo 5.4 - Fase 1).
Define contratos de entrada inmutables y blindados contra Mass Assignment (extra="forbid")
para registro e inicio de sesión, con enmascaramiento SecretStr y validación RFC 5321/5322.
"""

import re

from pydantic import Field, SecretStr, field_validator

from app.schemas.envelope import BaseSchema

# Expresión regular canónica para formato de correo electrónico institucional (RFC 5321 / 5322)
RFC_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")

__all__ = [
    "RFC_EMAIL_REGEX",
    "RegisterRequest",
    "LoginRequest",
]


class RegisterRequest(BaseSchema):
    """
    Esquema canónico para solicitud de registro público de usuario.
    Blindado contra Mass Assignment: excluye deliberadamente `role` e `is_active`.
    Con `extra="forbid"`, cualquier intento de inyectar privilegios en el payload es rechazado con HTTP 422.
    """

    email: str = Field(
        max_length=254,
        description="Dirección de correo electrónico institucional (normalizada a minúsculas)",
    )
    full_name: str = Field(
        min_length=2,
        max_length=100,
        description="Nombre completo y apellido del usuario",
    )
    password: SecretStr = Field(
        description="Contraseña plana del usuario (enmascarada en memoria, 8..72 bytes UTF-8)",
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        normalized = v.strip().lower()
        if "\x00" in normalized or not RFC_EMAIL_REGEX.match(normalized):
            raise ValueError("Invalid email format")
        return normalized

    @field_validator("full_name")
    @classmethod
    def validate_full_name_no_null_bytes(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("Full name cannot contain null bytes")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if "\x00" in raw:
            raise ValueError("Password cannot contain null bytes")
        if len(raw) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if len(raw.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes")
        return v


class LoginRequest(BaseSchema):
    """
    Esquema canónico para autenticación de credenciales por correo y contraseña.
    """

    email: str = Field(
        max_length=254,
        description="Dirección de correo electrónico institucional (normalizada a minúsculas)",
    )
    password: SecretStr = Field(
        description="Contraseña del usuario (enmascarada en memoria, 1..72 bytes UTF-8)",
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        normalized = v.strip().lower()
        if "\x00" in normalized or not RFC_EMAIL_REGEX.match(normalized):
            raise ValueError("Invalid email format")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if "\x00" in raw:
            raise ValueError("Password cannot contain null bytes")
        if len(raw) < 1:
            raise ValueError("Password cannot be empty")
        if len(raw.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes")
        return v
