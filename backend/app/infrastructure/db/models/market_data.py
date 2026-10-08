"""
Modelo relacional para series temporales de mercado OHLCV (Módulo 6 - Fase 3).
Permite persistencia particionada por ticker y timeframe con constraint de unicidad temporal.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
import uuid
from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketBarModel(Base):
    """
    Entidad relacional de barra OHLCV histórica en base de datos.
    """

    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "timeframe",
            "timestamp",
            name="uq_market_bar_ticker_tf_timestamp",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    ticker: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    timeframe: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="1d",
        server_default="1d",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    open_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    high_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    low_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    close_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    volume: Mapped[Decimal] = mapped_column(
        Numeric(24, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    vwap: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 4),
        nullable=True,
        default=None,
    )

