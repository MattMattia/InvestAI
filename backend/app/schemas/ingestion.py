import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawHoldingRecord(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    ticker: str = Field(..., description="Símbolo o ticker bursátil del activo")
    quantity: float = Field(..., description="Cantidad nominal de títulos en cartera (estrictamente positiva)")
    purchase_price: float = Field(default=0.0, description="Precio promedio de compra ponderado")
    current_price: float = Field(default=0.0, description="Precio o cotización de mercado actual")
    currency: str = Field(default="ARS", description="Moneda de denominación (ARS o USD)")
    market: Optional[str] = Field(default=None, description="Plaza de negociación (ej. BCBA, BYMA, NYSE, NASDAQ)")
    asset_type: Optional[str] = Field(default=None, description="Tipo de instrumento financiero")

    @field_validator("ticker", mode="before")
    @classmethod
    def validate_ticker(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("El ticker no puede ser una cadena vacía o nula.")
        return v.strip().upper()

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: Any) -> str:
        if not isinstance(v, str) or not v.strip():
            return "ARS"
        return v.strip().upper()

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("La cantidad debe ser un valor numérico finito.")
        if v <= 0:
            raise ValueError("La cantidad debe ser estrictamente positiva (> 0).")
        return v

    @field_validator("purchase_price", "current_price")
    @classmethod
    def validate_prices(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("El precio debe ser un valor numérico finito.")
        if v < 0:
            raise ValueError("El precio no puede ser negativo (>= 0).")
        return v


class IngestionBatchPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(..., description="Identificador del usuario propietario")
    portfolio_name: str = Field(..., description="Nombre del portafolio destino")
    records: List[RawHoldingRecord] = Field(..., description="Lista de registros de tenencia saneados")
    implicit_fx_rate: Optional[float] = Field(default=None, description="Tipo de cambio implícito CCL/MEP de referencia")

    @field_validator("implicit_fx_rate")
    @classmethod
    def validate_fx_rate(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if not math.isfinite(v) or v <= 0:
                raise ValueError("El tipo de cambio implícito debe ser un valor estrictamente positivo.")
        return v


class IngestionUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: str
    total_rows: int
    valid_records_count: int
    discarded_records_count: int
    is_successful: bool
    has_partial_errors: bool
    errors: List[Dict[str, Any]] = Field(default_factory=list)
