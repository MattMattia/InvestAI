from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Currency(str, Enum):
    """Trading and settlement currencies compliant with OpenBB and Argentine bimonetary standards."""

    ARS = "ARS"  # Argentine Peso
    USD = "USD"  # US Dollar (Standard / Wire / General)
    USD_MEP = "USD_MEP"  # Dólar Bolsa / MEP (Mercado Electrónico de Pagos)
    USD_CCL = "USD_CCL"  # Contado con Liquidación (Cable / 7000)


class FXQuote(BaseModel):
    """
    Immutable Value Object representing an FX rate quote for a specific currency pair.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    pair: str = Field(description="Currency pair, e.g. 'USD/ARS', 'USD_CCL/ARS', 'USD_MEP/ARS'")
    rate: float = Field(gt=0.0, description="Strictly positive exchange rate value")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp of quotation (UTC)"
    )
    source: str = Field(
        default="BYMA",
        description="Source of the quote (e.g., 'BYMA', 'OPENBB', 'ROFEX', 'IMPLICIT_CEDEAR')",
    )

    @field_validator("pair")
    @classmethod
    def validate_pair(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if "/" not in cleaned:
            raise ValueError(
                f"Par de divisas inválido '{v}'. Formato canónico requerido: 'BASE/QUOTE' (ej. 'USD/ARS')."
            )
        parts = cleaned.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Par de divisas con formato incorrecto '{v}'.")
        return cleaned

    @field_validator("rate")
    @classmethod
    def validate_rate(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("El tipo de cambio debe ser un valor estrictamente positivo (> 0).")
        return round(float(v), 4)
