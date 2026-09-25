from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import Float, String
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
    cedear_ratio: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    underlying_ticker: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
    )

    holdings: Mapped[List["HoldingModel"]] = relationship(
        "HoldingModel",
        back_populates="asset",
    )
