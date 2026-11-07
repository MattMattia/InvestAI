from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.holding import HoldingModel


class AssetModel(Base):
    __tablename__ = "assets"

    ticker: Mapped[str] = mapped_column(
        String(30),
        primary_key=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    asset_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(10),
        default="ARS",
        nullable=False,
    )
    sector: Mapped[str] = mapped_column(
        String(100),
        default="OTHER",
        nullable=False,
    )
    market: Mapped[str] = mapped_column(
        String(50),
        default="BYMA",
        nullable=False,
    )
    cedear_ratio: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    underlying_ticker: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    # --- Métricas Históricas Cuantitativas (Ventana hasta 10 Años / Máx. Antigüedad) ---
    history_start_date: Mapped[str | None] = mapped_column(
        String(20),
        default="2016-11-01",
        nullable=True,
    )
    history_years_available: Mapped[float] = mapped_column(
        Float,
        default=10.0,
        nullable=False,
    )
    data_points_count: Mapped[int] = mapped_column(
        Integer,
        default=2520,
        nullable=False,
    )
    cagr_annualized: Mapped[float] = mapped_column(
        Float,
        default=0.12,
        nullable=False,
    )
    volatility_annualized: Mapped[float] = mapped_column(
        Float,
        default=0.25,
        nullable=False,
    )
    sharpe_ratio: Mapped[float] = mapped_column(
        Float,
        default=0.48,
        nullable=False,
    )
    sortino_ratio: Mapped[float] = mapped_column(
        Float,
        default=0.68,
        nullable=False,
    )
    max_drawdown: Mapped[float] = mapped_column(
        Float,
        default=0.28,
        nullable=False,
    )
    beta_market: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )
    var_95_daily: Mapped[float] = mapped_column(
        Float,
        default=0.026,
        nullable=False,
    )

    # --- Indicadores Fundamentales (Renta Variable / CEDEARs) y Renta Fija (Bonos) ---
    pe_ratio: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    pb_ratio: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    roe_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    debt_to_equity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    dividend_yield_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    market_cap_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    ytm_tir_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    modified_duration: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    parity_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    metrics_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    metrics_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    holdings: Mapped[list["HoldingModel"]] = relationship(
        "HoldingModel",
        back_populates="asset",
    )
