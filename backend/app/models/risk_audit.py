import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.portfolio import PortfolioModel


class RiskAuditSnapshotModel(Base):
    __tablename__ = "risk_audit_snapshots"

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
    compliance_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    total_rules_evaluated: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    critical_alerts_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    report_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    notification_status: Mapped[str] = mapped_column(
        String(50),
        default="PENDING",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    portfolio: Mapped["PortfolioModel"] = relationship(
        "PortfolioModel",
        back_populates="risk_snapshots",
    )
