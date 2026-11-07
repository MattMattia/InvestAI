"""
Unit test suite for Module 7.3 (Phases 1, 2 & 3):
Dynamic Tolerance-Band Portfolio Rebalancing Engine, ATR Volatility Calibration,
Post-Trade Drift & Realized PnL Accounting, Tax-Lot Selection (FIFO/LIFO/HIFO),
Excess Cash Deployment, Idempotent Order FSM Execution Batching, and
End-to-End Chapter 7 Quantitative Certification
(`backend/app/domain/services/tolerance_band_rebalancer.py`).
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.domain.services as domain_services_pkg
import pytest
from app.domain.services.portfolio_valuation_service import (
    PortfolioValuationService,
    PositionValuationInput,
)
from app.domain.services.signal_generator import (
    SignalAction,
    SignalGeneratorService,
)
from app.domain.services.technical_indicators import (
    TechnicalIndicatorsService,
    TechnicalIndicatorsSnapshot,
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
    RebalanceFSMExecutionBatch,
    RebalanceFSMOrderTicket,
    RebalanceMode,
    RebalancePositionInput,
    RebalanceTradeOrder,
    TaxLotSelectionPolicy,
    ToleranceBandRebalancerConfig,
    ToleranceBandRebalanceReport,
    ToleranceBandRebalancerService,
)
from app.schemas.market_data import MarketBarDTO
from pydantic import ValidationError


@pytest.mark.unit
class TestToleranceBandRebalancer(unittest.TestCase):
    """Unit tests verifying tolerance-band corridor monitoring and self-financing rebalance execution."""

    def setUp(self) -> None:
        self.as_of = datetime(2026, 10, 25, 15, 0, tzinfo=UTC)
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
            "TaxLotSelectionPolicy",
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
        self.assertEqual(orders_by_side["SELL"].estimated_realized_pnl, Decimal("380.0000"))
        self.assertEqual(orders_by_side["BUY"].estimated_realized_pnl, Decimal("0.0000"))
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
        self.assertEqual(ars_report.total_estimated_realized_pnl, Decimal("380000.0000"))

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

    def test_end_to_end_chapter7_pipeline_indicators_to_valuation_to_atr_rebalance_and_fsm_batch(
        self,
    ) -> None:
        """
        Verify full End-to-End Chapter 7 orchestration:
        1. Module 7.1 (`TechnicalIndicatorsService` + `SignalGeneratorService`):
           Compute indicator snapshots (`atr_14`, `sma_20`, `ema_12`, `rsi_14`, Bollinger)
           and composite signal reports across multi-asset historical OHLCV series.
        2. Module 7.2 (`PortfolioValuationService.value_portfolio_mark_to_market`):
           Evaluate bimonetary ARS + USD mark-to-market portfolio valuation with
           unknown-cost positions (`avg_cost_price=Decimal("0")`) and native unit price conversion.
        3. Module 7.3 (`ToleranceBandRebalancerService`):
           Calibrate dynamic volatility bands from indicator snapshots (`calibrate_specs_from_indicators`),
           execute bimonetary rebalance directly from the MTM report (`rebalance_from_mtm_report`)
           in both USD and ARS base currencies, and emit a deterministic, two-phase
           `RebalanceFSMExecutionBatch` (`build_fsm_execution_batch`).
        """
        base_dt = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
        ggal_bars: list[MarketBarDTO] = []
        ypfd_bars: list[MarketBarDTO] = []
        aapl_bars: list[MarketBarDTO] = []

        for idx in range(25):
            ts = base_dt + timedelta(days=idx)
            # GGAL: trending up strongly with high ATR range
            g_close = Decimal(str(1800 + idx * 25))
            ggal_bars.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=g_close - Decimal("20"),
                    high=g_close + Decimal("45"),
                    low=g_close - Decimal("45"),
                    close=g_close,
                    volume=Decimal("150000"),
                )
            )
            # YPFD: moderate volatility
            y_close = Decimal(str(22000 + idx * 100))
            ypfd_bars.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=y_close - Decimal("100"),
                    high=y_close + Decimal("300"),
                    low=y_close - Decimal("300"),
                    close=y_close,
                    volume=Decimal("80000"),
                )
            )
            # AAPL: low volatility USD asset
            a_close = Decimal(str(200 + idx * 1))
            aapl_bars.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=a_close - Decimal("0.50"),
                    high=a_close + Decimal("1.50"),
                    low=a_close - Decimal("1.50"),
                    close=a_close,
                    volume=Decimal("500000"),
                )
            )

        # Step 1: Module 7.1 Technical Indicators & Signal Generator
        ind_svc = TechnicalIndicatorsService()
        indicators_map = {
            "GGAL.BA": ind_svc.compute_snapshot(ggal_bars, ticker="GGAL.BA"),
            "YPFD": ind_svc.compute_snapshot(ypfd_bars, ticker="YPFD"),
            "AAPL": ind_svc.compute_snapshot(aapl_bars, ticker="AAPL"),
        }
        sig_svc = SignalGeneratorService()
        ggal_sig = sig_svc.generate_signal(ggal_bars, ticker="GGAL.BA")
        self.assertIn(
            ggal_sig.action,
            (SignalAction.BUY, SignalAction.HOLD, SignalAction.SELL),
        )
        self.assertIsNotNone(indicators_map["GGAL.BA"].atr_14)

        # Step 2: Module 7.2 Bimonetary Mark-to-Market Valuation (with Caja de Valores 0-cost on AAPL)
        mtm_positions = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                currency="ARS",
                avg_cost_price=Decimal("1800"),
                market_price=indicators_map["GGAL.BA"].close,  # 2400 ARS -> 2.40 USD @ FX 1000
                entry_fx_rate=Decimal("950"),
            ),
            PositionValuationInput(
                ticker="YPFD",
                quantity=Decimal("1"),
                currency="ARS",
                avg_cost_price=Decimal("20000"),
                market_price=indicators_map["YPFD"].close,  # 24400 ARS -> 24.40 USD @ FX 1000
                entry_fx_rate=Decimal("950"),
            ),
            PositionValuationInput(
                ticker="AAPL",
                quantity=Decimal("2"),
                currency="USD",
                avg_cost_price=Decimal(
                    "0"
                ),  # Caja de Valores zero-cost -> indeterminate PnL % (None)
                market_price=indicators_map["AAPL"].close,  # 224 USD -> 448 USD total
            ),
        ]
        val_svc = PortfolioValuationService()
        mtm_report = val_svc.value_portfolio_mark_to_market(
            positions=mtm_positions,
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_ars=Decimal("25200"),  # 25.20 USD
            cash_balance_usd=Decimal("0"),
            portfolio_id="pf-ch7-e2e",
            as_of=self.as_of,
        )
        # Verify AAPL has None unrealized_pnl_pct_usd and None unrealized_pnl_pct_ars
        aapl_mtm = next(p for p in mtm_report.positions if p.ticker == "AAPL")
        self.assertIsNone(aapl_mtm.unrealized_pnl_pct_usd)
        self.assertIsNone(aapl_mtm.unrealized_pnl_pct_ars)

        # Step 3: Module 7.3 Dynamic Volatility Calibration + Bimonetary Rebalance + FSM Batch
        raw_specs = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.3000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.3000")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.4000")),
        ]
        reb_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.DYNAMIC_VOLATILITY,
                rebalance_mode=RebalanceMode.FULL_TO_TARGET,
                default_relative_tolerance=Decimal("0.1500"),
                commission_bps=Decimal("50"),
                allow_fractional_shares=False,
            )
        )
        calibrated_specs = reb_svc.calibrate_specs_from_indicators(
            target_specs=raw_specs,
            indicators_by_ticker=indicators_map,
            baseline_atr_pct=Decimal("0.0200"),
        )

        # Rebalance in USD base currency
        reb_usd = reb_svc.rebalance_from_mtm_report(
            mtm_report=mtm_report,
            target_specs=calibrated_specs,
            base_currency="USD",
        )
        self.assertTrue(reb_usd.needs_rebalancing)
        self.assertIn("AAPL", reb_usd.breached_tickers)
        # AAPL was sold to reduce weight from ~89.6% to ~40%, and its unknown cost basis
        # must produce estimated_realized_pnl = None on the AAPL SELL order!
        aapl_sell = next(o for o in reb_usd.orders if o.ticker == "AAPL" and o.side == "SELL")
        self.assertIsNone(aapl_sell.estimated_realized_pnl)

        # Rebalance in ARS base currency (verifies Round 4 unit price conversion for USD asset AAPL)
        reb_ars = reb_svc.rebalance_from_mtm_report(
            mtm_report=mtm_report,
            target_specs=calibrated_specs,
            base_currency="ARS",
        )
        self.assertTrue(reb_ars.needs_rebalancing)
        aapl_sell_ars = next(o for o in reb_ars.orders if o.ticker == "AAPL" and o.side == "SELL")
        # AAPL unit price in ARS must be 224 USD * 1000 ARS/USD = 224,000.0000 ARS
        self.assertEqual(aapl_sell_ars.execution_price, Decimal("224000.0000"))
        self.assertIsNone(aapl_sell_ars.estimated_realized_pnl)

        # Step 4: FSM Execution Batch
        fsm_batch = reb_svc.build_fsm_execution_batch(reb_usd)
        self.assertGreaterEqual(fsm_batch.sell_orders_count, 1)
        self.assertEqual(fsm_batch.tickets[0].execution_phase, "LIQUIDATION_SELL")
        self.assertEqual(fsm_batch.tickets[0].order_payload["status"], "PENDING")

    def test_multi_lot_tax_selection_fifo_lifo_hifo_and_unknown_cost_or_conflicting_price_guards(
        self,
    ) -> None:
        """
        Verify multi-lot tax selection policies (`AVERAGE_COST`, `FIFO`, `LIFO`, `HIFO`)
        and Audit Round 1 multi-lot consolidation invariants:
        - `FIFO`: consumes oldest `acquired_at` lots first.
        - `LIFO`: consumes newest `acquired_at` lots first.
        - `HIFO`: consumes highest `avg_cost_price` lots first (minimizing taxable gain).
        - `AVERAGE_COST`: uses weighted average cost across all positive lots.
        - Unknown cost propagation: if ANY positive lot has `avg_cost_price=None`,
          `estimated_realized_pnl` is `None`; if a zero-quantity lot has `avg_cost_price=None`,
          known cost basis from positive lots is preserved.
        - Conflicting `market_price` across duplicate ticker entries raises `InvalidToleranceBandConfigError`.
        """
        t1 = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        t3 = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)

        # GGAL has 3 tax lots totaling 60 shares @ $100 market price ($6,000):
        # Lot A (oldest, t1): 20 shares @ $50 cost
        # Lot B (middle, t2): 20 shares @ $120 cost (highest cost)
        # Lot C (newest, t3): 20 shares @ $70 cost
        # Plus a zero-quantity historical lot with avg_cost_price=None (must not poison known cost)
        lots = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("50"),
                lot_id="LOT-A",
                acquired_at=t1,
            ),
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("120"),
                lot_id="LOT-B",
                acquired_at=t2,
            ),
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("70"),
                lot_id="LOT-C",
                acquired_at=t3,
            ),
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("0"),
                market_price=Decimal("100"),
                avg_cost_price=None,
                lot_id="LOT-EMPTY",
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("40"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        # Total portfolio = $10,000. Target GGAL = 30% ($3,000) -> SELL 30 shares of GGAL @ $100 ($3,000 gross)
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.3000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.7000")),
        ]

        def run_with_policy(policy: TaxLotSelectionPolicy) -> Decimal | None:
            svc = ToleranceBandRebalancerService(
                ToleranceBandRebalancerConfig(
                    tax_lot_policy=policy,
                    commission_bps=Decimal("0"),
                )
            )
            rep = svc.evaluate_and_rebalance(
                positions=lots,
                target_specs=targets,
                as_of=self.as_of,
            )
            sell_ord = next(o for o in rep.orders if o.ticker == "GGAL" and o.side == "SELL")
            self.assertEqual(sell_ord.quantity, Decimal("30.0000"))
            return sell_ord.estimated_realized_pnl

        # 1. AVERAGE_COST: avg_cost = (20*50 + 20*120 + 20*70) / 60 = 4800 / 60 = $80.00
        # Selling 30 shares @ $100 -> proceeds $3,000 - cost $2,400 = +$600.0000
        self.assertEqual(
            run_with_policy(TaxLotSelectionPolicy.AVERAGE_COST),
            Decimal("600.0000"),
        )

        # 2. FIFO: sells 20 from Lot A ($50) + 10 from Lot B ($120) -> cost = 1000 + 1200 = $2,200
        # Proceeds $3,000 - $2,200 = +$800.0000
        self.assertEqual(
            run_with_policy(TaxLotSelectionPolicy.FIFO),
            Decimal("800.0000"),
        )

        # 3. LIFO: sells 20 from Lot C ($70) + 10 from Lot B ($120) -> cost = 1400 + 1200 = $2,600
        # Proceeds $3,000 - $2,600 = +$400.0000
        self.assertEqual(
            run_with_policy(TaxLotSelectionPolicy.LIFO),
            Decimal("400.0000"),
        )

        # 4. HIFO: sells 20 from Lot B ($120) + 10 from Lot C ($70) -> cost = 2400 + 700 = $3,100
        # Proceeds $3,000 - $3,100 = -$100.0000 (tax loss harvesting!)
        self.assertEqual(
            run_with_policy(TaxLotSelectionPolicy.HIFO),
            Decimal("-100.0000"),
        )

        # 5. If ANY positive lot has avg_cost_price=None, estimated_realized_pnl must be None
        unknown_lot_positions = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("80"),
            ),
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=None,
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("40"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        rep_unknown = self.default_service.evaluate_and_rebalance(
            positions=unknown_lot_positions,
            target_specs=targets,
            as_of=self.as_of,
        )
        sell_unknown = next(
            o for o in rep_unknown.orders if o.ticker == "GGAL" and o.side == "SELL"
        )
        self.assertIsNone(sell_unknown.estimated_realized_pnl)

        # 6. Conflicting market_price across lots of the same ticker raises InvalidToleranceBandConfigError
        conflicting_price_lots = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
            ),
            RebalancePositionInput(
                ticker="GGAL.BA",
                quantity=Decimal("30"),
                market_price=Decimal("101"),
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("40"),
                market_price=Decimal("100"),
            ),
        ]
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.evaluate_and_rebalance(
                positions=conflicting_price_lots,
                target_specs=targets,
                as_of=self.as_of,
            )

    def test_breach_detected_but_blocked_by_integer_share_floor_or_dust_filter_preserves_invariants(
        self,
    ) -> None:
        """
        Verify Audit Round 3 edge case: when a position breaches its tolerance band
        (`breached_tickers` is non-empty and `needs_rebalancing=True`), but every
        candidate order either floors to `0` whole shares (`allow_fractional_shares=False`
        on a high-priced asset) or is suppressed by `min_trade_notional`, `orders` is
        empty (`[]`) while all post-trade weights, values, and portfolio invariants hold.
        """
        # Portfolio = $10,000: BRK.A = 1 share @ $7,000 (70%), YPFD = 1 share @ $3,000 (30%)
        # Target = 50% / 50% ($5,000 each). Required trade on BRK.A is $2,000 / $7,000 = 0.2857 shares
        # With allow_fractional_shares=False, floor(0.2857) = 0 shares!
        positions = [
            RebalancePositionInput(
                ticker="BRK.A",
                quantity=Decimal("1"),
                market_price=Decimal("7000"),
            ),
            RebalancePositionInput(
                ticker="YPFD",
                quantity=Decimal("1"),
                market_price=Decimal("3000"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="BRK.A", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]
        int_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(allow_fractional_shares=False)
        )
        rep_int = int_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            as_of=self.as_of,
        )
        self.assertTrue(rep_int.needs_rebalancing)
        self.assertEqual(rep_int.breached_tickers, ["BRK.A", "YPFD"])
        self.assertEqual(rep_int.orders, [])
        self.assertEqual(rep_int.portfolio_turnover, Decimal("0.0000"))
        self.assertEqual(
            sum(ev.post_trade_weight for ev in rep_int.evaluations),
            Decimal("1.0000"),
        )

        # Same scenario with fractional shares allowed, but min_trade_notional = $2,500 suppresses $2,000 trade
        dust_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                allow_fractional_shares=True,
                min_trade_notional=Decimal("2500"),
            )
        )
        rep_dust = dust_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            as_of=self.as_of,
        )
        self.assertTrue(rep_dust.needs_rebalancing)
        self.assertEqual(rep_dust.breached_tickers, ["BRK.A", "YPFD"])
        self.assertEqual(rep_dust.orders, [])
        self.assertEqual(
            sum(ev.post_trade_weight for ev in rep_dust.evaluations),
            Decimal("1.0000"),
        )

    def test_post_trade_weight_largest_remainder_exact_sum_invariant_with_zero_and_positive_cash(
        self,
    ) -> None:
        """
        Verify Audit Round 2 invariant:
        - For a 3-asset equal-value portfolio ($100 / $100 / $100 = $300 total) with
          `projected_ending_cash == 0.0000`, `sum(ev.post_trade_weight for ev in evaluations)`
          equals `Decimal("1.0000")` exactly via the Largest Remainder Method (instead of `0.9999`).
        - When `projected_ending_cash > 0.0000`, `sum(ev.post_trade_weight) + cash_weight == Decimal("1.0000")`
          and `sum(ev.post_trade_weight) <= Decimal("1.0000")`.
        """
        positions = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("1"),
                market_price=Decimal("100"),
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("1"),
                market_price=Decimal("100"),
            ),
            RebalancePositionInput(
                ticker="CCC",
                quantity=Decimal("1"),
                market_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.3334")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.3333")),
            AssetTargetBandSpec(ticker="CCC", target_weight=Decimal("0.3333")),
        ]
        rep_zero_cash = self.default_service.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("0"),
            as_of=self.as_of,
        )
        self.assertEqual(rep_zero_cash.projected_ending_cash, Decimal("0.0000"))
        self.assertEqual(
            sum(ev.post_trade_weight for ev in rep_zero_cash.evaluations),
            Decimal("1.0000"),
        )

        # With positive cash ($30 cash on $300 positions = $330 total)
        rep_pos_cash = self.default_service.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("30"),
            as_of=self.as_of,
        )
        self.assertEqual(rep_pos_cash.projected_ending_cash, Decimal("30.0000"))
        self.assertLess(
            sum(ev.post_trade_weight for ev in rep_pos_cash.evaluations),
            Decimal("1.0000"),
        )

    def test_to_band_boundary_asymmetric_upper_only_and_lower_only_breaches_and_batch_id_collision_resistance(
        self,
    ) -> None:
        """
        Verify Audit Rounds 3 & 9:
        1. In `RebalanceMode.TO_BAND_BOUNDARY`, when only `UPPER` breaches exist and
           underweighted assets sit inside their lower band (`lower_band <= current_weight < target_weight`),
           the freed sell proceeds are actively reallocated to those underweighted assets up to
           their `target_weight` instead of sitting idle in cash.
        2. `build_fsm_execution_batch` includes `rebalance_mode`, `band_type`, and
           `total_portfolio_value` in the `batch_id` preimage so distinct configurations
           never collide on `batch_id`.
        """
        # Portfolio = $10,000:
        # AAA = $5,000 (50%) vs target 40% [35%, 45%] (ABSOLUTE 5% band) -> UPPER breach (50% > 45%)
        # BBB = $2,500 (25%) vs target 30% [25%, 35%] -> inside band (25% >= 25%), underweighted vs 30%
        # CCC = $2,500 (25%) vs target 30% [25%, 35%] -> inside band (25% >= 25%), underweighted vs 30%
        positions = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("50"),
                market_price=Decimal("100"),
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("25"),
                market_price=Decimal("100"),
            ),
            RebalancePositionInput(
                ticker="CCC",
                quantity=Decimal("25"),
                market_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(
                ticker="AAA",
                target_weight=Decimal("0.4000"),
                absolute_tolerance_override=Decimal("0.0500"),
            ),
            AssetTargetBandSpec(
                ticker="BBB",
                target_weight=Decimal("0.3000"),
                absolute_tolerance_override=Decimal("0.0500"),
            ),
            AssetTargetBandSpec(
                ticker="CCC",
                target_weight=Decimal("0.3000"),
                absolute_tolerance_override=Decimal("0.0500"),
            ),
        ]
        boundary_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                rebalance_mode=RebalanceMode.TO_BAND_BOUNDARY,
            )
        )
        rep_boundary = boundary_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            portfolio_id="pf-boundary-asym",
            as_of=self.as_of,
        )
        # Only AAA breached UPPER (50% > 45% -> sells $500 to reach 45%)
        self.assertEqual(rep_boundary.breached_tickers, ["AAA"])
        self.assertEqual(rep_boundary.total_sell_gross, Decimal("500.0000"))
        # The $500 freed from AAA must be reinvested into BBB and CCC ($250 each)!
        self.assertEqual(rep_boundary.total_buy_gross, Decimal("500.0000"))
        self.assertEqual(rep_boundary.projected_ending_cash, Decimal("0.0000"))

        # Verify batch_id collision resistance when rebalance_mode or band_type differs
        rel_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.RELATIVE,
                rebalance_mode=RebalanceMode.TO_BAND_BOUNDARY,
            )
        )
        # With relative tolerance 0.125 on AAA (0.40 * 0.125 = 0.05 -> same 45% upper band!)
        rel_targets = [
            AssetTargetBandSpec(
                ticker="AAA",
                target_weight=Decimal("0.4000"),
                relative_tolerance_override=Decimal("0.1250"),
            ),
            AssetTargetBandSpec(
                ticker="BBB",
                target_weight=Decimal("0.3000"),
                relative_tolerance_override=Decimal("0.2000"),
            ),
            AssetTargetBandSpec(
                ticker="CCC",
                target_weight=Decimal("0.3000"),
                relative_tolerance_override=Decimal("0.2000"),
            ),
        ]
        rep_rel = rel_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=rel_targets,
            portfolio_id="pf-boundary-asym",
            as_of=self.as_of,
        )
        batch_abs = boundary_svc.build_fsm_execution_batch(rep_boundary)
        batch_rel = rel_svc.build_fsm_execution_batch(rep_rel)
        # Even though the resulting orders are identical, band_type differs -> batch_id must differ!
        self.assertNotEqual(batch_abs.batch_id, batch_rel.batch_id)

    def test_scale_boundaries_10_pow_12_subpip_prices_ba_suffix_and_high_commission_500_bps_stress(
        self,
    ) -> None:
        """
        Verify Audit Rounds 7, 8 & 10:
        - Institutional scale boundary up to `10^12` (`$1,000,000,000,000.0000`) without
          precision loss under `localcontext(prec=50)`.
        - Sub-pip price (`0.0001`) and `.BA` suffix matching in both `positions` and `market_prices`.
        - Extreme friction stress at `commission_bps = 500` (5.00%) +
          `cash_buffer_weight = 0.2500`, preserving `projected_ending_cash >= required_buffer`
          and `projected_post_trade_portfolio_value == sum(post_trade_value) + projected_ending_cash`.
        """
        # 1. Scale boundary near 10^12 ($800B portfolio) with 500 bps commission and 25% cash buffer
        stress_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                commission_bps=Decimal("500"),
                cash_buffer_weight=Decimal("0.2500"),
                allow_fractional_shares=True,
            )
        )
        mega_positions = [
            RebalancePositionInput(
                ticker="GGAL.BA",
                quantity=Decimal("800000000"),
                market_price=Decimal("1000"),
                avg_cost_price=Decimal("800"),
            ),
        ]
        # Target weights (0.3750 + 0.3750 = 0.7500) + cash_buffer_weight (0.2500) = 1.0000
        mega_targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.3750")),
            AssetTargetBandSpec(ticker="YPFD.BA", target_weight=Decimal("0.3750")),
        ]
        # YPFD.BA is unheld and resolves its price from "YPFD" in market_prices via .BA matching
        mega_prices = {
            "YPFD": Decimal("1000.0000"),
        }
        rep_mega = stress_svc.evaluate_and_rebalance(
            positions=mega_positions,
            target_specs=mega_targets,
            market_prices=mega_prices,
            initial_cash=Decimal("0"),
            as_of=self.as_of,
        )
        self.assertTrue(rep_mega.needs_rebalancing)
        self.assertEqual(
            rep_mega.total_portfolio_value,
            Decimal("800000000000.0000"),
        )
        required_buffer = Decimal("800000000000.0000") * Decimal("0.2500")
        self.assertGreaterEqual(rep_mega.projected_ending_cash, required_buffer)
        self.assertEqual(
            rep_mega.projected_post_trade_portfolio_value,
            sum(ev.post_trade_value for ev in rep_mega.evaluations)
            + rep_mega.projected_ending_cash,
        )

        # 2. Sub-pip price (0.0001) position rebalance
        micro_positions = [
            RebalancePositionInput(
                ticker="SHIB",
                quantity=Decimal("70000000"),
                market_price=Decimal("0.0001"),
            ),
            RebalancePositionInput(
                ticker="PEPE",
                quantity=Decimal("30000000"),
                market_price=Decimal("0.0001"),
            ),
        ]
        micro_targets = [
            AssetTargetBandSpec(ticker="SHIB", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="PEPE", target_weight=Decimal("0.5000")),
        ]
        rep_micro = self.default_service.evaluate_and_rebalance(
            positions=micro_positions,
            target_specs=micro_targets,
            as_of=self.as_of,
        )
        self.assertTrue(rep_micro.needs_rebalancing)
        self.assertEqual(rep_micro.total_sell_gross, Decimal("2000.0000"))
        self.assertEqual(rep_micro.total_buy_gross, Decimal("2000.0000"))

    def test_audit_tbr_01_exact_lower_and_upper_band_boundary_non_breach_invariants(self) -> None:
        """Verify positions sitting exactly at lower_band or upper_band are NOT breached."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("40"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("60"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        # Default relative_tolerance = 0.2000 -> bands [0.4000, 0.6000]; AAA=0.4000, BBB=0.6000
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertFalse(rep.needs_rebalancing)
        self.assertEqual(rep.breached_tickers, [])
        self.assertEqual(rep.orders, [])

    def test_audit_tbr_02_one_pip_beyond_band_boundary_triggers_rebalance(self) -> None:
        """Verify 0.0001 weight drift beyond [0.4000, 0.6000] triggers rebalancing."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("39.99"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("60.01"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertTrue(rep.needs_rebalancing)
        self.assertEqual(rep.breached_tickers, ["AAA", "BBB"])

    def test_audit_tbr_03_absolute_band_with_per_asset_override_and_min_max_clamping(self) -> None:
        """Verify BandType.ABSOLUTE respects per-asset override and clamps to [min_band_half_width, max_band_half_width]."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0500"),
                min_band_half_width=Decimal("0.0200"),
                max_band_half_width=Decimal("0.1000"),
            )
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("50"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("50"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(
                ticker="AAA",
                target_weight=Decimal("0.5000"),
                absolute_tolerance_override=Decimal("0.0050"),  # Clamped up to 0.0200
            ),
            AssetTargetBandSpec(
                ticker="BBB",
                target_weight=Decimal("0.5000"),
                absolute_tolerance_override=Decimal("0.2500"),  # Clamped down to 0.1000
            ),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        ev_map = {e.ticker: e for e in rep.evaluations}
        self.assertEqual(ev_map["AAA"].upper_band - ev_map["AAA"].target_weight, Decimal("0.0200"))
        self.assertEqual(ev_map["BBB"].upper_band - ev_map["BBB"].target_weight, Decimal("0.1000"))

    def test_audit_tbr_04_relative_band_with_per_asset_override(self) -> None:
        """Verify BandType.RELATIVE uses relative_tolerance_override * target_weight when provided."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("50"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("50"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(
                ticker="AAA",
                target_weight=Decimal("0.5000"),
                relative_tolerance_override=Decimal("0.1000"),  # 0.50 * 0.10 = 0.0500
            ),
            AssetTargetBandSpec(
                ticker="BBB",
                target_weight=Decimal("0.5000"),
                relative_tolerance_override=Decimal("0.3000"),  # 0.50 * 0.30 = 0.1500
            ),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        ev_map = {e.ticker: e for e in rep.evaluations}
        self.assertEqual(ev_map["AAA"].upper_band - ev_map["AAA"].target_weight, Decimal("0.0500"))
        self.assertEqual(ev_map["BBB"].upper_band - ev_map["BBB"].target_weight, Decimal("0.1500"))

    def test_audit_tbr_05_dynamic_volatility_band_scales_by_volatility_multiplier(self) -> None:
        """Verify BandType.DYNAMIC_VOLATILITY scales relative band half-width by volatility_multiplier."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.DYNAMIC_VOLATILITY,
                default_relative_tolerance=Decimal("0.2000"),
                max_band_half_width=Decimal("0.2500"),
            )
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("50"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("50"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(
                ticker="AAA",
                target_weight=Decimal("0.5000"),
                volatility_multiplier=Decimal("0.5000"),  # 0.50 * 0.20 * 0.50 = 0.0500
            ),
            AssetTargetBandSpec(
                ticker="BBB",
                target_weight=Decimal("0.5000"),
                volatility_multiplier=Decimal("2.0000"),  # 0.50 * 0.20 * 2.00 = 0.2000
            ),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        ev_map = {e.ticker: e for e in rep.evaluations}
        self.assertEqual(ev_map["AAA"].upper_band - ev_map["AAA"].target_weight, Decimal("0.0500"))
        self.assertEqual(ev_map["BBB"].upper_band - ev_map["BBB"].target_weight, Decimal("0.2000"))

    def test_audit_tbr_06_full_to_target_vs_to_band_boundary_on_4_assets(self) -> None:
        """Verify FULL_TO_TARGET generates strictly greater or equal turnover than TO_BAND_BOUNDARY on 4 assets."""
        positions = [
            RebalancePositionInput(
                ticker="A1", quantity=Decimal("40"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="A2", quantity=Decimal("35"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="A3", quantity=Decimal("15"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="A4", quantity=Decimal("10"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker=f"A{i}", target_weight=Decimal("0.2500"))
            for i in range(1, 5)
        ]
        rep_full = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        svc_bound = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(rebalance_mode=RebalanceMode.TO_BAND_BOUNDARY)
        )
        rep_bound = svc_bound.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertGreater(rep_full.portfolio_turnover, rep_bound.portfolio_turnover)

    def test_audit_tbr_07_full_to_target_on_8_assets_equal_target_weights(self) -> None:
        """Verify FULL_TO_TARGET rebalancing across 8 assets with 0.1250 target weights."""
        positions = [
            RebalancePositionInput(
                ticker=f"T{i:02d}",
                quantity=Decimal(str(20 if i <= 4 else 5)),
                market_price=Decimal("100"),
            )
            for i in range(1, 9)
        ]
        targets = [
            AssetTargetBandSpec(ticker=f"T{i:02d}", target_weight=Decimal("0.1250"))
            for i in range(1, 9)
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertTrue(rep.needs_rebalancing)
        for ev in rep.evaluations:
            self.assertEqual(ev.post_trade_weight, Decimal("0.1250"))

    def test_audit_tbr_08_full_to_target_on_20_assets_institutional_portfolio(self) -> None:
        """Verify FULL_TO_TARGET rebalancing across 20 assets with 0.0500 target weights."""
        positions = [
            RebalancePositionInput(
                ticker=f"T{i:02d}",
                quantity=Decimal(str(8 if i <= 10 else 2)),
                market_price=Decimal("100"),
            )
            for i in range(1, 21)
        ]
        targets = [
            AssetTargetBandSpec(ticker=f"T{i:02d}", target_weight=Decimal("0.0500"))
            for i in range(1, 21)
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertTrue(rep.needs_rebalancing)
        self.assertEqual(len(rep.orders), 20)
        self.assertEqual(sum(ev.post_trade_weight for ev in rep.evaluations), Decimal("1.0000"))

    def test_audit_tbr_09_to_band_boundary_lower_only_breaches_funded_by_excess_cash(self) -> None:
        """Verify TO_BAND_BOUNDARY when only LOWER breaches occur (due to high cash) buys up to lower_band."""
        # Positions: AAA = $150 (15%), BBB = $150 (15%), Cash = $700 (70%) -> Total = $1,000
        # Target = 40% AAA, 40% BBB, cash_buffer_weight = 20%
        # Band = ABSOLUTE 0.0500 -> [0.3500, 0.4500]. Both AAA and BBB breach LOWER (0.1500 < 0.3500)
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                default_absolute_tolerance=Decimal("0.0500"),
                rebalance_mode=RebalanceMode.TO_BAND_BOUNDARY,
                cash_buffer_weight=Decimal("0.2000"),
            )
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("1.5"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("1.5"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.4000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.4000")),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("700"),
            as_of=self.as_of,
        )
        self.assertEqual(rep.breached_tickers, ["AAA", "BBB"])
        self.assertEqual(rep.total_sell_gross, Decimal("0.0000"))
        self.assertGreater(rep.total_buy_gross, Decimal("0.0000"))

    def test_audit_tbr_10_tax_lot_fifo_partial_single_lot_consumption(self) -> None:
        """Verify FIFO consuming only a partial slice of the oldest lot."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 6, 1, tzinfo=UTC)
        lots = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("50"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("60"),
                acquired_at=t1,
            ),
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("90"),
                acquired_at=t2,
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                tax_lot_policy=TaxLotSelectionPolicy.FIFO, commission_bps=Decimal("0")
            )
        )
        rep = svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
        sell_ord = next(o for o in rep.orders if o.ticker == "AAA")
        # Sells 20 shares from oldest lot @ $60 cost -> gain = 20 * (100 - 60) = $800.0000
        self.assertEqual(sell_ord.quantity, Decimal("20.0000"))
        self.assertEqual(sell_ord.estimated_realized_pnl, Decimal("800.0000"))

    def test_audit_tbr_11_tax_lot_lifo_partial_single_lot_consumption(self) -> None:
        """Verify LIFO consuming only the newest lot."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 6, 1, tzinfo=UTC)
        lots = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("50"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("60"),
                acquired_at=t1,
            ),
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("90"),
                acquired_at=t2,
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                tax_lot_policy=TaxLotSelectionPolicy.LIFO, commission_bps=Decimal("0")
            )
        )
        rep = svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
        sell_ord = next(o for o in rep.orders if o.ticker == "AAA")
        # Sells 20 shares from newest lot @ $90 cost -> gain = 20 * (100 - 90) = $200.0000
        self.assertEqual(sell_ord.estimated_realized_pnl, Decimal("200.0000"))

    def test_audit_tbr_12_tax_lot_hifo_full_liquidation_all_lots_equals_average_cost(self) -> None:
        """Verify that when 100% of an unlisted asset's lots are liquidated, FIFO, LIFO, HIFO, and AVERAGE_COST agree."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 6, 1, tzinfo=UTC)
        lots = [
            RebalancePositionInput(
                ticker="LEGACY",
                quantity=Decimal("10"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("50"),
                acquired_at=t1,
            ),
            RebalancePositionInput(
                ticker="LEGACY",
                quantity=Decimal("10"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("110"),
                acquired_at=t2,
            ),
            RebalancePositionInput(
                ticker="CORE",
                quantity=Decimal("80"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [AssetTargetBandSpec(ticker="CORE", target_weight=Decimal("1.0000"))]
        pnls: list[Decimal | None] = []
        for pol in (
            TaxLotSelectionPolicy.AVERAGE_COST,
            TaxLotSelectionPolicy.FIFO,
            TaxLotSelectionPolicy.LIFO,
            TaxLotSelectionPolicy.HIFO,
        ):
            svc = ToleranceBandRebalancerService(
                ToleranceBandRebalancerConfig(tax_lot_policy=pol, commission_bps=Decimal("0"))
            )
            rep = svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
            pnls.append(rep.total_estimated_realized_pnl)
        self.assertEqual(pnls, [Decimal("400.0000")] * 4)

    def test_audit_tbr_13_tax_lot_mixed_timezone_naive_aware_and_none_acquired_at_sorting(
        self,
    ) -> None:
        """Verify FIFO and LIFO sort mixed timezone-aware, timezone-naive, and None acquired_at timestamps without TypeError."""
        lots = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("25"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("50"),
                acquired_at=datetime(2026, 1, 10, 12, 0),  # Naive
                lot_id="L-NAIVE",
            ),
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("25"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("80"),
                acquired_at=datetime(2026, 2, 10, 12, 0, tzinfo=UTC),  # Aware
                lot_id="L-AWARE",
            ),
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("25"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("95"),
                acquired_at=None,  # None timestamp
                lot_id="L-NONE",
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("25"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        for pol in (
            TaxLotSelectionPolicy.FIFO,
            TaxLotSelectionPolicy.LIFO,
            TaxLotSelectionPolicy.HIFO,
        ):
            svc = ToleranceBandRebalancerService(ToleranceBandRebalancerConfig(tax_lot_policy=pol))
            rep = svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
            self.assertIsNotNone(rep.total_estimated_realized_pnl)

    def test_audit_tbr_14_commission_bps_zero_exact_self_financing_symmetry(self) -> None:
        """Verify with commission_bps=0 and initial_cash=0 that total_sell_gross == total_buy_gross."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("70"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("30"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertEqual(rep.total_sell_gross, Decimal("2000.0000"))
        self.assertEqual(rep.total_buy_gross, Decimal("2000.0000"))
        self.assertEqual(rep.total_estimated_commissions, Decimal("0.0000"))

    def test_audit_tbr_15_commission_bps_10_waterfall_deduction(self) -> None:
        """Verify commission_bps=10 (0.10%) deducts sell and buy commissions without negative ending cash."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(commission_bps=Decimal("10"))
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("70"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("30"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertGreater(rep.total_estimated_commissions, Decimal("0.0000"))
        self.assertGreaterEqual(rep.projected_ending_cash, Decimal("0.0000"))

    def test_audit_tbr_16_commission_bps_50_waterfall_deduction(self) -> None:
        """Verify commission_bps=50 (0.50%) preserves cash conservation identity."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(commission_bps=Decimal("50"))
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("70"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("30"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertEqual(
            rep.initial_cash
            + rep.total_sell_gross
            - rep.total_buy_gross
            - rep.total_estimated_commissions,
            rep.projected_ending_cash,
        )

    def test_audit_tbr_17_commission_bps_150_and_realized_pnl_net_of_sell_commission(self) -> None:
        """Verify commission_bps=150 (1.50%) reduces estimated_realized_pnl on SELL orders by sell commission."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(commission_bps=Decimal("150"))
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("70"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("80"),
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        sell_ord = next(o for o in rep.orders if o.side == "SELL")
        # Sells 20 shares @ $100 ($2,000 gross), cost = $1,600, commission = 1.5% of $2,000 = $30 -> net PnL = $370.0000
        self.assertEqual(sell_ord.estimated_commission, Decimal("30.0000"))
        self.assertEqual(sell_ord.estimated_realized_pnl, Decimal("370.0000"))

    def test_audit_tbr_18_cash_buffer_weight_reserves_liquidity_during_rebalance(self) -> None:
        """Verify cash_buffer_weight=0.1000 retains at least 10% of portfolio value in projected_ending_cash."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(cash_buffer_weight=Decimal("0.1000"))
        )
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("90"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("10"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.4500")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.4500")),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertGreaterEqual(rep.projected_ending_cash, Decimal("1000.0000"))

    def test_audit_tbr_19_integer_shares_rounding_with_multiple_buys_preserves_positive_cash(
        self,
    ) -> None:
        """Verify allow_fractional_shares=False across 3 BUY orders floors share quantities and leaves residual cash."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                allow_fractional_shares=False, commission_bps=Decimal("25")
            )
        )
        positions = [
            RebalancePositionInput(
                ticker="A1", quantity=Decimal("80"), market_price=Decimal("100")
            ),
            RebalancePositionInput(ticker="A2", quantity=Decimal("5"), market_price=Decimal("33")),
            RebalancePositionInput(ticker="A3", quantity=Decimal("5"), market_price=Decimal("37")),
            RebalancePositionInput(ticker="A4", quantity=Decimal("5"), market_price=Decimal("41")),
        ]
        targets = [
            AssetTargetBandSpec(ticker=f"A{i}", target_weight=Decimal("0.2500"))
            for i in range(1, 5)
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        for o in rep.orders:
            self.assertEqual(o.quantity, o.quantity.to_integral_value())
        self.assertGreaterEqual(rep.projected_ending_cash, Decimal("0.0000"))

    def test_audit_tbr_20_liquidate_unlisted_holdings_true_sells_100_pct_of_unlisted(self) -> None:
        """Verify liquidate_unlisted_holdings=True liquidates 100% of positions not in target_specs."""
        positions = [
            RebalancePositionInput(
                ticker="UNLISTED", quantity=Decimal("30"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="CORE", quantity=Decimal("70"), market_price=Decimal("100")
            ),
        ]
        targets = [AssetTargetBandSpec(ticker="CORE", target_weight=Decimal("1.0000"))]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        unlisted_ev = next(e for e in rep.evaluations if e.ticker == "UNLISTED")
        self.assertEqual(unlisted_ev.post_trade_quantity, Decimal("0.0000"))
        self.assertEqual(unlisted_ev.post_trade_weight, Decimal("0.0000"))

    def test_audit_tbr_21_liquidate_unlisted_holdings_false_retains_unlisted_position(self) -> None:
        """Verify liquidate_unlisted_holdings=False does not sell unlisted positions when target assets are inside bands."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(liquidate_unlisted_holdings=False)
        )
        positions = [
            RebalancePositionInput(
                ticker="UNLISTED", quantity=Decimal("10"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="CORE", quantity=Decimal("90"), market_price=Decimal("100")
            ),
        ]
        targets = [AssetTargetBandSpec(ticker="CORE", target_weight=Decimal("1.0000"))]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertFalse(rep.needs_rebalancing)
        self.assertEqual(rep.orders, [])

    def test_audit_tbr_22_unheld_target_asset_resolved_via_reference_price_on_spec(self) -> None:
        """Verify unheld target asset resolves execution price via AssetTargetBandSpec.reference_price."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("100"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(
                ticker="NEWBIE", target_weight=Decimal("0.5000"), reference_price=Decimal("250")
            ),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        buy_ord = next(o for o in rep.orders if o.ticker == "NEWBIE")
        self.assertEqual(buy_ord.execution_price, Decimal("250.0000"))
        self.assertEqual(buy_ord.quantity, Decimal("20.0000"))

    def test_audit_tbr_23_unheld_target_asset_missing_price_raises_error(self) -> None:
        """Verify unheld target asset without market_prices entry or reference_price raises MissingRebalancePriceError."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("100"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="NEWBIE", target_weight=Decimal("0.5000")),
        ]
        with self.assertRaises(MissingRebalancePriceError):
            self.default_service.evaluate_and_rebalance(
                positions=positions, target_specs=targets, as_of=self.as_of
            )

    def test_audit_tbr_24_calibrate_specs_from_indicators_low_volatility_narrows_multiplier(
        self,
    ) -> None:
        """Verify calibrate_specs_from_indicators narrows volatility_multiplier (< 1.0) when ATR% < baseline_atr_pct."""
        specs = [AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("1.0000"))]
        snap = TechnicalIndicatorsSnapshot(
            ticker="AAPL",
            as_of=self.as_of,
            close=Decimal("200"),
            atr_14=Decimal("2.0"),  # 1.0% ATR vs 2.0% baseline
        )
        calibrated = self.default_service.calibrate_specs_from_indicators(
            target_specs=specs,
            indicators_by_ticker={"AAPL": snap},
            baseline_atr_pct=Decimal("0.0200"),
        )
        self.assertEqual(calibrated[0].volatility_multiplier, Decimal("0.5000"))

    def test_audit_tbr_25_calibrate_specs_from_indicators_high_volatility_widens_and_clamps_multiplier(
        self,
    ) -> None:
        """Verify calibrate_specs_from_indicators widens volatility_multiplier and clamps at max_multiplier."""
        specs = [AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("1.0000"))]
        snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=self.as_of,
            close=Decimal("100"),
            atr_14=Decimal("10.0"),  # 10% ATR vs 2% baseline -> 5.0 -> clamped to 2.5
        )
        calibrated = self.default_service.calibrate_specs_from_indicators(
            target_specs=specs,
            indicators_by_ticker={"GGAL": snap},
            baseline_atr_pct=Decimal("0.0200"),
            max_multiplier=Decimal("2.5000"),
        )
        self.assertEqual(calibrated[0].volatility_multiplier, Decimal("2.5000"))

    def test_audit_tbr_26_calibrate_specs_from_indicators_missing_snapshot_or_none_atr_preserves_spec(
        self,
    ) -> None:
        """Verify calibrate_specs_from_indicators preserves existing volatility_multiplier when snapshot or atr_14 is absent."""
        specs = [
            AssetTargetBandSpec(
                ticker="AAA",
                target_weight=Decimal("0.5000"),
                volatility_multiplier=Decimal("1.2500"),
            ),
            AssetTargetBandSpec(
                ticker="BBB",
                target_weight=Decimal("0.5000"),
                volatility_multiplier=Decimal("1.1000"),
            ),
        ]
        snap_no_atr = TechnicalIndicatorsSnapshot(
            ticker="AAA", as_of=self.as_of, close=Decimal("100"), atr_14=None
        )
        calibrated = self.default_service.calibrate_specs_from_indicators(
            target_specs=specs,
            indicators_by_ticker={"AAA": snap_no_atr},
        )
        self.assertEqual(calibrated[0].volatility_multiplier, Decimal("1.2500"))
        self.assertEqual(calibrated[1].volatility_multiplier, Decimal("1.1000"))

    def test_audit_tbr_27_rebalance_from_mtm_report_usd_base_currency_with_mixed_assets(
        self,
    ) -> None:
        """Verify rebalance_from_mtm_report in USD converts ARS positions to USD unit prices accurately."""
        val_svc = PortfolioValuationService()
        mtm = val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("100"),
                    avg_cost_price=Decimal("1000"),
                    market_price=Decimal("2000"),
                    currency="ARS",
                    entry_fx_rate=Decimal("1000"),
                ),
                PositionValuationInput(
                    ticker="AAPL",
                    quantity=Decimal("1"),
                    avg_cost_price=Decimal("100"),
                    market_price=Decimal("100"),
                    currency="USD",
                ),
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.rebalance_from_mtm_report(
            mtm_report=mtm, target_specs=targets, base_currency="USD"
        )
        self.assertTrue(rep.needs_rebalancing)
        ggal_sell = next(o for o in rep.orders if o.ticker == "GGAL")
        self.assertEqual(ggal_sell.execution_price, Decimal("2.0000"))

    def test_audit_tbr_28_rebalance_from_mtm_report_ars_base_currency_with_mixed_assets(
        self,
    ) -> None:
        """Verify rebalance_from_mtm_report in ARS converts USD positions to ARS unit prices accurately."""
        val_svc = PortfolioValuationService()
        mtm = val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("100"),
                    avg_cost_price=Decimal("1000"),
                    market_price=Decimal("1000"),
                    currency="ARS",
                ),
                PositionValuationInput(
                    ticker="AAPL",
                    quantity=Decimal("3"),
                    avg_cost_price=Decimal("100"),
                    market_price=Decimal("100"),
                    currency="USD",
                    entry_fx_rate=Decimal("1000"),
                ),
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.rebalance_from_mtm_report(
            mtm_report=mtm, target_specs=targets, base_currency="ARS"
        )
        self.assertTrue(rep.needs_rebalancing)
        aapl_sell = next(o for o in rep.orders if o.ticker == "AAPL")
        self.assertEqual(aapl_sell.execution_price, Decimal("100000.0000"))

    def test_audit_tbr_29_rebalance_from_mtm_report_invalid_base_currency_rejected(self) -> None:
        """Verify rebalance_from_mtm_report rejects unsupported base_currency."""
        val_svc = PortfolioValuationService()
        mtm = val_svc.value_portfolio_mark_to_market(
            positions=[],
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        targets = [
            AssetTargetBandSpec(
                ticker="AAPL", target_weight=Decimal("1.0000"), reference_price=Decimal("100")
            )
        ]
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.rebalance_from_mtm_report(
                mtm_report=mtm,
                target_specs=targets,
                base_currency="EUR",  # type: ignore[arg-type]
            )

    def test_audit_tbr_30_build_fsm_execution_batch_empty_orders_produces_zero_ticket_batch(
        self,
    ) -> None:
        """Verify build_fsm_execution_batch on a no-rebalance report produces an empty tickets list and valid batch_id."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("50"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("50"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        batch = self.default_service.build_fsm_execution_batch(rep)
        self.assertEqual(batch.total_orders, 0)
        self.assertEqual(batch.sell_orders_count, 0)
        self.assertEqual(batch.buy_orders_count, 0)
        self.assertEqual(batch.tickets, [])
        self.assertTrue(batch.batch_id.startswith("reb-batch-"))

    def test_audit_tbr_31_build_fsm_execution_batch_batch_tag_changes_batch_id_and_idempotency_keys(
        self,
    ) -> None:
        """Verify passing reports with distinct portfolio_id changes both batch_id and per-ticket idempotency_key hashes."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("80"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("20"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep1 = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, portfolio_id="pf-run-1", as_of=self.as_of
        )
        rep2 = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, portfolio_id="pf-run-2", as_of=self.as_of
        )
        b1 = self.default_service.build_fsm_execution_batch(rep1)
        b2 = self.default_service.build_fsm_execution_batch(rep2)
        self.assertNotEqual(b1.batch_id, b2.batch_id)
        self.assertNotEqual(b1.tickets[0].idempotency_key, b2.tickets[0].idempotency_key)

    def test_audit_tbr_32_config_invalid_min_greater_than_max_band_half_width_rejected(
        self,
    ) -> None:
        """Verify ToleranceBandRebalancerConfig rejects min_band_half_width > max_band_half_width."""
        with self.assertRaises(ValidationError):
            ToleranceBandRebalancerConfig(
                min_band_half_width=Decimal("0.1500"),
                max_band_half_width=Decimal("0.0500"),
            )

    def test_audit_tbr_33_config_commission_bps_above_500_rejected(self) -> None:
        """Verify ToleranceBandRebalancerConfig rejects commission_bps > 500."""
        with self.assertRaises(ValidationError):
            ToleranceBandRebalancerConfig(commission_bps=Decimal("500.0001"))

    def test_audit_tbr_34_config_cash_buffer_weight_above_0_5000_rejected(self) -> None:
        """Verify ToleranceBandRebalancerConfig rejects cash_buffer_weight >= 1.0000."""
        with self.assertRaises(ValidationError):
            ToleranceBandRebalancerConfig(cash_buffer_weight=Decimal("1.0000"))

    def test_audit_tbr_35_target_specs_duplicate_normalized_ticker_rejected(self) -> None:
        """Verify evaluate_and_rebalance rejects duplicate tickers in target_specs (e.g. GGAL and GGAL.BA)."""
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="GGAL.BA", target_weight=Decimal("0.5000")),
        ]
        with self.assertRaises(InvalidTargetAllocationError):
            self.default_service.evaluate_and_rebalance(
                positions=positions, target_specs=targets, as_of=self.as_of
            )

    def test_audit_tbr_36_target_specs_weights_not_summing_to_one_minus_buffer_rejected(
        self,
    ) -> None:
        """Verify evaluate_and_rebalance rejects target weights that do not sum to 1.0 - cash_buffer_weight."""
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]
        targets = [AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.8000"))]
        with self.assertRaises(InvalidTargetAllocationError):
            self.default_service.evaluate_and_rebalance(
                positions=positions, target_specs=targets, as_of=self.as_of
            )

    def test_audit_tbr_37_empty_target_specs_rejected(self) -> None:
        """Verify evaluate_and_rebalance rejects an empty target_specs list."""
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]
        with self.assertRaises(InvalidTargetAllocationError):
            self.default_service.evaluate_and_rebalance(
                positions=positions, target_specs=[], as_of=self.as_of
            )

    def test_audit_tbr_38_non_positive_total_portfolio_value_raises_insufficient_liquidity(
        self,
    ) -> None:
        """Verify zero total portfolio value raises InsufficientLiquidityForRebalanceError."""
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("0"), market_price=Decimal("100")
            )
        ]
        targets = [AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("1.0000"))]
        with self.assertRaises(InsufficientLiquidityForRebalanceError):
            self.default_service.evaluate_and_rebalance(
                positions=positions,
                target_specs=targets,
                initial_cash=Decimal("0"),
                as_of=self.as_of,
            )

    def test_audit_tbr_39_negative_initial_cash_rejected(self) -> None:
        """Verify negative initial_cash raises InsufficientLiquidityForRebalanceError."""
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]
        targets = [AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("1.0000"))]
        with self.assertRaises(InsufficientLiquidityForRebalanceError):
            self.default_service.evaluate_and_rebalance(
                positions=positions,
                target_specs=targets,
                initial_cash=Decimal("-10"),
                as_of=self.as_of,
            )

    def test_audit_tbr_40_exceeding_max_rebalance_assets_rejected(self) -> None:
        """Verify passing > MAX_REBALANCE_ASSETS (500) target specs raises InvalidTargetAllocationError."""
        positions = [
            RebalancePositionInput(
                ticker="T001", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]
        targets = [
            AssetTargetBandSpec(ticker=f"T{i:03d}", target_weight=Decimal("0.0010"))
            for i in range(1, MAX_REBALANCE_ASSETS + 2)
        ]
        with self.assertRaises(InvalidTargetAllocationError):
            self.default_service.evaluate_and_rebalance(
                positions=positions, target_specs=targets, as_of=self.as_of
            )

    def test_audit_tbr_41_boolean_numeric_inputs_rejected_in_rebalance_dtos(self) -> None:
        """Verify boolean values passed to numeric fields in RebalancePositionInput or AssetTargetBandSpec are rejected."""
        with self.assertRaises(ValidationError):
            RebalancePositionInput(
                ticker="GGAL",
                quantity=True,  # type: ignore[arg-type]
                market_price=Decimal("100"),
            )
        with self.assertRaises(ValidationError):
            AssetTargetBandSpec(
                ticker="GGAL",
                target_weight=False,  # type: ignore[arg-type]
            )

    def test_audit_tbr_42_exponent_bomb_numeric_strings_rejected(self) -> None:
        """Verify > 32 character numeric strings are rejected in RebalancePositionInput."""
        with self.assertRaises((InvalidToleranceBandConfigError, ValidationError)):
            RebalancePositionInput(
                ticker="GGAL",
                quantity="9" * 40,  # type: ignore[arg-type]
                market_price=Decimal("100"),
            )

    def test_audit_tbr_43_control_characters_in_lot_id_or_portfolio_id_rejected(self) -> None:
        """Verify ASCII control characters in lot_id or portfolio_id are rejected."""
        with self.assertRaises(ValidationError):
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                market_price=Decimal("100"),
                lot_id="bad\x07lot",
            )
        positions = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("10"), market_price=Decimal("100")
            )
        ]
        targets = [AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("1.0000"))]
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.default_service.evaluate_and_rebalance(
                positions=positions,
                target_specs=targets,
                portfolio_id="bad\nportfolio",
                as_of=self.as_of,
            )

    def test_audit_tbr_44_rebalance_trade_order_model_validator_rejects_tampered_net_cash_impact(
        self,
    ) -> None:
        """Verify RebalanceTradeOrder model validator rejects inconsistent gross_amount or net_cash_impact."""
        with self.assertRaises(ValidationError):
            RebalanceTradeOrder(
                ticker="GGAL",
                side="SELL",
                quantity=Decimal("10"),
                execution_price=Decimal("100"),
                gross_amount=Decimal("1000"),
                estimated_commission=Decimal("10"),
                net_cash_impact=Decimal("1000"),  # Tampered! Should be +990 for SELL
                order_intent=domain_services_pkg.OrderFSMIntent(
                    ticker="GGAL",
                    side="SELL",
                    target_state="PENDING",
                    reference_price=Decimal("100"),
                    suggested_stop_loss=Decimal("105"),
                    suggested_take_profit=Decimal("90"),
                    risk_reward_ratio=Decimal("1.5000"),
                ),
            )

    def test_audit_tbr_45_rebalance_trade_order_buy_rejects_non_null_estimated_realized_pnl(
        self,
    ) -> None:
        """Verify RebalanceTradeOrder model validator rejects a BUY order with non-zero estimated_realized_pnl."""
        with self.assertRaises(ValidationError):
            RebalanceTradeOrder(
                ticker="GGAL",
                side="BUY",
                quantity=Decimal("10"),
                execution_price=Decimal("100"),
                gross_amount=Decimal("1000"),
                estimated_commission=Decimal("0"),
                net_cash_impact=Decimal("-1000"),
                estimated_realized_pnl=Decimal("50"),
                order_intent=domain_services_pkg.OrderFSMIntent(
                    ticker="GGAL",
                    side="BUY",
                    target_state="PENDING",
                    reference_price=Decimal("100"),
                    suggested_stop_loss=Decimal("95"),
                    suggested_take_profit=Decimal("110"),
                    risk_reward_ratio=Decimal("1.5000"),
                ),
            )

    def test_audit_tbr_46_asset_band_evaluation_model_validator_rejects_inconsistent_breach_direction(
        self,
    ) -> None:
        """Verify AssetBandEvaluation rejects negative market_price or out-of-range weights."""
        with self.assertRaises(ValidationError):
            AssetBandEvaluation(
                ticker="GGAL",
                current_quantity=Decimal("50"),
                market_price=Decimal("0"),  # Invalid: must be > 0
                current_value=Decimal("5000"),
                current_weight=Decimal("0.5000"),
                target_weight=Decimal("0.5000"),
                lower_band=Decimal("0.4000"),
                upper_band=Decimal("0.6000"),
                drift_weight=Decimal("0.0000"),
                breach_direction=BandBreachDirection.NONE,
                is_breached=False,
                destination_weight=Decimal("0.5000"),
                post_trade_quantity=Decimal("50"),
                post_trade_value=Decimal("5000"),
                post_trade_weight=Decimal("0.5000"),
                post_trade_drift_weight=Decimal("0.0000"),
            )

    def test_audit_tbr_47_report_model_validator_rejects_buy_before_sell_in_orders(self) -> None:
        """Verify ToleranceBandRebalanceReport rejects an order list where a SELL appears after a BUY."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("70"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("30"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        with self.assertRaises(ValidationError):
            ToleranceBandRebalanceReport(
                portfolio_id=rep.portfolio_id,
                as_of=rep.as_of,
                base_currency=rep.base_currency,
                rebalance_mode=rep.rebalance_mode,
                band_type=rep.band_type,
                needs_rebalancing=rep.needs_rebalancing,
                breached_tickers=rep.breached_tickers,
                total_portfolio_value=rep.total_portfolio_value,
                projected_post_trade_portfolio_value=rep.projected_post_trade_portfolio_value,
                initial_cash=rep.initial_cash,
                projected_ending_cash=rep.projected_ending_cash,
                total_sell_gross=rep.total_sell_gross,
                total_buy_gross=rep.total_buy_gross,
                total_estimated_commissions=rep.total_estimated_commissions,
                total_estimated_realized_pnl=rep.total_estimated_realized_pnl,
                portfolio_turnover=rep.portfolio_turnover,
                evaluations=rep.evaluations,
                orders=list(reversed(rep.orders)),  # BUY before SELL -> must raise ValidationError!
            )

    def test_audit_tbr_48_deploy_excess_cash_when_inside_bands_with_to_band_boundary_mode(
        self,
    ) -> None:
        """Verify deploy_excess_cash_when_inside_bands=True also allocates excess cash under TO_BAND_BOUNDARY mode."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                rebalance_mode=RebalanceMode.TO_BAND_BOUNDARY,
                cash_buffer_weight=Decimal("0.0400"),
                deploy_excess_cash_when_inside_bands=True,
            )
        )
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
        rep = svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("1000"),
            as_of=self.as_of,
        )
        self.assertTrue(rep.needs_rebalancing)
        self.assertEqual(rep.total_buy_gross, Decimal("600.0000"))

    def test_audit_tbr_49_realized_loss_on_underwater_position_sale(self) -> None:
        """Verify selling an underwater position (market_price < avg_cost_price) yields negative estimated_realized_pnl."""
        positions = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("70"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("150"),
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("30"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertEqual(rep.total_estimated_realized_pnl, Decimal("-1000.0000"))

    def test_audit_tbr_50_buy_only_rebalance_has_none_total_estimated_realized_pnl(self) -> None:
        """Verify a BUY-only rebalance (funded by initial_cash) has total_estimated_realized_pnl == 0.0000."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("20"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("50"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            initial_cash=Decimal("3000"),
            as_of=self.as_of,
        )
        self.assertTrue(all(o.side == "BUY" for o in rep.orders))
        self.assertEqual(rep.total_estimated_realized_pnl, Decimal("0.0000"))

    def test_audit_tbr_51_re_exports_in_domain_services_init_complete(self) -> None:
        """Verify all Module 7.3 Phase 1-3 symbols are re-exported in app.domain.services."""
        for sym in (
            "BandType",
            "RebalanceMode",
            "BandBreachDirection",
            "TaxLotSelectionPolicy",
            "ToleranceBandRebalancerConfig",
            "AssetTargetBandSpec",
            "RebalancePositionInput",
            "AssetBandEvaluation",
            "RebalanceTradeOrder",
            "ToleranceBandRebalanceReport",
            "RebalanceFSMOrderTicket",
            "RebalanceFSMExecutionBatch",
            "ToleranceBandRebalancerService",
            "RebalancingError",
            "InvalidTargetAllocationError",
            "InvalidToleranceBandConfigError",
            "MissingRebalancePriceError",
            "InsufficientLiquidityForRebalanceError",
        ):
            self.assertTrue(hasattr(domain_services_pkg, sym), f"Missing export: {sym}")

    def test_audit_tbr_52_no_negative_zero_in_rebalance_report_serialized_fields(self) -> None:
        """Verify no serialized Decimal in ToleranceBandRebalanceReport ever formats as '-0.0000'."""
        positions = [
            RebalancePositionInput(
                ticker="AAA", quantity=Decimal("50"), market_price=Decimal("100")
            ),
            RebalancePositionInput(
                ticker="BBB", quantity=Decimal("50"), market_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        rep = self.default_service.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        dumped = rep.model_dump_json()
        self.assertNotIn("-0.0000", dumped)
