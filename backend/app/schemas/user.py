"""
Contratos canónicos de identidad y usuario (Módulo 5.1 - Fase 1).
DTOs inmutables basados en Pydantic v2 con validación estricta, enmascaramiento SecretStr
y validación defensiva de correos según RFC 5321/5322.
"""
from datetime import datetime, timezone
import enum
import re
from typing import Any
import uuid

from pydantic import ConfigDict, Field, SecretStr, field_validator

from app.schemas.envelope import BaseSchema

# Expresión regular canónica para formato de correo electrónico institucional (RFC 5321 / 5322)
RFC_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")


class UserRole(str, enum.Enum):
    """Roles de acceso y privilegios en la plataforma (RBAC)."""

    VIEWER = "VIEWER"
    TRADER = "TRADER"
    ADMIN = "ADMIN"


class UserBase(BaseSchema):
    """Esquema base de usuario con atributos públicos comunes."""

    email: str = Field(
        max_length=254,
        description="Dirección de correo electrónico institucional (normalizada a minúsculas)",
    )
    full_name: str = Field(
        min_length=2,
        max_length=100,
        description="Nombre completo y apellido del usuario",
    )
    role: UserRole = Field(
        default=UserRole.VIEWER,
        description="Rol jerárquico del usuario para control de acceso (RBAC)",
    )
    is_active: bool = Field(
        default=True,
        description="Indicador de cuenta activa y habilitada para operar",
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        normalized = v.strip().lower()
        if not RFC_EMAIL_REGEX.match(normalized):
            raise ValueError("Invalid email format")
        return normalized


class UserCreate(UserBase):
    """Esquema para registro o creación de usuario con contraseña protegida."""

    password: SecretStr = Field(
        description="Contraseña plana del usuario (enmascarada en memoria)",
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if len(raw) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if len(raw.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes")
        return v


class UserResponse(UserBase):
    """Esquema de respuesta pública de usuario (sin secretos ni hashes)."""

    id: uuid.UUID = Field(description="Identificador único global del usuario (UUIDv4)")
    created_at: datetime = Field(description="Fecha y hora de creación de la cuenta en UTC")
    updated_at: datetime = Field(description="Fecha y hora de última actualización de la cuenta en UTC")

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def ensure_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

