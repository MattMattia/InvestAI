"""Domain Models Package — InvestAI SQLAlchemy 2.0 ORM Entities."""

from app.infrastructure.db.models.market_data import MarketBarModel
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.models.rebalance_order import RebalanceOrderModel
from app.models.risk_audit import RiskAuditSnapshotModel
from app.models.user import UserModel

# Canonical domain aliases for unified vocabulary
OrderModel = RebalanceOrderModel
AuditLogModel = RiskAuditSnapshotModel

__all__ = [
    "UserModel",
    "AssetModel",
    "PortfolioModel",
    "HoldingModel",
    "RiskAuditSnapshotModel",
    "AuditLogModel",
    "RebalanceOrderModel",
    "OrderModel",
    "MarketBarModel",
]
