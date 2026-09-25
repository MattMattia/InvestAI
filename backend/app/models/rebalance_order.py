import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.portfolio import PortfolioModel


class RebalanceOrderModel(Base):
    __tablename__ = "rebalance_orders"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    portfolio_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    current_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    target_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    delta_amount: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    estimated_shares: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    price_used: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING",
        nullable=False,
    )
    justification: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    portfolio: Mapped["PortfolioModel"] = relationship(
        "PortfolioModel",
        back_populates="rebalance_orders",
    )
