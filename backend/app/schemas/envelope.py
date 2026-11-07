"""
Contratos de Transporte y Esquema Universal Envelope (ARQ-02).
Define estructuras inmutables y fuertemente tipadas para respuestas de éxito y error en la API.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

logger = logging.getLogger("investai.envelope")


def _default_request_id() -> str:
    """Resuelve el request_id activo del contexto ASGI o genera un UUIDv4."""
    try:
        from app.api.middleware.trace import get_current_request_id

        req_id = get_current_request_id()
        if req_id:
            return req_id
    except Exception as exc:
        logger.debug("Request id lookup failed, generating a new one: %s", exc)
    return str(uuid.uuid4())


class BaseSchema(BaseModel):
    """Esquema base inmutable con validación estricta y sanitización de frontera (Pydantic v2)."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class ResponseMeta(BaseSchema):
    """Metadatos de observabilidad, trazabilidad y telemetría de solicitud."""

    request_id: str = Field(default_factory=_default_request_id)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    execution_time_ms: float | None = None


class APIResponse(BaseSchema, Generic[T]):
    """Envoltorio canónico universal para respuestas exitosas."""

    success: bool = True
    data: T
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


class SubErrorDetail(BaseSchema):
    """Detalle granular de error de validación o campo específico."""

    field: str | None = None
    issue: str


class ErrorDetail(BaseSchema):
    """Detalle de error estandarizado con código taxonómico y detalles secundarios."""

    code: str
    message: str
    details: list[SubErrorDetail] = Field(default_factory=list)


class APIErrorResponse(BaseSchema):
    """Envoltorio canónico universal para respuestas de error de la API."""

    success: bool = False
    error: ErrorDetail
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
