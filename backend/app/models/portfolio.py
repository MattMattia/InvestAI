import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.holding import HoldingModel
    from app.models.rebalance_order import RebalanceOrderModel
    from app.models.risk_audit import RiskAuditSnapshotModel
    from app.models.user import UserModel


class PortfolioModel(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        default="Portafolio Principal",
        nullable=False,
    )
    investor_profile: Mapped[str] = mapped_column(
        String(50),
        default="MODERATE",
        server_default="MODERATE",
        nullable=False,
    )
    cash_balance_ars: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    cash_balance_usd: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped["UserModel"] = relationship(
        "UserModel",
        back_populates="portfolios",
    )
    holdings: Mapped[list["HoldingModel"]] = relationship(
        "HoldingModel",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    risk_snapshots: Mapped[list["RiskAuditSnapshotModel"]] = relationship(
        "RiskAuditSnapshotModel",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    rebalance_orders: Mapped[list["RebalanceOrderModel"]] = relationship(
        "RebalanceOrderModel",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
