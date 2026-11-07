"""
Contratos canónicos de mercado e ingesta en vivo (Módulo 6 - Fase 1 & Fase II 10Y Quant).
DTOs inmutables basados en Pydantic v2 con validación defensiva estricta y precisión Decimal.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field, field_validator, model_validator

from app.schemas.envelope import BaseSchema


class Timeframe(str, Enum):
    """Intervalos temporales estándar para agregaciones de mercado (OHLCV)."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"


class FXType(str, Enum):
    """Tipos de cambio financieros implícitos del mercado de capitales argentino."""

    MEP = "MEP"
    CCL = "CCL"


class MarketQuoteDTO(BaseSchema):
    """
    Cotización de mercado atómica en tiempo real para un instrumento financiero.
    Utiliza Decimal para precisión monetaria estricta y validación temporal UTC.
    """

    ticker: str = Field(description="Símbolo o especie del activo (normalizado a mayúsculas)")
    price: Decimal = Field(description="Último precio operado o precio de referencia")
    bid: Decimal | None = Field(
        default=None, description="Mejor precio de compra (punta compradora)"
    )
    ask: Decimal | None = Field(default=None, description="Mejor precio de venta (punta vendedora)")
    volume: Decimal = Field(default=Decimal("0"), description="Volumen nominal u operado acumulado")
    timestamp: datetime = Field(
        description="Marca temporal de la cotización con zona horaria UTC obligatoria"
    )

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        normalized = v.strip().upper()
        if not normalized:
            raise ValueError("El ticker no puede ser una cadena vacía.")
        return normalized

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("El precio de cotización debe ser estrictamente positivo (> 0).")
        return v

    @field_validator("bid", "ask")
    @classmethod
    def validate_quotes_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= Decimal("0"):
            raise ValueError(
                "Las puntas de mercado (bid/ask) deben ser estrictamente positivas (> 0)."
            )
        return v

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, v: Decimal) -> Decimal:
        if v < Decimal("0"):
            raise ValueError("El volumen operado no puede ser negativo.")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None or v.utcoffset().total_seconds() != 0:
            raise ValueError("Timestamp must include UTC timezone information (offset 0)")
        return v


class MarketBarDTO(BaseSchema):
    """
    Estructura canónica OHLCV (Open, High, Low, Close, Volume) para velas y barras de mercado.
    Implementa validaciones defensivas cruzadas para garantizar integridad geométrica de la barra.
    """

    timestamp: datetime = Field(
        description="Marca temporal de apertura o cierre de la barra en UTC"
    )
    open: Decimal = Field(description="Precio de apertura")
    high: Decimal = Field(description="Precio máximo")
    low: Decimal = Field(description="Precio mínimo")
    close: Decimal = Field(description="Precio de cierre")
    volume: Decimal = Field(description="Volumen negociado durante el período")
    vwap: Decimal | None = Field(
        default=None, description="Precio promedio ponderado por volumen (VWAP)"
    )

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None or v.utcoffset().total_seconds() != 0:
            raise ValueError("Timestamp must include UTC timezone information (offset 0)")
        return v

    @field_validator("open", "high", "low", "close")
    @classmethod
    def validate_positive_prices(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError(
                "Los precios de la barra OHLCV deben ser estrictamente positivos (> 0)."
            )
        return v

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, v: Decimal) -> Decimal:
        if v < Decimal("0"):
            raise ValueError("El volumen de la barra no puede ser negativo.")
        return v

    @model_validator(mode="after")
    def validate_ohlcv_integrity(self) -> "MarketBarDTO":
        min_body = min(self.open, self.close)
        if self.low > min_body:
            raise ValueError(
                f"Barra corrupta: low ({self.low}) no puede ser mayor que min(open, close) ({min_body})."
            )

        max_body = max(self.open, self.close)
        if self.high < max_body:
            raise ValueError(
                f"Barra corrupta: high ({self.high}) no puede ser menor que max(open, close) ({max_body})."
            )

        if self.high < self.low:
            raise ValueError(
                f"Barra corrupta: high ({self.high}) no puede ser estrictamente menor que low ({self.low})."
            )

        if self.vwap is not None:
            if not (self.low <= self.vwap <= self.high):
                raise ValueError("vwap must be between low and high prices")

        return self


class FXRateDTO(BaseSchema):
    """
    Representación estructurada del tipo de cambio financiero implícito (MEP / CCL).
    """

    fx_type: FXType = Field(description="Clasificación del tipo de cambio financiero (MEP o CCL)")
    rate: Decimal = Field(description="Tipo de cambio implícito en ARS/USD")
    base_ticker: str = Field(description="Ticker en moneda local / activo subyacente (ej. AL30)")
    quote_ticker: str = Field(
        description="Ticker en dólares / cable o ADR de referencia (ej. AL30D)"
    )
    spread_pct: Decimal | None = Field(
        default=None, description="Spread bid-ask implícito porcentual si está disponible"
    )
    timestamp: datetime = Field(
        description="Marca temporal de determinación del tipo de cambio (UTC)"
    )

    @field_validator("base_ticker", "quote_ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        normalized = v.strip().upper()
        if not normalized:
            raise ValueError("El ticker no puede estar vacío.")
        return normalized

    @field_validator("rate")
    @classmethod
    def validate_rate(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0"):
            raise ValueError("El tipo de cambio implícito debe ser estrictamente positivo (> 0).")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None or v.utcoffset().total_seconds() != 0:
            raise ValueError("Timestamp must include UTC timezone information (offset 0)")
        return v


class AssetFundamentalQuantMetricsDTO(BaseSchema):
    """
    Métricas cuantitativas históricas de hasta 10 años (o máxima antigüedad desde emisión)
    e indicadores fundamentales / renta fija en tiempo real para un activo financiero.
    """

    ticker: str
    name: str
    asset_type: str
    currency: str
    sector: str
    reference_price: float
    history_start_date: str
    history_years_available: float
    data_points_count: int
    cagr_annualized: float
    volatility_annualized: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    beta_market: float
    var_95_daily: float
    composite_quant_return: float
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    roe_pct: float | None = None
    debt_to_equity: float | None = None
    dividend_yield_pct: float | None = None
    market_cap_usd: float | None = None
    ytm_tir_pct: float | None = None
    modified_duration: float | None = None
    parity_pct: float | None = None
    cedear_ratio: float | None = None
    underlying_ticker: str | None = None
    yahoo_symbol: str | None = None
    adr_symbol: str | None = None
    data_source: str = "BYMA_CALIBRATED_10Y_ENGINE"
    updated_at: str | None = None


class MarketSyncMetricsResponseDTO(BaseSchema):
    """Respuesta de sincronización en lote de métricas cuantitativas de 10 años en la BD."""

    synced_count: int
    tickers: list[str]
    metrics: list[AssetFundamentalQuantMetricsDTO]
