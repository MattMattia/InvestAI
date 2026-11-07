import unittest

from app.domain.models.order import (
    InvalidOrderStateTransitionError,
    Order,
    OrderSide,
    OrderState,
    OrderType,
)
from app.domain.services.market_frictions import (
    ExecutionCostBreakdown,
    calculate_alyc_commission,
    calculate_market_fees,
    calculate_net_execution_cost,
    calculate_slippage,
)


class TestOrderFSM(unittest.TestCase):
    def test_order_creation_defaults_and_validation(self) -> None:
        order = Order(
            ticker="aapl",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10.0,
            price=220.50,
        )
        self.assertEqual(order.ticker, "AAPL")  # Uppercased and normalized
        self.assertEqual(order.state, OrderState.CREATED)
        self.assertFalse(order.is_terminal)
        self.assertEqual(order.quantity, 10.0)
        self.assertEqual(order.price, 220.50)

    def test_limit_order_requires_price(self) -> None:
        with self.assertRaises(ValueError):
            Order(
                ticker="AL30",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100.0,
                price=None,  # Invalid: LIMIT requires price
            )

    def test_market_order_allows_none_price(self) -> None:
        order = Order(
            ticker="AL30",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100.0,
            price=None,
        )
        self.assertIsNone(order.price)
        self.assertEqual(order.order_type, OrderType.MARKET)

    def test_invalid_quantity_or_price(self) -> None:
        with self.assertRaises(ValueError):
            Order(
                ticker="GGAL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=0.0,  # Invalid: quantity must be > 0
                price=4500.0,
            )

        with self.assertRaises(ValueError):
            Order(
                ticker="GGAL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10.0,
                price=-100.0,  # Invalid: price must be > 0
            )

    def test_valid_lifecycle_transitions(self) -> None:
        order = Order(
            ticker="NVDA",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=50.0,
            price=125.0,
        )
        self.assertEqual(order.state, OrderState.CREATED)

        # 1. CREATED -> VALIDATED
        order.validate()
        self.assertEqual(order.state, OrderState.VALIDATED)
        self.assertFalse(order.is_terminal)

        # 2. VALIDATED -> SUBMITTED
        order.submit()
        self.assertEqual(order.state, OrderState.SUBMITTED)
        self.assertFalse(order.is_terminal)

        # 3. SUBMITTED -> FILLED
        order.fill(filled_qty=50.0, filled_price=125.10)
        self.assertEqual(order.state, OrderState.FILLED)
        self.assertTrue(order.is_terminal)
        self.assertEqual(order.filled_quantity, 50.0)
        self.assertEqual(order.filled_avg_price, 125.10)

    def test_cancellation_from_non_terminal_states(self) -> None:
        # Can cancel from CREATED
        o1 = Order(ticker="YPFD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=20.0)
        o1.cancel(reason="User changed mind")
        self.assertEqual(o1.state, OrderState.CANCELLED)
        self.assertTrue(o1.is_terminal)
        self.assertEqual(o1.cancellation_reason, "User changed mind")

        # Can cancel from VALIDATED
        o2 = Order(ticker="YPFD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=20.0)
        o2.validate()
        o2.cancel(reason="Cancelled before send")
        self.assertEqual(o2.state, OrderState.CANCELLED)

        # Can cancel from SUBMITTED
        o3 = Order(ticker="YPFD", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=20.0)
        o3.validate().submit()
        o3.cancel(reason="Cancelled on exchange")
        self.assertEqual(o3.state, OrderState.CANCELLED)

    def test_rejection_from_states(self) -> None:
        # Reject from CREATED (e.g. insufficient cash)
        o1 = Order(
            ticker="PAMP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100.0,
            price=3000.0,
        )
        o1.reject(reason="Saldo insuficiente en cuenta")
        self.assertEqual(o1.state, OrderState.REJECTED)
        self.assertTrue(o1.is_terminal)
        self.assertEqual(o1.rejection_reason, "Saldo insuficiente en cuenta")

        # Reject from SUBMITTED (e.g. exchange rejection / market collar)
        o2 = Order(
            ticker="PAMP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100.0,
            price=3000.0,
        )
        o2.validate().submit()
        o2.reject(reason="BYMA collar limit breached")
        self.assertEqual(o2.state, OrderState.REJECTED)

    def test_illegal_state_transitions_raise_exception(self) -> None:
        # Cannot jump from CREATED directly to SUBMITTED
        o1 = Order(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
        with self.assertRaises(InvalidOrderStateTransitionError):
            o1.submit()

        # Cannot jump from CREATED directly to FILLED
        o2 = Order(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
        with self.assertRaises(InvalidOrderStateTransitionError):
            o2.fill()

        # Cannot transition out of terminal state FILLED
        o3 = Order(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
        o3.validate().submit().fill()
        with self.assertRaises(InvalidOrderStateTransitionError):
            o3.cancel()
        with self.assertRaises(InvalidOrderStateTransitionError):
            o3.submit()

        # Cannot transition out of terminal state CANCELLED
        o4 = Order(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
        o4.cancel()
        with self.assertRaises(InvalidOrderStateTransitionError):
            o4.validate()

        # Cannot transition out of terminal state REJECTED
        o5 = Order(ticker="AAPL", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=10.0)
        o5.reject("Rejected")
        with self.assertRaises(InvalidOrderStateTransitionError):
            o5.submit()


class TestMarketFrictions(unittest.TestCase):
    def test_alyc_commission_calculation(self) -> None:
        amount = 100_000.0
        # 0.5% rate = 500.0, VAT 21% = 105.0
        base_comm, vat = calculate_alyc_commission(amount, rate=0.005, include_vat=True)
        self.assertEqual(base_comm, 500.0)
        self.assertEqual(vat, 105.0)

        # Without VAT
        base_no_vat, vat_zero = calculate_alyc_commission(amount, rate=0.005, include_vat=False)
        self.assertEqual(base_no_vat, 500.0)
        self.assertEqual(vat_zero, 0.0)

        # Minimum commission applied
        base_min, _ = calculate_alyc_commission(1000.0, rate=0.005, min_fee=50.0)
        self.assertEqual(base_min, 50.0)

        # Edge validations
        with self.assertRaises(ValueError):
            calculate_alyc_commission(-100.0)
        with self.assertRaises(ValueError):
            calculate_alyc_commission(100.0, rate=1.5)

    def test_market_fees_calculation(self) -> None:
        amount = 100_000.0
        # 0.09% market fee = 90.0
        fee = calculate_market_fees(amount, fee_rate=0.0009)
        self.assertEqual(fee, 90.0)

        with self.assertRaises(ValueError):
            calculate_market_fees(-50.0)

    def test_slippage_calculation(self) -> None:
        price = 1000.0
        qty = 10.0
        slippage_rate = 0.002  # 0.2%

        # BUY: price shifts UP
        eff_px_buy, slip_amt_buy = calculate_slippage(
            price, qty, OrderSide.BUY, slippage_rate=slippage_rate
        )
        self.assertEqual(eff_px_buy, 1002.0)
        self.assertEqual(slip_amt_buy, 20.0)  # (1002 - 1000) * 10 = 20

        # SELL: price shifts DOWN
        eff_px_sell, slip_amt_sell = calculate_slippage(
            price, qty, OrderSide.SELL, slippage_rate=slippage_rate
        )
        self.assertEqual(eff_px_sell, 998.0)
        self.assertEqual(slip_amt_sell, 20.0)

        with self.assertRaises(ValueError):
            calculate_slippage(-10.0, 10.0, OrderSide.BUY)

    def test_net_execution_cost_buy(self) -> None:
        # BUY 100 shares @ $1,000 ARS
        # Nominal: $100,000 ARS
        # Slippage: 0.1% -> Eff Price = $1,001 ARS, Eff Amount = $100,100 ARS, Slippage Cost = $100 ARS
        # ALyC: 0.5% on $100,100 = $500.50 ARS, VAT (21%) = $105.105 ARS
        # Market fee: 0.09% on $100,100 = $90.09 ARS
        # Total frictions: $100 + $500.50 + $105.105 + $90.09 = $795.695 ARS
        # Net total outlay: $100,100 + $500.50 + $105.105 + $90.09 = $100,795.695 ARS
        breakdown = calculate_net_execution_cost(
            quantity=100.0,
            price=1000.0,
            side=OrderSide.BUY,
            alyc_rate=0.005,
            market_fee_rate=0.0009,
            slippage_rate=0.001,
            include_vat=True,
        )

        self.assertIsInstance(breakdown, ExecutionCostBreakdown)
        self.assertEqual(breakdown.side, OrderSide.BUY)
        self.assertEqual(breakdown.nominal_amount, 100_000.0)
        self.assertEqual(breakdown.effective_price, 1001.0)
        self.assertEqual(breakdown.effective_amount, 100_100.0)
        self.assertEqual(breakdown.slippage_amount, 100.0)
        self.assertEqual(breakdown.alyc_commission, 500.50)
        self.assertEqual(breakdown.alyc_vat, 105.105)
        self.assertEqual(breakdown.market_fees, 90.09)
        self.assertEqual(breakdown.total_frictions, 795.695)
        self.assertEqual(breakdown.net_total_amount, 100_795.695)
        # Buyer pays more per share than nominal
        self.assertGreater(breakdown.effective_net_price_per_share, 1000.0)
        self.assertAlmostEqual(breakdown.effective_net_price_per_share, 1007.957, places=3)
        self.assertAlmostEqual(breakdown.friction_pct, 0.7957, places=3)

    def test_net_execution_cost_sell(self) -> None:
        # SELL 100 shares @ $1,000 ARS
        # Nominal: $100,000 ARS
        # Slippage: 0.1% -> Eff Price = $999 ARS, Eff Amount = $99,900 ARS, Slippage Cost = $100 ARS
        # ALyC: 0.5% on $99,900 = $499.50 ARS, VAT (21%) = $104.895 ARS
        # Market fee: 0.09% on $99,900 = $89.91 ARS
        # Total frictions: $100 + $499.50 + $104.895 + $89.91 = $794.305 ARS
        # Net proceeds received: $99,900 - ($499.50 + $104.895 + $89.91) = $99,205.695 ARS
        breakdown = calculate_net_execution_cost(
            quantity=100.0,
            price=1000.0,
            side=OrderSide.SELL,
            alyc_rate=0.005,
            market_fee_rate=0.0009,
            slippage_rate=0.001,
            include_vat=True,
        )

        self.assertEqual(breakdown.side, OrderSide.SELL)
        self.assertEqual(breakdown.nominal_amount, 100_000.0)
        self.assertEqual(breakdown.effective_price, 999.0)
        self.assertEqual(breakdown.effective_amount, 99_900.0)
        self.assertEqual(breakdown.slippage_amount, 100.0)
        self.assertEqual(breakdown.alyc_commission, 499.50)
        self.assertEqual(breakdown.alyc_vat, 104.895)
        self.assertEqual(breakdown.market_fees, 89.91)
        self.assertEqual(breakdown.total_frictions, 794.305)
        self.assertEqual(breakdown.net_total_amount, 99_205.695)
        # Seller receives less per share than nominal
        self.assertLess(breakdown.effective_net_price_per_share, 1000.0)
        self.assertAlmostEqual(breakdown.effective_net_price_per_share, 992.057, places=3)
        self.assertAlmostEqual(breakdown.friction_pct, 0.7943, places=3)

    def test_net_execution_cost_sell_extreme_fees_does_not_drain_cash(self) -> None:
        """[DEFENSE: NUM-04] Verifica que si los costos fijos superan el valor de venta, el neto no sea negativo."""
        # Venta de penny stock: 1 share @ $1 ARS, pero comisión fija mínima de $50 ARS
        breakdown = calculate_net_execution_cost(
            quantity=1.0,
            price=1.0,
            side=OrderSide.SELL,
            min_alyc_fee=50.0,
            include_vat=True,
        )
        self.assertEqual(breakdown.side, OrderSide.SELL)
        self.assertGreaterEqual(breakdown.net_total_amount, 0.0)
        self.assertEqual(breakdown.net_total_amount, 0.0)


if __name__ == "__main__":
    unittest.main()
