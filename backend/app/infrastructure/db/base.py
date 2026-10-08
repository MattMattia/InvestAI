"""
Declarative Base registry for SQLAlchemy ORM models.
Ensures all database models are discovered and attached to Base.metadata.
"""
from app.core.database import Base
from app.infrastructure.db.models.market_data import MarketBarModel
import app.models  # Registers domain/app models (User, Portfolio, Holding, Asset, etc.)

__all__ = [
    "Base",
    "MarketBarModel",
]

