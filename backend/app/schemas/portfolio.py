import math
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    asset_type: str
    currency: str
    sector: str
    market: str
    cedear_ratio: float | None = None
    underlying_ticker: str | None = None


class HoldingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = Field(..., description="Ticker o código de especie")
    quantity: float = Field(..., description="Cantidad nominal de títulos")
    average_buy_price: float = Field(default=0.0, description="Precio de compra promedio")
    current_price: float = Field(default=0.0, description="Cotización actual de mercado")
    currency: str = Field(default="ARS", description="Moneda (ARS o USD)")
    market: str | None = Field(default="BYMA", description="Plaza bursátil")
    asset_type: str | None = Field(default=None, description="Tipo de activo")
    sector: str | None = Field(default="OTHER", description="Sector económico")

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("El ticker no puede estar vacío.")
        return v.strip().upper()

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("La cantidad debe ser estrictamente positiva (> 0).")
        return v

    @field_validator("average_buy_price", "current_price")
    @classmethod
    def validate_prices(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError("El precio debe ser un valor no negativo (>= 0).")
        return v


class HoldingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: str
    asset_ticker: str
    quantity: float
    average_buy_price: float
    current_price: float
    total_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    weight_pct: float | None = None
    asset: AssetResponse | None = None


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(default="Mi Cartera Principal", min_length=1, max_length=255)
    investor_profile: str = Field(
        default="MODERATE", description="Perfil del inversor: CONSERVATIVE, MODERATE, AGGRESSIVE"
    )
    cash_balance_ars: float = Field(default=0.0, ge=0.0)
    cash_balance_usd: float = Field(default=0.0, ge=0.0)
    holdings: list[HoldingCreate] | None = None

    @field_validator("investor_profile")
    @classmethod
    def validate_investor_profile(cls, v: str) -> str:
        v_upper = v.strip().upper()
        if v_upper not in {"CONSERVATIVE", "MODERATE", "AGGRESSIVE"}:
            raise ValueError("El perfil del inversor debe ser CONSERVATIVE, MODERATE o AGGRESSIVE.")
        return v_upper


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    investor_profile: str | None = Field(
        default=None, description="Perfil del inversor: CONSERVATIVE, MODERATE, AGGRESSIVE"
    )
    cash_balance_ars: float | None = Field(default=None, ge=0.0)
    cash_balance_usd: float | None = Field(default=None, ge=0.0)

    @field_validator("investor_profile")
    @classmethod
    def validate_investor_profile(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_upper = v.strip().upper()
        if v_upper not in {"CONSERVATIVE", "MODERATE", "AGGRESSIVE"}:
            raise ValueError("El perfil del inversor debe ser CONSERVATIVE, MODERATE o AGGRESSIVE.")
        return v_upper


class PortfolioListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    investor_profile: str = "MODERATE"
    cash_balance_ars: float
    cash_balance_usd: float
    total_market_value_ars: float
    holdings_count: int
    updated_at: datetime


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    investor_profile: str = "MODERATE"
    cash_balance_ars: float
    cash_balance_usd: float
    total_market_value_ars: float
    total_market_value_usd: float
    holdings_count: int
    holdings: list[HoldingResponse]
    updated_at: datetime
