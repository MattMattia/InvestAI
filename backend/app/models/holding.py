from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import AssetModel
    from app.models.portfolio import PortfolioModel


class HoldingModel(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    portfolio_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    asset_ticker: Mapped[str] = mapped_column(
        String(30),
        ForeignKey("assets.ticker", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    average_buy_price: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    current_price: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    portfolio: Mapped["PortfolioModel"] = relationship(
        "PortfolioModel",
        back_populates="holdings",
    )
    asset: Mapped["AssetModel"] = relationship(
        "AssetModel",
        back_populates="holdings",
    )
