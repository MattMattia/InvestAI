import unittest

from app.core.database import Base
from app.models import (
    AssetModel,
    HoldingModel,
    PortfolioModel,
    RebalanceOrderModel,
    RiskAuditSnapshotModel,
    UserModel,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


class TestPersistenceModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # In-memory SQLite for testing relational schema integrity and relationships
        cls.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(cls.engine)

    def setUp(self):
        self.session: Session = self.SessionLocal()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_schema_metadata_tables_registered(self):
        tables = Base.metadata.tables
        expected_tables = {
            "users",
            "assets",
            "portfolios",
            "holdings",
            "risk_audit_snapshots",
            "rebalance_orders",
        }
        self.assertTrue(expected_tables.issubset(set(tables.keys())))

    def test_user_creation_and_portfolio_relationship(self):
        user = UserModel(
            id="u-1",
            email="investor@investai.com",
            hashed_password="hashed_secret_123",
            investor_profile="AGGRESSIVE",
        )
        self.session.add(user)
        self.session.commit()

        queried_user = (
            self.session.query(UserModel).filter_by(email="investor@investai.com").first()
        )
        self.assertIsNotNone(queried_user)
        self.assertEqual(queried_user.investor_profile, "AGGRESSIVE")
        self.assertEqual(len(queried_user.portfolios), 0)

    def test_full_portfolio_holdings_and_audit_graph(self):
        # 1. User
        user = UserModel(
            id="u-2",
            email="trader@investai.com",
            hashed_password="hashed_secret_456",
            investor_profile="MODERATE",
        )
        self.session.add(user)

        # 2. Assets (Equities / CEDEAR and Sovereign Bonds)
        aapl = AssetModel(
            ticker="AAPL",
            name="Apple Inc. CEDEAR",
            asset_type="CEDEAR",
            currency="ARS",
            sector="TECHNOLOGY",
            market="BYMA",
            cedear_ratio=10.0,
            underlying_ticker="AAPL",
        )
        al30 = AssetModel(
            ticker="AL30",
            name="Bono Soberano AL30",
            asset_type="BOND_SOVEREIGN",
            currency="ARS",
            sector="GOVERNMENT",
            market="BYMA",
        )
        self.session.add_all([aapl, al30])

        # 3. Portfolio
        portfolio = PortfolioModel(
            id="p-1",
            user_id="u-2",
            name="Cartera Modelo",
            cash_balance_ars=50000.0,
            cash_balance_usd=100.0,
        )
        self.session.add(portfolio)

        # 4. Holdings
        h1 = HoldingModel(
            portfolio_id="p-1",
            asset_ticker="AAPL",
            quantity=15.0,
            average_buy_price=1200.0,
            current_price=1350.0,
        )
        h2 = HoldingModel(
            portfolio_id="p-1",
            asset_ticker="AL30",
            quantity=300.0,
            average_buy_price=280.0,
            current_price=310.0,
        )
        self.session.add_all([h1, h2])

        # 5. Risk Audit Snapshot
        snapshot = RiskAuditSnapshotModel(
            id="snap-1",
            portfolio_id="p-1",
            compliance_status="COMPLIANT",
            total_rules_evaluated=7,
            critical_alerts_count=0,
            report_payload={"status": "OK", "evaluated_rules": ["R1", "R2"]},
            notification_status="DELIVERED",
        )
        self.session.add(snapshot)

        # 6. Rebalance Order
        order = RebalanceOrderModel(
            id="ord-1",
            portfolio_id="p-1",
            ticker="AAPL",
            side="SELL",
            current_weight=45.0,
            target_weight=30.0,
            delta_amount=-15000.0,
            estimated_shares=11,
            price_used=1350.0,
            status="PENDING",
            justification="Desvío de 15% supera banda de tolerancia (±5%).",
        )
        self.session.add(order)
        self.session.commit()

        # Query back and verify relationships
        queried_port = self.session.query(PortfolioModel).filter_by(id="p-1").first()
        self.assertIsNotNone(queried_port)
        self.assertEqual(queried_port.user.email, "trader@investai.com")
        self.assertEqual(len(queried_port.holdings), 2)
        self.assertEqual(len(queried_port.risk_snapshots), 1)
        self.assertEqual(len(queried_port.rebalance_orders), 1)

        # Verify holding navigates to asset
        h_aapl = [h for h in queried_port.holdings if h.asset_ticker == "AAPL"][0]
        self.assertEqual(h_aapl.asset.name, "Apple Inc. CEDEAR")
        self.assertEqual(h_aapl.asset.cedear_ratio, 10.0)

        # Verify audit snapshot payload
        snap = queried_port.risk_snapshots[0]
        self.assertEqual(snap.compliance_status, "COMPLIANT")
        self.assertEqual(snap.report_payload["status"], "OK")

        # Verify rebalance order
        ord_queried = queried_port.rebalance_orders[0]
        self.assertEqual(ord_queried.side, "SELL")
        self.assertEqual(ord_queried.status, "PENDING")
        self.assertEqual(ord_queried.estimated_shares, 11)


if __name__ == "__main__":
    unittest.main()
