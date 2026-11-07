"""
Contratos canónicos de Token y Payload JWT (Módulo 5.2 - Fases 1 & 2).
DTOs inmutables basados en Pydantic v2 para la representación, transporte y
deserialización estricta de claims de seguridad según RFC 7519, incluyendo ciclo de vida de refresh tokens.
"""

import enum
from datetime import UTC, datetime

from pydantic import Field, field_validator

from app.schemas.envelope import BaseSchema
from app.schemas.user import UserRole


class TokenType(str, enum.Enum):
    """Tipos y propósitos canónicos de tokens criptográficos."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseSchema):
    """
    Payload y claims canónicos contenidos dentro del token JWT.
    Sigue las directrices de claims estándar de RFC 7519.
    """

    sub: str = Field(
        min_length=1,
        description="Identificador único del sujeto/usuario (UUID o ID)",
    )
    role: UserRole = Field(
        description="Rol jerárquico del usuario para control de acceso (RBAC)",
    )
    type: TokenType = Field(
        default=TokenType.ACCESS,
        description="Propósito del token (access o refresh)",
    )
    exp: datetime = Field(
        description="Fecha y hora de expiración en UTC",
    )
    iat: datetime = Field(
        description="Fecha y hora de emisión en UTC",
    )
    jti: str = Field(
        min_length=1,
        description="Identificador único global del token (UUIDv4) para trazabilidad y revocación",
    )
    email: str | None = Field(
        default=None,
        description="Correo electrónico asociado al sujeto (opcional)",
    )

    @field_validator("sub")
    @classmethod
    def validate_sub_not_whitespace(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Subject cannot be empty or whitespace")
        return trimmed

    @field_validator("exp", "iat")
    @classmethod
    def ensure_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class TokenResponse(BaseSchema):
    """
    Respuesta canónica de transporte para emisión de tokens de acceso y refresh (OAuth2 Bearer).
    """

    access_token: str = Field(
        description="Token de acceso JWT codificado y firmado criptográficamente",
    )
    refresh_token: str | None = Field(
        default=None,
        description="Token de actualización (Refresh Token) para extender la sesión (opcional)",
    )
    token_type: str = Field(
        default="bearer",
        description="Tipo de token de transporte HTTP (OAuth2 standard 'bearer')",
    )
    expires_in: int = Field(
        description="Vida útil del token expresada en segundos (ej. 1800 para 30 minutos)",
    )


class RefreshTokenRequest(BaseSchema):
    """
    Solicitud de renovación de sesión mediante Refresh Token.
    """

    refresh_token: str = Field(
        min_length=1,
        max_length=4096,
        description="Refresh token criptográfico emitido previamente para renovación de sesión",
    )
