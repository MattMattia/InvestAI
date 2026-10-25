"""
Unit test suite for Module 7.3 (Phases 1 & 2):
Dynamic Tolerance-Band Portfolio Rebalancing Engine, ATR Volatility Calibration,
Post-Trade Drift & Realized PnL Accounting, Excess Cash Deployment, and
Idempotent Order FSM Execution Batching
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
from app.domain.services.technical_indicators import TechnicalIndicatorsSnapshot
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
    RebalanceFSMExecutionBatch,
    RebalanceFSMOrderTicket,
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
            "RebalanceFSMOrderTicket",
            "RebalanceFSMExecutionBatch",
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

    def test_calibrate_specs_from_indicators_scales_bands_by_atr_volatility(
        self,
    ) -> None:
        """
        Verify `calibrate_specs_from_indicators` bridges `TechnicalIndicatorsSnapshot`
        (`atr_14 / close` vs `baseline_atr_pct`), clamping multipliers to
        `[min_multiplier, max_multiplier]`, matching `.BA` suffixes, and populating
        fallback `reference_price` from `snapshot.close`.
        """
        specs = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.4000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.3500")),
            AssetTargetBandSpec(ticker="KO", target_weight=Decimal("0.2500")),
        ]
        indicators = {
            # GGAL.BA: atr_14 = 8.00, close = 100.00 -> atr_pct = 8% -> 0.08 / 0.02 = 4.0 -> clamped to 3.0000
            "GGAL.BA": TechnicalIndicatorsSnapshot(
                ticker="GGAL.BA",
                as_of=self.as_of,
                close=Decimal("100.0000"),
                atr_14=Decimal("8.0000"),
            ),
            # YPFD: atr_14 = 3.00, close = 100.00 -> atr_pct = 3% -> 0.03 / 0.02 = 1.5000
            "YPFD": TechnicalIndicatorsSnapshot(
                ticker="YPFD",
                as_of=self.as_of,
                close=Decimal("100.0000"),
                atr_14=Decimal("3.0000"),
            ),
            # KO: atr_14 = 0.25, close = 50.00 -> atr_pct = 0.5% -> 0.005 / 0.02 = 0.25 -> clamped to 0.5000
            "KO": TechnicalIndicatorsSnapshot(
                ticker="KO",
                as_of=self.as_of,
                close=Decimal("50.0000"),
                atr_14=Decimal("0.2500"),
            ),
        }

        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.DYNAMIC_VOLATILITY,
                default_relative_tolerance=Decimal("0.1000"),
                min_band_half_width=Decimal("0.0050"),
                max_band_half_width=Decimal("0.2500"),
            )
        )
        calibrated = svc.calibrate_specs_from_indicators(
            target_specs=specs,
            indicators_by_ticker=indicators,
            baseline_atr_pct=Decimal("0.0200"),
            min_multiplier=Decimal("0.5000"),
            max_multiplier=Decimal("3.0000"),
        )

        cal_map = {s.ticker: s for s in calibrated}
        self.assertEqual(cal_map["GGAL"].volatility_multiplier, Decimal("3.0000"))
        self.assertEqual(cal_map["GGAL"].reference_price, Decimal("100.0000"))
        self.assertEqual(cal_map["YPFD"].volatility_multiplier, Decimal("1.5000"))
        self.assertEqual(cal_map["YPFD"].reference_price, Decimal("100.0000"))
        self.assertEqual(cal_map["KO"].volatility_multiplier, Decimal("0.5000"))
        self.assertEqual(cal_map["KO"].reference_price, Decimal("50.0000"))

        # Evaluate using calibrated specs without passing external market_prices (uses calibrated reference_price)
        report = svc.evaluate_and_rebalance(
            positions=[],
            target_specs=calibrated,
            initial_cash=Decimal("10000"),
            as_of=self.as_of,
        )
        eval_map = {e.ticker: e for e in report.evaluations}
        # GGAL: target 0.4000, half = 0.40 * 0.10 * 3.0 = 0.1200 -> [0.2800, 0.5200]
        self.assertEqual(eval_map["GGAL"].lower_band, Decimal("0.2800"))
        self.assertEqual(eval_map["GGAL"].upper_band, Decimal("0.5200"))
        # KO: target 0.2500, half = 0.25 * 0.10 * 0.5 = 0.0125 -> [0.2375, 0.2625]
        self.assertEqual(eval_map["KO"].lower_band, Decimal("0.2375"))
        self.assertEqual(eval_map["KO"].upper_band, Decimal("0.2625"))

    def test_post_trade_weights_and_residual_drift_accounting_with_commissions(
        self,
    ) -> None:
        """
        Verify projected post-trade state (`post_trade_quantity`, `post_trade_value`,
        `post_trade_weight`, `post_trade_drift_weight`) and exact net worth conservation:
        `projected_post_trade_portfolio_value == total_portfolio_value - total_estimated_commissions`
        `== sum(e.post_trade_value for e in evaluations) + projected_ending_cash`.
        """
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0500"),
                rebalance_mode=RebalanceMode.FULL_TO_TARGET,
                commission_bps=Decimal("50.0000"),  # 0.50%
            )
        )
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("70"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="YPFD", quantity=Decimal("30"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]

        report = svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("0"),
            as_of=self.as_of,
        )

        # Total pre-trade = $10,000; GGAL sells 20 shares ($2,000 gross, $10 comm -> $1,990 net cash)
        # YPFD buys $1,990 / (1.005 * 100) = 19.8009 shares ($1,980.0900 gross, $9.9005 comm)
        sum_post_trade_values = sum(
            (e.post_trade_value for e in report.evaluations), Decimal("0.0000")
        )
        self.assertEqual(
            report.projected_post_trade_portfolio_value,
            report.total_portfolio_value - report.total_estimated_commissions,
        )
        self.assertEqual(
            sum_post_trade_values + report.projected_ending_cash,
            report.projected_post_trade_portfolio_value,
        )

        eval_map = {e.ticker: e for e in report.evaluations}
        self.assertEqual(eval_map["GGAL"].post_trade_quantity, Decimal("50.0000"))
        self.assertEqual(eval_map["GGAL"].post_trade_value, Decimal("5000.0000"))
        self.assertLess(
            abs(eval_map["GGAL"].post_trade_drift_weight),
            abs(eval_map["GGAL"].drift_weight),
        )
        self.assertLess(
            abs(eval_map["YPFD"].post_trade_drift_weight),
            abs(eval_map["YPFD"].drift_weight),
        )

    def test_realized_pnl_estimation_on_partial_and_full_sells_from_mtm_report(
        self,
    ) -> None:
        """
        Verify `estimated_realized_pnl` on SELL and BUY orders and `total_estimated_realized_pnl`
        when rebalancing both from direct `RebalancePositionInput` lots (with weighted-average
        cost consolidation) and from `PortfolioMarkToMarketReport` in USD and ARS.
        """
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0500"),
                commission_bps=Decimal("100.0000"),  # 1.00% commission
            )
        )
        # Two GGAL lots: 30 @ cost $60 + 40 @ cost $95 -> 70 shares, weighted avg cost = $80.0000, market = $100
        # YPFD: 30 shares @ cost $120, market = $100
        positions = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("60"),
            ),
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("40"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("95"),
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("120"),
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

        # GGAL sells 20 shares @ $100 (avg cost $80) -> gross gain = 20 * 20 = $400; comm = 1% of $2,000 = $20 -> net realized PnL = $380.0000
        orders_by_side = {o.side: o for o in report.orders}
        self.assertEqual(
            orders_by_side["SELL"].estimated_realized_pnl, Decimal("380.0000")
        )
        self.assertEqual(
            orders_by_side["BUY"].estimated_realized_pnl, Decimal("0.0000")
        )
        self.assertEqual(report.total_estimated_realized_pnl, Decimal("380.0000"))

        # Verify propagation from PortfolioMarkToMarketReport in ARS
        val_svc = PortfolioValuationService()
        mtm_report = val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("70"),
                    avg_cost_price=Decimal("80000"),
                    market_price=Decimal("100000"),
                    currency="ARS",
                    entry_fx_rate=Decimal("1000"),
                ),
                PositionValuationInput(
                    ticker="YPFD",
                    quantity=Decimal("30"),
                    avg_cost_price=Decimal("110000"),
                    market_price=Decimal("100000"),
                    currency="ARS",
                    entry_fx_rate=Decimal("1000"),
                ),
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        ars_report = svc.rebalance_from_mtm_report(
            mtm_report=mtm_report,
            target_specs=targets,
            base_currency="ARS",
        )
        # In ARS: sells 20 GGAL @ 100,000 (cost 80,000) -> gain 400,000 - 20,000 comm = 380,000.0000 ARS
        self.assertEqual(
            ars_report.total_estimated_realized_pnl, Decimal("380000.0000")
        )

    def test_deploy_excess_cash_when_inside_bands_allocates_inflow_without_sells(
        self,
    ) -> None:
        """
        Verify `deploy_excess_cash_when_inside_bands=True`:
        When all positions sit inside their tolerance bands (`breached_tickers == []`)
        but `initial_cash / total_portfolio_value > cash_buffer_weight + min_band_half_width`,
        the engine triggers BUY-only orders to allocate the excess cash into underweighted
        target assets without selling any position.
        """
        # Portfolio = $10,000 total: GGAL = $4,500 (45%), YPFD = $4,500 (45%), Cash = $1,000 (10%)
        # Target = 48% GGAL, 48% YPFD, 4% cash buffer; relative tolerance 20% -> bands [0.3840, 0.5760]
        # Both GGAL (0.4500) and YPFD (0.4500) are strictly INSIDE their bands!
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("45"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="YPFD", quantity=Decimal("45"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.4800")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.4800")),
        ]

        # 1. With deploy_excess_cash_when_inside_bands=False (default): no rebalance
        default_Cash_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                cash_buffer_weight=Decimal("0.0400"),
                deploy_excess_cash_when_inside_bands=False,
            )
        )
        rep_idle = default_Cash_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("1000"),
            as_of=self.as_of,
        )
        self.assertFalse(rep_idle.needs_rebalancing)
        self.assertEqual(rep_idle.orders, [])

        # 2. With deploy_excess_cash_when_inside_bands=True: allocates $600 excess cash ($300 GGAL, $300 YPFD)
        deploy_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                cash_buffer_weight=Decimal("0.0400"),
                deploy_excess_cash_when_inside_bands=True,
                commission_bps=Decimal("0"),
            )
        )
        rep_deploy = deploy_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("1000"),
            as_of=self.as_of,
        )
        self.assertTrue(rep_deploy.needs_rebalancing)
        self.assertEqual(rep_deploy.breached_tickers, [])
        self.assertEqual(len(rep_deploy.orders), 2)
        self.assertTrue(all(o.side == "BUY" for o in rep_deploy.orders))
        self.assertEqual(rep_deploy.total_sell_gross, Decimal("0.0000"))
        self.assertEqual(rep_deploy.total_buy_gross, Decimal("600.0000"))
        self.assertEqual(rep_deploy.projected_ending_cash, Decimal("400.0000"))

    def test_build_fsm_execution_batch_deterministic_idempotency_and_phase_ordering(
        self,
    ) -> None:
        """
        Verify `build_fsm_execution_batch` produces deterministic `batch_id` and
        per-ticket `idempotency_key` hashes across repeated invocations, contiguous
        `sequence_number` ordering, two-phase separation (`LIQUIDATION_SELL` before
        `ACQUISITION_BUY`), and validated `PENDING` order payloads.
        """
        positions = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("70"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("80"),
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("90"),
            ),
            RebalancePositionInput(
                ticker="AAPL",
                quantity=Decimal("10"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("95"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.4000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.3500")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.2500")),
        ]

        report = self.default_service.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            portfolio_id="pf-fsm-batch-01",
            as_of=self.as_of,
        )

        batch_1 = self.default_service.build_fsm_execution_batch(report)
        batch_2 = self.default_service.build_fsm_execution_batch(report)

        self.assertIsInstance(batch_1, RebalanceFSMExecutionBatch)
        self.assertEqual(batch_1.batch_id, batch_2.batch_id)
        self.assertTrue(batch_1.batch_id.startswith("reb-batch-"))
        self.assertEqual(batch_1.portfolio_id, "pf-fsm-batch-01")
        self.assertEqual(batch_1.total_orders, 3)
        self.assertEqual(batch_1.sell_orders_count, 1)
        self.assertEqual(batch_1.buy_orders_count, 2)
        self.assertEqual(
            [t.sequence_number for t in batch_1.tickets],
            [1, 2, 3],
        )
        self.assertEqual(
            [t.execution_phase for t in batch_1.tickets],
            ["LIQUIDATION_SELL", "ACQUISITION_BUY", "ACQUISITION_BUY"],
        )
        self.assertEqual(
            [t.idempotency_key for t in batch_1.tickets],
            [t.idempotency_key for t in batch_2.tickets],
        )
        for ticket in batch_1.tickets:
            self.assertTrue(ticket.idempotency_key.startswith("reb-ord-"))
            self.assertEqual(ticket.order_payload["status"], "PENDING")
            self.assertEqual(ticket.order_payload["portfolio_id"], "pf-fsm-batch-01")
            self.assertEqual(ticket.order_payload["ticker"], ticket.ticker)
            self.assertEqual(ticket.order_payload["side"], ticket.side)
            self.assertEqual(ticket.order_payload["quantity"], ticket.quantity)

    def test_phase2_validation_guards_invalid_calibration_bounds_and_batch_invariants(
        self,
    ) -> None:
        """
        Verify Phase 2 validation guards across `calibrate_specs_from_indicators`,
        `RebalanceFSMOrderTicket`, `RebalanceFSMExecutionBatch`, and `build_fsm_execution_batch`.
        """
        specs = [AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("1.0000"))]
        snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=self.as_of,
            close=Decimal("100"),
            atr_14=Decimal("2.0"),
        )

        # 1. Invalid calibration bounds and types
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.calibrate_specs_from_indicators(
                target_specs=specs,
                indicators_by_ticker={"GGAL": snap},
                baseline_atr_pct=Decimal("0"),
            )
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.calibrate_specs_from_indicators(
                target_specs=specs,
                indicators_by_ticker={"GGAL": snap},
                min_multiplier=Decimal("2.5000"),
                max_multiplier=Decimal("1.5000"),
            )
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.calibrate_specs_from_indicators(
                target_specs=specs,
                indicators_by_ticker={"GGAL": "not-a-snapshot"},  # type: ignore[dict-item]
            )

        # 2. Invalid RebalanceFSMOrderTicket phase / side mismatch
        with self.assertRaises(ValidationError):
            RebalanceFSMOrderTicket(
                sequence_number=1,
                execution_phase="ACQUISITION_BUY",
                idempotency_key="reb-ord-0123456789abcdef01234567",
                ticker="GGAL",
                side="SELL",
                quantity=Decimal("10.0000"),
                execution_price=Decimal("100.0000"),
                estimated_commission=Decimal("0.0000"),
                order_payload={"ticker": "GGAL", "side": "SELL"},
            )

        # 3. Invalid RebalanceFSMExecutionBatch phase ordering (SELL after BUY)
        buy_ticket = RebalanceFSMOrderTicket(
            sequence_number=1,
            execution_phase="ACQUISITION_BUY",
            idempotency_key="reb-ord-111111111111111111111111",
            ticker="YPFD",
            side="BUY",
            quantity=Decimal("10.0000"),
            execution_price=Decimal("100.0000"),
            estimated_commission=Decimal("0.0000"),
            order_payload={"ticker": "YPFD", "side": "BUY"},
        )
        sell_ticket = RebalanceFSMOrderTicket(
            sequence_number=2,
            execution_phase="LIQUIDATION_SELL",
            idempotency_key="reb-ord-222222222222222222222222",
            ticker="GGAL",
            side="SELL",
            quantity=Decimal("10.0000"),
            execution_price=Decimal("100.0000"),
            estimated_commission=Decimal("0.0000"),
            order_payload={"ticker": "GGAL", "side": "SELL"},
        )
        with self.assertRaises(ValidationError):
            RebalanceFSMExecutionBatch(
                batch_id="reb-batch-0123456789abcdef01234567",
                as_of=self.as_of,
                base_currency="USD",
                total_orders=2,
                sell_orders_count=1,
                buy_orders_count=1,
                tickets=[buy_ticket, sell_ticket],
            )

        # 4. Invalid report or control character in build_fsm_execution_batch
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.build_fsm_execution_batch(report="invalid")  # type: ignore[arg-type]

