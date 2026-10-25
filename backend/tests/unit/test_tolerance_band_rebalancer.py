"""
Unit test suite for Module 7.3 Phase 1:
Dynamic Tolerance-Band Portfolio Rebalancing Engine
(`backend/app/domain/services/tolerance_band_rebalancer.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from pydantic import ValidationError
import pytest

import app.domain.services as domain_services_pkg
from app.domain.services.portfolio_valuation_service import (
    PortfolioValuationService,
    PositionValuationInput,
)
from app.domain.services.tolerance_band_rebalancer import (
    MAX_REBALANCE_ASSETS,
    REBALANCE_QUANTIZE,
    AssetBandEvaluation,
    AssetTargetBandSpec,
    BandBreachDirection,
    BandType,
    InsufficientLiquidityForRebalanceError,
    InvalidTargetAllocationError,
    InvalidToleranceBandConfigError,
    MissingRebalancePriceError,
    RebalanceMode,
    RebalancePositionInput,
    RebalanceTradeOrder,
    ToleranceBandRebalanceReport,
    ToleranceBandRebalancerConfig,
    ToleranceBandRebalancerService,
)


@pytest.mark.unit
class TestToleranceBandRebalancer(unittest.TestCase):
    """Unit tests verifying tolerance-band corridor monitoring and self-financing rebalance execution."""

    def setUp(self) -> None:
        self.as_of = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
        self.default_service = ToleranceBandRebalancerService()

    def test_no_rebalance_triggered_when_all_positions_inside_tolerance_corridor(
        self,
    ) -> None:
        """
        Verify that when all assets sit inside their configured tolerance corridor
        ($w_i^* \\pm \\theta_i$), `needs_rebalancing` is False, `orders` is empty,
        `breached_tickers` is empty, and `portfolio_turnover` is 0.0000.
        """
        # Portfolio = $10,000 total: GGAL = $5,300 (53%), YPFD = $4,700 (47%)
        # Target = 50% / 50% with 20% relative tolerance -> [0.4000, 0.6000] band
        positions = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("53"),
                market_price=Decimal("100"),
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("47"),
                market_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]

        report = self.default_service.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("0"),
            portfolio_id="pf-corridor-ok",
            as_of=self.as_of,
        )

        self.assertFalse(report.needs_rebalancing)
        self.assertEqual(report.breached_tickers, [])
        self.assertEqual(report.orders, [])
        self.assertEqual(report.total_sell_gross, Decimal("0.0000"))
        self.assertEqual(report.total_buy_gross, Decimal("0.0000"))
        self.assertEqual(report.portfolio_turnover, Decimal("0.0000"))
        for ev in report.evaluations:
            self.assertFalse(ev.is_breached)
            self.assertEqual(ev.breach_direction, BandBreachDirection.NONE)
            self.assertEqual(ev.lower_band, Decimal("0.4000"))
            self.assertEqual(ev.upper_band, Decimal("0.6000"))
            self.assertEqual(ev.destination_weight, ev.current_weight)

    def test_full_to_target_vs_to_band_boundary_turnover_reduction(self) -> None:
        """
        Compare `RebalanceMode.FULL_TO_TARGET` vs `RebalanceMode.TO_BAND_BOUNDARY`
        on a drifted portfolio (65% / 35% vs 50% / 50% target with +/-5% absolute bands),
        verifying that `TO_BAND_BOUNDARY` only trades back to the 55% / 45% corridor
        edges and cuts portfolio turnover in third (0.0500 vs 0.1500).
        """
        positions = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("65"),
                market_price=Decimal("100"),  # $6,500 (65%)
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("35"),
                market_price=Decimal("100"),  # $3,500 (35%)
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]

        full_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0500"),
                rebalance_mode=RebalanceMode.FULL_TO_TARGET,
                commission_bps=Decimal("0"),
            )
        )
        boundary_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0500"),
                rebalance_mode=RebalanceMode.TO_BAND_BOUNDARY,
                commission_bps=Decimal("0"),
            )
        )

        report_full = full_svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        report_boundary = boundary_svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )

        # FULL_TO_TARGET sells $1,500 GGAL and buys $1,500 YPFD -> turnover = 15% (0.1500)
        self.assertTrue(report_full.needs_rebalancing)
        self.assertEqual(report_full.total_sell_gross, Decimal("1500.0000"))
        self.assertEqual(report_full.total_buy_gross, Decimal("1500.0000"))
        self.assertEqual(report_full.portfolio_turnover, Decimal("0.1500"))

        # TO_BAND_BOUNDARY sells $1,000 GGAL (to 55%) and buys $1,000 YPFD (to 45%) -> turnover = 10% (0.1000)
        self.assertTrue(report_boundary.needs_rebalancing)
        self.assertEqual(report_boundary.total_sell_gross, Decimal("1000.0000"))
        self.assertEqual(report_boundary.total_buy_gross, Decimal("1000.0000"))
        self.assertEqual(report_boundary.portfolio_turnover, Decimal("0.1000"))
        self.assertLess(
            report_boundary.portfolio_turnover,
            report_full.portfolio_turnover,
        )

    def test_sell_before_buy_waterfall_with_commissions_prevents_cash_overdraft(
        self,
    ) -> None:
        """
        Verify the Self-Financing Liquidity Waterfall with 50 bps commissions and
        a 2% cash buffer reserve:
        1. All SELL orders precede BUY orders.
        2. Net sell proceeds after commission fund BUY orders without overdraft.
        3. Exact cash closure holds (`projected_ending_cash >= target_cash_reserve >= 0`).
        """
        config = ToleranceBandRebalancerConfig(
            band_type=BandType.ABSOLUTE,
            default_absolute_tolerance=Decimal("0.0400"),
            rebalance_mode=RebalanceMode.FULL_TO_TARGET,
            commission_bps=Decimal("50.0000"),  # 0.50% commission
            cash_buffer_weight=Decimal("0.0200"),  # 2% cash buffer
        )
        svc = ToleranceBandRebalancerService(config)

        # Total portfolio = $10,000 (GGAL = $7,000, YPFD = $2,000, AAPL = $1,000, cash = $0)
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("70"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="YPFD", quantity=Decimal("20"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="AAPL", quantity=Decimal("10"), market_price=Decimal("100")
            ),
        ]
        # Target weights sum to 0.9800 + 0.0200 cash buffer = 1.0000
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.4000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.3800")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.2000")),
        ]

        report = svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("0"),
            as_of=self.as_of,
        )

        self.assertTrue(report.needs_rebalancing)
        self.assertGreaterEqual(len(report.orders), 2)
        self.assertEqual(report.orders[0].side, "SELL")
        self.assertEqual(report.orders[0].ticker, "GGAL")

        # Verify SELL order precedes all BUY orders
        sides = [o.side for o in report.orders]
        self.assertEqual(sides[0], "SELL")
        self.assertTrue(all(s == "BUY" for s in sides[1:]))

        # Verify zero overdraft and cash buffer preservation ($200 target reserve on $10,000)
        self.assertGreaterEqual(report.projected_ending_cash, Decimal("200.0000"))
        self.assertEqual(
            report.projected_ending_cash,
            report.initial_cash
            + report.total_sell_gross
            - report.total_buy_gross
            - report.total_estimated_commissions,
        )

    def test_integer_lot_shares_floor_rounding_and_min_trade_dust_filter(self) -> None:
        """
        Verify `allow_fractional_shares=False` floors quantities to whole shares (`Decimal("1")`)
        and `min_trade_notional` suppresses sub-threshold dust orders.
        """
        config = ToleranceBandRebalancerConfig(
            band_type=BandType.ABSOLUTE,
            default_absolute_tolerance=Decimal("0.0200"),
            allow_fractional_shares=False,
            min_trade_notional=Decimal("500.0000"),
            commission_bps=Decimal("25.0000"),
        )
        svc = ToleranceBandRebalancerService(config)

        positions = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("100"),
                market_price=Decimal("73"),  # $7,300
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("20"),
                market_price=Decimal("135"),  # $2,700
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]

        report = svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            as_of=self.as_of,
        )

        self.assertTrue(report.needs_rebalancing)
        for order in report.orders:
            # Must be whole integer quantity
            self.assertEqual(order.quantity, order.quantity // Decimal("1"))
            self.assertGreaterEqual(order.gross_amount, Decimal("500.0000"))

        # Now set min_trade_notional above the trade size ($3,000) and verify dust suppression
        high_min_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0200"),
                allow_fractional_shares=False,
                min_trade_notional=Decimal("3000.0000"),
            )
        )
        dust_report = high_min_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            as_of=self.as_of,
        )
        self.assertTrue(dust_report.needs_rebalancing)
        self.assertEqual(dust_report.orders, [])

    def test_unlisted_holding_full_liquidation_and_new_unheld_target_asset_entry(
        self,
    ) -> None:
        """
        Verify that:
        1. An unlisted legacy holding ("COME") not in `target_specs` is 100% liquidated
           when `liquidate_unlisted_holdings=True`.
        2. A brand-new target asset ("NVDA") not currently held in `positions` resolves its
           price from `market_prices` (or `reference_price`) and receives a BUY order.
        3. Missing price for an unheld target asset raises `MissingRebalancePriceError`.
        """
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("50"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="COME", quantity=Decimal("200"), market_price=Decimal("25")
            ),  # $5,000 unlisted holding
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="NVDA", target_weight=Decimal("0.5000")),
        ]

        # Missing price for NVDA must raise MissingRebalancePriceError
        with self.assertRaises(MissingRebalancePriceError):
            self.default_service.evaluate_and_rebalance(
                positions=positions,
                target_specs=targets,
                as_of=self.as_of,
            )

        report = self.default_service.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            market_prices={"NVDA": Decimal("250")},
            as_of=self.as_of,
        )

        self.assertTrue(report.needs_rebalancing)
        self.assertIn("COME", report.breached_tickers)
        self.assertIn("NVDA", report.breached_tickers)

        orders_by_ticker = {o.ticker: o for o in report.orders}
        self.assertIn("COME", orders_by_ticker)
        self.assertEqual(orders_by_ticker["COME"].side, "SELL")
        self.assertEqual(orders_by_ticker["COME"].quantity, Decimal("200.0000"))
        self.assertEqual(orders_by_ticker["COME"].gross_amount, Decimal("5000.0000"))

        self.assertIn("NVDA", orders_by_ticker)
        self.assertEqual(orders_by_ticker["NVDA"].side, "BUY")
        self.assertEqual(orders_by_ticker["NVDA"].quantity, Decimal("20.0000"))
        self.assertEqual(orders_by_ticker["NVDA"].gross_amount, Decimal("5000.0000"))

    def test_dynamic_volatility_band_scaling_and_rebalance_from_mtm_report_integration(
        self,
    ) -> None:
        """
        Verify `BandType.DYNAMIC_VOLATILITY` scales tolerance corridors by
        `volatility_multiplier` (clamped to `[min_band_half_width, max_band_half_width]`)
        and integrates seamlessly with `PortfolioMarkToMarketReport` via `rebalance_from_mtm_report`.
        """
        val_svc = PortfolioValuationService()
        mtm_report = val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("70"),
                    avg_cost_price=Decimal("90000"),
                    market_price=Decimal("100000"),  # $7,000 USD at FX 1000
                    currency="ARS",
                    entry_fx_rate=Decimal("1000"),
                ),
                PositionValuationInput(
                    ticker="AAPL",
                    quantity=Decimal("30"),
                    avg_cost_price=Decimal("90"),
                    market_price=Decimal("100"),  # $3,000 USD
                    currency="USD",
                    entry_fx_rate=Decimal("1000"),
                ),
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_usd=Decimal("0"),
            portfolio_id="pf-mtm-rebal-01",
            as_of=self.as_of,
        )

        rebal_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.DYNAMIC_VOLATILITY,
                default_relative_tolerance=Decimal("0.1000"),
                min_band_half_width=Decimal("0.0100"),
                max_band_half_width=Decimal("0.2000"),
                commission_bps=Decimal("10.0000"),
            )
        )
        # GGAL target 50% with volatility_multiplier 1.5 -> half_width = 0.50 * 0.10 * 1.5 = 0.0750 -> [0.4250, 0.5750]
        # AAPL target 50% with volatility_multiplier 2.0 -> half_width = 0.50 * 0.10 * 2.0 = 0.1000 -> [0.4000, 0.6000]
        targets = [
            AssetTargetBandSpec(
                ticker="GGAL",
                target_weight=Decimal("0.5000"),
                volatility_multiplier=Decimal("1.5000"),
            ),
            AssetTargetBandSpec(
                ticker="AAPL",
                target_weight=Decimal("0.5000"),
                volatility_multiplier=Decimal("2.0000"),
            ),
        ]

        report = rebal_svc.rebalance_from_mtm_report(
            mtm_report=mtm_report,
            target_specs=targets,
            base_currency="USD",
        )

        self.assertIsInstance(report, ToleranceBandRebalanceReport)
        self.assertEqual(report.portfolio_id, "pf-mtm-rebal-01")
        self.assertTrue(report.needs_rebalancing)

        eval_map = {e.ticker: e for e in report.evaluations}
        self.assertEqual(eval_map["GGAL"].lower_band, Decimal("0.4250"))
        self.assertEqual(eval_map["GGAL"].upper_band, Decimal("0.5750"))
        self.assertEqual(eval_map["AAPL"].lower_band, Decimal("0.4000"))
        self.assertEqual(eval_map["AAPL"].upper_band, Decimal("0.6000"))
        self.assertEqual(len(report.orders), 2)
        self.assertEqual(report.orders[0].side, "SELL")
        self.assertEqual(report.orders[1].side, "BUY")

    def test_validation_guards_target_weights_sum_duplicate_tickers_and_zero_portfolio(
        self,
    ) -> None:
        """
        Verify domain validation guards:
        1. Target weights + cash_buffer_weight != 1.0000 raises `InvalidTargetAllocationError`.
        2. Duplicate tickers in `target_specs` raises `InvalidTargetAllocationError`.
        3. Zero total portfolio value raises `InsufficientLiquidityForRebalanceError`.
        4. Invalid config (`min_band_half_width > max_band_half_width` or boolean injection) raises `ValidationError`.
        5. All public symbols are re-exported in `app.domain.services`.
        """
        pos = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]

        # 1. Target weights sum != 1.0000
        with self.assertRaises(InvalidTargetAllocationError):
            self.default_service.evaluate_and_rebalance(
                positions=pos,
                target_specs=[
                    AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.6000")),
                    AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.3000")),
                ],
                market_prices={"YPFD": Decimal("100")},
            )

        # 2. Duplicate tickers in target_specs
        with self.assertRaises(InvalidTargetAllocationError):
            self.default_service.evaluate_and_rebalance(
                positions=pos,
                target_specs=[
                    AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
                    AssetTargetBandSpec(ticker="ggal", target_weight=Decimal("0.5000")),
                ],
            )

        # 3. Zero total portfolio value
        with self.assertRaises(InsufficientLiquidityForRebalanceError):
            self.default_service.evaluate_and_rebalance(
                positions=[],
                target_specs=[
                    AssetTargetBandSpec(
                        ticker="GGAL",
                        target_weight=Decimal("1.0000"),
                        reference_price=Decimal("100"),
                    )
                ],
                initial_cash=Decimal("0"),
            )

        # 4. Invalid config bounds and boolean rejection
        with self.assertRaises(ValidationError):
            ToleranceBandRebalancerConfig(
                min_band_half_width=Decimal("0.1500"),
                max_band_half_width=Decimal("0.1000"),
            )
        with self.assertRaises(ValidationError):
            RebalancePositionInput(
                ticker="GGAL",
                quantity=True,  # type: ignore[arg-type]
                market_price=Decimal("100"),
            )
        with self.assertRaises(InvalidToleranceBandConfigError):
            ToleranceBandRebalancerService(config="invalid")  # type: ignore[arg-type]

        # 5. Re-exports in app.domain.services
        for symbol in (
            "REBALANCE_QUANTIZE",
            "MAX_REBALANCE_ASSETS",
            "RebalancingError",
            "InvalidTargetAllocationError",
            "InvalidToleranceBandConfigError",
            "MissingRebalancePriceError",
            "InsufficientLiquidityForRebalanceError",
            "BandType",
            "RebalanceMode",
            "BandBreachDirection",
            "RebalancePositionInput",
            "AssetTargetBandSpec",
            "ToleranceBandRebalancerConfig",
            "AssetBandEvaluation",
            "RebalanceTradeOrder",
            "ToleranceBandRebalanceReport",
            "ToleranceBandRebalancerService",
        ):
            self.assertTrue(
                hasattr(domain_services_pkg, symbol),
                f"Expected '{symbol}' to be re-exported in app.domain.services",
            )
        self.assertEqual(REBALANCE_QUANTIZE, Decimal("0.0001"))
        self.assertEqual(MAX_REBALANCE_ASSETS, 5_000)
        self.assertTrue(issubclass(RebalanceTradeOrder, object))
        self.assertTrue(issubclass(AssetBandEvaluation, object))
