import unittest
from app.domain.models.asset import Asset, AssetType, Currency, Sector
from app.domain.models.portfolio import Holding, InvestorProfile, Portfolio
from app.domain.rules.rebalancing import (
    OrderSide,
    RebalancePlan,
    TargetAllocation,
    ToleranceBandRebalancer,
)


class TestToleranceBandRebalancer(unittest.TestCase):
    def setUp(self):
        self.aapl = Asset("AAPL", "Apple Inc.", AssetType.CEDEAR, Currency.ARS, Sector.TECHNOLOGY, "US", 10.0)
        self.msft = Asset("MSFT", "Microsoft Corp.", AssetType.CEDEAR, Currency.ARS, Sector.TECHNOLOGY, "US", 10.0)
        self.al30 = Asset("AL30", "Bono AL30", AssetType.BOND_SOVEREIGN, Currency.ARS, Sector.GOVERNMENT, "AR")

    def test_rebalance_excess_generates_sell(self):
        h_aapl = Holding(self.aapl, quantity=60, average_buy_price=1000.0, current_price=1000.0)
        h_al30 = Holding(self.al30, quantity=40, average_buy_price=1000.0, current_price=1000.0)
        portfolio = Portfolio("p1", "Excess Port", InvestorProfile.MODERATE, [h_aapl, h_al30])

        targets = [
            TargetAllocation(ticker="AAPL", target_weight=30.0, tolerance_band=5.0),
        ]

        orders = ToleranceBandRebalancer.calculate_orders(portfolio, targets)
        self.assertEqual(len(orders), 1)

        order = orders[0]
        self.assertEqual(order.ticker, "AAPL")
        self.assertEqual(order.side, OrderSide.SELL)
        self.assertEqual(order.current_weight, 60.0)
        self.assertEqual(order.target_weight, 30.0)
        self.assertEqual(order.delta_weight, -30.0)
        self.assertEqual(order.delta_amount, -30000.0)
        self.assertEqual(order.estimated_shares, 30)
        self.assertIn("sobreponderado", order.justification)

    def test_rebalance_deficit_generates_buy(self):
        h_aapl = Holding(self.aapl, quantity=10, average_buy_price=1000.0, current_price=1000.0)
        h_al30 = Holding(self.al30, quantity=90, average_buy_price=1000.0, current_price=1000.0)
        portfolio = Portfolio("p2", "Deficit Port", InvestorProfile.MODERATE, [h_aapl, h_al30])

        targets = [
            TargetAllocation(ticker="AAPL", target_weight=35.0, tolerance_band=5.0),
        ]

        orders = ToleranceBandRebalancer.calculate_orders(portfolio, targets)
        self.assertEqual(len(orders), 1)

        order = orders[0]
        self.assertEqual(order.ticker, "AAPL")
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.current_weight, 10.0)
        self.assertEqual(order.target_weight, 35.0)
        self.assertEqual(order.delta_weight, 25.0)
        self.assertEqual(order.delta_amount, 25000.0)
        self.assertEqual(order.estimated_shares, 25)
        self.assertIn("subponderado", order.justification)

    def test_rebalance_within_tolerance_band(self):
        h_aapl = Holding(self.aapl, quantity=23, average_buy_price=1000.0, current_price=1000.0)
        h_al30 = Holding(self.al30, quantity=77, average_buy_price=1000.0, current_price=1000.0)
        portfolio = Portfolio("p3", "Within Band", InvestorProfile.MODERATE, [h_aapl, h_al30])

        targets = [
            TargetAllocation(ticker="AAPL", target_weight=20.0, tolerance_band=5.0),
        ]

        orders_filtered = ToleranceBandRebalancer.calculate_orders(portfolio, targets, include_hold=False)
        self.assertEqual(len(orders_filtered), 0)

        orders_hold = ToleranceBandRebalancer.calculate_orders(portfolio, targets, include_hold=True)
        self.assertEqual(len(orders_hold), 1)
        self.assertEqual(orders_hold[0].side, OrderSide.HOLD)
        self.assertEqual(orders_hold[0].estimated_shares, 0)
        self.assertIn("dentro de la banda de tolerancia", orders_hold[0].justification)

    def test_integer_share_truncation(self):
        h_aapl = Holding(self.aapl, quantity=10, average_buy_price=1000.0, current_price=1000.0)
        h_al30 = Holding(self.al30, quantity=90, average_buy_price=1000.0, current_price=1000.0)
        portfolio = Portfolio("p4", "Truncation Port", InvestorProfile.MODERATE, [h_aapl, h_al30])

        targets = [
            TargetAllocation(ticker="AAPL", target_weight=25.0, tolerance_band=5.0),
        ]
        prices = {"AAPL": 7000.0}

        orders = ToleranceBandRebalancer.calculate_orders(portfolio, targets, prices=prices)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].estimated_shares, 2)
        self.assertIsInstance(orders[0].estimated_shares, int)

    def test_liquidity_conservation_sufficient_and_deficit(self):
        h_aapl = Holding(self.aapl, quantity=60, average_buy_price=1000.0, current_price=1000.0)
        h_al30 = Holding(self.al30, quantity=30, average_buy_price=1000.0, current_price=1000.0)
        portfolio = Portfolio(
            id="p5",
            name="Liquidity Port",
            investor_profile="MODERATE",
            holdings=[h_aapl, h_al30],
            cash_balance_ars=10000.0,
        )

        targets = [
            TargetAllocation(ticker="AAPL", target_weight=30.0, tolerance_band=5.0),
            TargetAllocation(ticker="MSFT", target_weight=35.0, tolerance_band=5.0),
        ]
        prices = {"AAPL": 1000.0, "MSFT": 1000.0}

        plan_sufficient = ToleranceBandRebalancer.generate_plan(portfolio, targets, prices=prices)
        self.assertTrue(plan_sufficient.is_liquidity_sufficient)
        self.assertIsNone(plan_sufficient.liquidity_warning)
        self.assertEqual(plan_sufficient.total_sell_amount, 30000.0)
        self.assertEqual(plan_sufficient.total_buy_amount, 35000.0)

        portfolio_no_cash = Portfolio(
            id="p6",
            name="No Cash Port",
            investor_profile="MODERATE",
            holdings=[h_aapl, h_al30],
            cash_balance_ars=0.0,
        )
        targets_large_buy = [
            TargetAllocation(ticker="AAPL", target_weight=30.0, tolerance_band=5.0),
            TargetAllocation(ticker="MSFT", target_weight=60.0, tolerance_band=5.0),
        ]
        plan_deficit = ToleranceBandRebalancer.generate_plan(portfolio_no_cash, targets_large_buy, prices=prices)
        self.assertFalse(plan_deficit.is_liquidity_sufficient)
        self.assertIsNotNone(plan_deficit.liquidity_warning)
        self.assertIn("Alerta de Liquidez", plan_deficit.liquidity_warning)

    def test_target_allocation_validation(self):
        with self.assertRaises(ValueError):
            TargetAllocation(ticker="AAPL", target_weight=-5.0)
        with self.assertRaises(ValueError):
            TargetAllocation(ticker="AAPL", target_weight=110.0)
        with self.assertRaises(ValueError):
            TargetAllocation(ticker="AAPL", target_weight=20.0, tolerance_band=-1.0)


if __name__ == "__main__":
    unittest.main()
