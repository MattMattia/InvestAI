from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MarketExchange(str, Enum):
    """Supported market exchanges for dual-listed instruments."""

    BYMA = "BYMA"  # Bolsas y Mercados Argentinos (Buenos Aires)
    NYSE = "NYSE"  # New York Stock Exchange
    NASDAQ = "NASDAQ"  # Nasdaq Stock Market


class QuoteState(str, Enum):
    """Real-time liquidity and freshness state of a market price."""

    ACTIVE = "ACTIVE"  # Fresh quote from active trading session
    STALE_MARKET_CLOSED = (
        "STALE_MARKET_CLOSED"  # Forward-filled price because local exchange was closed
    )


class SynchronizedPriceQuote(BaseModel):
    """
    Immutable representation of cross-market synchronized price quotes.
    Integrates forward-fill metadata and implicit Contado con Liquidación (CCL).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    ticker: str = Field(description="Asset ticker symbol, e.g. 'AAPL', 'NVDA'")
    target_date: date = Field(description="Target business date for the valuation")
    byma_price: float = Field(
        ge=0.0, description="Effective BYMA price in ARS (fresh or forward-filled)"
    )
    nyse_price: float = Field(
        ge=0.0, description="Effective NYSE/NASDAQ price in USD (fresh or forward-filled)"
    )
    byma_status: QuoteState = Field(
        description="State of the BYMA quote (ACTIVE or STALE_MARKET_CLOSED)"
    )
    nyse_status: QuoteState = Field(
        description="State of the US quote (ACTIVE or STALE_MARKET_CLOSED)"
    )
    is_stale: bool = Field(
        default=False, description="True if at least one leg of the dual listing is stale/closed"
    )
    implicit_ccl: float | None = Field(
        default=None, description="Implicit CCL exchange rate if computable"
    )
    stale_reason: str | None = Field(
        default=None, description="Deterministic explanation of why price is stale"
    )
