"""
Declarative Base registry for SQLAlchemy ORM models.
Ensures all database models are discovered and attached to Base.metadata.
"""

from app.core.database import Base
from app.infrastructure.db.models.market_data import MarketBarModel
from app.infrastructure.db.models.user import UserModel

__all__ = [
    "Base",
    "MarketBarModel",
    "UserModel",
]
