"""
Contratos de Transporte y Esquema Universal Envelope (ARQ-02).
Define estructuras inmutables y fuertemente tipadas para respuestas de éxito y error en la API.
"""
from datetime import datetime, timezone
from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


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

    request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    execution_time_ms: Optional[float] = None


class APIResponse(BaseSchema, Generic[T]):
    """Envoltorio canónico universal para respuestas exitosas."""

    success: bool = True
    data: T
    meta: ResponseMeta


class SubErrorDetail(BaseSchema):
    """Detalle granular de error de validación o campo específico."""

    field: Optional[str] = None
    issue: str


class ErrorDetail(BaseSchema):
    """Detalle de error estandarizado con código taxonómico y detalles secundarios."""

    code: str
    message: str
    details: List[SubErrorDetail] = Field(default_factory=list)


class APIErrorResponse(BaseSchema):
    """Envoltorio canónico universal para respuestas de error de la API."""

    success: bool = False
    error: ErrorDetail
    meta: ResponseMeta

