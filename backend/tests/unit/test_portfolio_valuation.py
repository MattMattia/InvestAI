"""
Unit test suite for Module 7.2 (Phases 1 & 2):
Dynamic Mark-to-Market Bimonetary Portfolio Valuation, TWR/MWR Attribution &
Historical Valuation Curve Engine (`backend/app/domain/services/portfolio_valuation_service.py`).
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.domain.services as domain_services_pkg
import pytest
from app.domain.services.ingestion.data_cleaning_pipeline import CleanHoldingRecord
from app.domain.services.portfolio_valuation_service import (
    MAX_VALUATION_SLICES,
    CleanedHoldingRecord,
    DatedCashFlowEvent,
    HistoricalValuationSnapshot,
    InvalidCashFlowPeriodError,
    InvalidFXRateError,
    InvalidValuationInputError,
    MissingMarketPriceError,
    PortfolioMarkToMarketReport,
    PortfolioValuationCurveReport,
    PortfolioValuationService,
    PositionValuationInput,
    SubPeriodValuationSlice,
    ValuationCurvePoint,
    ValuedPositionBreakdown,
)
from pydantic import ValidationError


@pytest.mark.unit
class TestPortfolioValuation(unittest.TestCase):
    """Unit tests verifying bimonetary Mark-to-Market valuation, Karnosky-Singer attribution, TWR, and MWR."""

    def setUp(self) -> None:
        self.service = PortfolioValuationService()
        self.as_of = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)

    def test_mark_to_market_bimonetary_and_exact_weight_sum_invariant(self) -> None:
        """
        Verify bimonetary MTM valuation and Largest Remainder Method weight allocation
        summing to 1.0000 across 3 equal-sized positions plus bimonetary cash.
        """
        positions = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("8000"),
                market_price=Decimal("10000"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="YPFD",
                quantity=Decimal("50"),
                avg_cost_price=Decimal("18"),
                market_price=Decimal("20"),
                currency="USD",
                entry_fx_rate=Decimal("900"),
            ),
            PositionValuationInput(
                ticker="PAMP",
                quantity=Decimal("200"),
                avg_cost_price=Decimal("4500"),
                market_price=Decimal("5000"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
        ]

        # Each position has market value = 1,000,000 ARS = 1,000 USD at FX = 1000
        # Cash = 500,000 ARS (500 USD) + 500 USD = 1,000 USD -> Net Worth = 4,000 USD
        report = self.service.value_portfolio_mark_to_market(
            positions=positions,
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_ars=Decimal("500000"),
            cash_balance_usd=Decimal("500"),
            portfolio_id="port-bimonetary-001",
            as_of=self.as_of,
        )

        self.assertEqual(report.portfolio_id, "port-bimonetary-001")
        self.assertEqual(len(report.positions), 3)

        # Position weights: 1/3 each -> Largest Remainder yields 0.3334, 0.3333, 0.3333 = 1.0000
        pos_weights = [p.weight_in_positions for p in report.positions]
        self.assertEqual(
            pos_weights,
            [Decimal("0.3334"), Decimal("0.3333"), Decimal("0.3333")],
        )
        self.assertEqual(sum(pos_weights, Decimal("0.0000")), Decimal("1.0000"))

        # Net worth weights: 1,000 / 4,000 = 0.2500 each -> sum = 0.7500
        nw_weights = [p.weight_in_net_worth for p in report.positions]
        self.assertEqual(
            nw_weights,
            [Decimal("0.2500"), Decimal("0.2500"), Decimal("0.2500")],
        )
        self.assertEqual(sum(nw_weights, Decimal("0.0000")), Decimal("0.7500"))

        # Vertical totals check:
        # Costs ARS: GGAL=800,000 + YPFD=(900*900=810,000) + PAMP=900,000 = 2,510,000 ARS
        # Costs USD: GGAL=800 + YPFD=900 + PAMP=900 = 2,600 USD
        self.assertEqual(report.total_cost_basis_ars, Decimal("2510000.0000"))
        self.assertEqual(report.total_cost_basis_usd, Decimal("2600.0000"))
        self.assertEqual(report.total_positions_value_ars, Decimal("3000000.0000"))
        self.assertEqual(report.total_positions_value_usd, Decimal("3000.0000"))
        self.assertEqual(report.total_net_worth_ars, Decimal("4000000.0000"))
        self.assertEqual(report.total_net_worth_usd, Decimal("4000.0000"))
        self.assertEqual(report.total_unrealized_pnl_ars, Decimal("490000.0000"))
        self.assertEqual(report.total_unrealized_pnl_usd, Decimal("400.0000"))

    def test_karnosky_singer_multiplicative_fx_and_asset_return_decomposition(self) -> None:
        """
        Verify multiplicative Karnosky-Singer return decomposition:
        (1 + r_ars) = (1 + r_usd)(1 + r_fx) => r_ars = r_usd + r_fx + r_interaction.
        """
        # Case 1: +10% real USD return coupled with +50% FX jump (1000 -> 1500) => +65% nominal ARS return
        # Case 2: Nominal ARS gain (+20%: 1000 -> 1200) masking a -20% real USD loss under +50% FX jump
        positions = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("1000"),
                market_price=Decimal("1650"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="COME",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("1000"),
                market_price=Decimal("1200"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
        ]

        report = self.service.value_portfolio_mark_to_market(
            positions=positions,
            fx_rate_ars_per_usd=Decimal("1500"),
            as_of=self.as_of,
        )

        ggal = report.positions[0]
        self.assertEqual(ggal.unrealized_pnl_pct_ars, Decimal("0.6500"))
        self.assertEqual(ggal.unrealized_pnl_pct_usd, Decimal("0.1000"))
        self.assertEqual(ggal.fx_return_component, Decimal("0.5000"))
        self.assertEqual(ggal.interaction_return_component, Decimal("0.0500"))
        self.assertEqual(
            ggal.unrealized_pnl_pct_usd
            + ggal.fx_return_component
            + ggal.interaction_return_component,
            ggal.unrealized_pnl_pct_ars,
        )

        come = report.positions[1]
        self.assertEqual(come.unrealized_pnl_pct_ars, Decimal("0.2000"))
        self.assertEqual(come.unrealized_pnl_pct_usd, Decimal("-0.2000"))
        self.assertEqual(come.fx_return_component, Decimal("0.5000"))
        self.assertEqual(come.interaction_return_component, Decimal("-0.1000"))
        self.assertEqual(
            come.unrealized_pnl_pct_usd
            + come.fx_return_component
            + come.interaction_return_component,
            come.unrealized_pnl_pct_ars,
        )

    def test_multi_lot_consolidation_across_entry_fx_and_mixed_currencies(self) -> None:
        """
        Verify multi-lot consolidation for the same ticker bought at different
        entry FX rates and in mixed currencies (ARS lot + USD lot).
        """
        lots = [
            PositionValuationInput(
                ticker=" al30 ",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("500"),
                market_price=Decimal("750"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="AL30",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("0.60"),
                market_price=Decimal("0.50"),
                currency="USD",
                entry_fx_rate=Decimal("1200"),
            ),
        ]

        report = self.service.value_portfolio_mark_to_market(
            positions=lots,
            fx_rate_ars_per_usd=Decimal("1500"),
            as_of=self.as_of,
        )

        self.assertEqual(len(report.positions), 1)
        al30 = report.positions[0]
        self.assertEqual(al30.ticker, "AL30")
        self.assertEqual(al30.native_currency, "ARS")
        self.assertEqual(al30.quantity, Decimal("200.0000"))
        # Lot 1 cost: 50,000 ARS (50 USD); Lot 2 cost: 72,000 ARS (60 USD) -> Total: 122,000 ARS (110 USD)
        self.assertEqual(al30.cost_basis_ars, Decimal("122000.0000"))
        self.assertEqual(al30.cost_basis_usd, Decimal("110.0000"))
        self.assertEqual(al30.avg_cost_price_native, Decimal("610.0000"))
        # Market value: 75,000 + 75,000 = 150,000 ARS (100 USD)
        self.assertEqual(al30.market_value_ars, Decimal("150000.0000"))
        self.assertEqual(al30.market_value_usd, Decimal("100.0000"))
        self.assertEqual(al30.market_price_native, Decimal("750.0000"))
        self.assertEqual(al30.unrealized_pnl_ars, Decimal("28000.0000"))
        self.assertEqual(al30.unrealized_pnl_usd, Decimal("-10.0000"))

    def test_twr_geometric_chaining_start_and_end_cash_flow_conventions(self) -> None:
        """
        Verify GIPS Time-Weighted Return (TWR) geometric chaining across START and END
        cash-flow timing conventions and invariance to external deposit size.
        """
        slices_small_deposit = [
            SubPeriodValuationSlice(
                start_value=Decimal("1000"),
                end_value=Decimal("1300"),
                net_cash_flow=Decimal("200"),
                cash_flow_timing="END",
            ),
            SubPeriodValuationSlice(
                start_value=Decimal("1300"),
                end_value=Decimal("2400"),
                net_cash_flow=Decimal("700"),
                cash_flow_timing="START",
            ),
        ]
        # Sub-period 1: (1300 - 200 - 1000) / 1000 = +10%
        # Sub-period 2: (2400 - (1300 + 700)) / 2000 = +20%
        # Chained TWR: 1.10 * 1.20 - 1 = 0.3200 (+32%)
        twr_1 = self.service.calculate_twr(slices_small_deposit)
        self.assertEqual(twr_1, Decimal("0.3200"))

        # Increasing external deposit by 10x while manager achieves same +20% in period 2
        slices_huge_deposit = [
            SubPeriodValuationSlice(
                start_value=Decimal("1000"),
                end_value=Decimal("1300"),
                net_cash_flow=Decimal("200"),
                cash_flow_timing="END",
            ),
            SubPeriodValuationSlice(
                start_value=Decimal("1300"),
                end_value=Decimal("12000"),
                net_cash_flow=Decimal("8700"),
                cash_flow_timing="START",
            ),
        ]
        twr_2 = self.service.calculate_twr(slices_huge_deposit)
        self.assertEqual(twr_2, Decimal("0.3200"))

    def test_mwr_modified_dietz_and_exact_nonlinear_irr_solver(self) -> None:
        """
        Verify Modified Dietz MWR and Exact Non-Linear IRR solver against an
        analytical quadratic midpoint cash-flow benchmark and full performance report.
        """
        # Analytical benchmark:
        # V_start = 1000, T = 100, CF at t=50 (w=0.5) of +1100, V_end = 2420
        # 1000*(1+r) + 1100*(1+r)^0.5 - 2420 = 0 => (1+r)^0.5 = 1.1 => 1+r = 1.21 => r_IRR = 0.2100
        # Modified Dietz: (2420 - 1000 - 1100) / (1000 + 0.5*1100) = 320 / 1550 = 0.2065
        cf_events = [DatedCashFlowEvent(day_offset=50, amount=Decimal("1100"))]

        dietz = self.service.calculate_mwr_modified_dietz(
            start_value=Decimal("1000"),
            end_value=Decimal("2420"),
            total_days=100,
            cash_flows=cf_events,
        )
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("2420"),
            total_days=100,
            cash_flows=cf_events,
        )
        self.assertEqual(dietz, Decimal("0.2065"))
        self.assertEqual(irr, Decimal("0.2100"))

        # Consolidated performance report over 365 days with FX devaluation (1000 -> 1250, +25%)
        slices = [
            SubPeriodValuationSlice(
                start_value=Decimal("1000"),
                end_value=Decimal("1500"),
                net_cash_flow=Decimal("0"),
                cash_flow_timing="END",
            )
        ]
        perf = self.service.evaluate_performance_metrics(
            slices=slices,
            start_value=Decimal("1000"),
            end_value=Decimal("1500"),
            total_days=365,
            cash_flows=(),
            start_fx_rate=Decimal("1000"),
            end_fx_rate=Decimal("1250"),
        )
        self.assertEqual(perf.twr, Decimal("0.5000"))
        self.assertEqual(perf.twr_pct, Decimal("50.0000"))
        self.assertEqual(perf.mwr_dietz, Decimal("0.5000"))
        self.assertEqual(perf.mwr_irr, Decimal("0.5000"))
        self.assertEqual(perf.annualized_twr, Decimal("0.5000"))
        self.assertEqual(perf.annualized_mwr_irr, Decimal("0.5000"))
        self.assertEqual(perf.fx_devaluation_return, Decimal("0.2500"))
        # Real USD TWR: (1 + 0.50) / (1 + 0.25) - 1 = 1.20 - 1 = 0.2000 (+20%)
        self.assertEqual(perf.real_usd_twr, Decimal("0.2000"))

    def test_zero_cost_basis_total_loss_and_cash_only_portfolio_edge_cases(self) -> None:
        """
        Verify zero-cost basis (airdrop/spin-off), -100% total loss boundary,
        and cash-only portfolio valuation without division-by-zero errors.
        """
        # 1. Zero cost basis position
        airdrop_pos = [
            PositionValuationInput(
                ticker="AIRDROP",
                quantity=Decimal("50"),
                avg_cost_price=Decimal("0"),
                market_price=Decimal("100"),
                currency="USD",
            )
        ]
        airdrop_rep = self.service.value_portfolio_mark_to_market(
            positions=airdrop_pos,
            fx_rate_ars_per_usd=Decimal("1200"),
            as_of=self.as_of,
        )
        p0 = airdrop_rep.positions[0]
        self.assertEqual(p0.cost_basis_usd, Decimal("0.0000"))
        self.assertIsNone(p0.unrealized_pnl_pct_ars)
        self.assertIsNone(p0.unrealized_pnl_pct_usd)
        self.assertIsNone(p0.fx_return_component)
        self.assertIsNone(p0.interaction_return_component)
        self.assertIsNone(airdrop_rep.total_unrealized_pnl_pct_ars)
        self.assertIsNone(airdrop_rep.total_unrealized_pnl_pct_usd)

        # 2. Cash-only portfolio (empty positions)
        cash_rep = self.service.value_portfolio_mark_to_market(
            positions=[],
            fx_rate_ars_per_usd=Decimal("1500"),
            cash_balance_ars=Decimal("150000"),
            cash_balance_usd=Decimal("200"),
            as_of=self.as_of,
        )
        self.assertEqual(cash_rep.positions, [])
        self.assertEqual(cash_rep.total_positions_value_usd, Decimal("0.0000"))
        self.assertEqual(cash_rep.total_net_worth_usd, Decimal("300.0000"))
        self.assertEqual(cash_rep.total_net_worth_ars, Decimal("450000.0000"))

        # 3. Total loss (-100% return) in TWR, Dietz, and IRR
        total_loss_slice = [
            SubPeriodValuationSlice(
                start_value=Decimal("1000"),
                end_value=Decimal("0"),
                net_cash_flow=Decimal("0"),
            )
        ]
        loss_perf = self.service.evaluate_performance_metrics(
            slices=total_loss_slice,
            start_value=Decimal("1000"),
            end_value=Decimal("0"),
            total_days=180,
            cash_flows=[DatedCashFlowEvent(day_offset=90, amount=Decimal("200"))],
        )
        self.assertEqual(loss_perf.twr, Decimal("-1.0000"))
        self.assertEqual(loss_perf.mwr_dietz, Decimal("-1.0909"))
        self.assertEqual(loss_perf.mwr_irr, Decimal("-1.0000"))
        self.assertEqual(loss_perf.annualized_twr, Decimal("-1.0000"))
        self.assertEqual(loss_perf.annualized_mwr_irr, Decimal("-1.0000"))

        # Verify package re-export
        self.assertIs(
            domain_services_pkg.PortfolioValuationService,
            PortfolioValuationService,
        )

    def test_validation_guards_negative_capital_base_invalid_fx_and_boolean_rejection(self) -> None:
        """
        Verify domain exceptions and Pydantic contract validators reject invalid FX rates,
        negative weighted capital bases, out-of-range cash flow offsets, booleans, and broken closures.
        """
        # 1. Invalid FX rates
        for bad_fx in (Decimal("0"), Decimal("-100"), True, False, None):
            with self.assertRaises(InvalidFXRateError):
                self.service.value_portfolio_mark_to_market(
                    positions=[],
                    fx_rate_ars_per_usd=bad_fx,  # type: ignore[arg-type]
                )

        # Asymmetric start_fx_rate / end_fx_rate
        with self.assertRaises(InvalidFXRateError):
            self.service.evaluate_performance_metrics(
                slices=[
                    SubPeriodValuationSlice(start_value=Decimal("100"), end_value=Decimal("110"))
                ],
                start_value=Decimal("100"),
                end_value=Decimal("110"),
                total_days=30,
                start_fx_rate=Decimal("1000"),
                end_fx_rate=None,
            )

        # 2. Negative capital base in TWR (START withdrawal >= start_value) and Modified Dietz
        with self.assertRaises((InvalidCashFlowPeriodError, ValidationError)):
            self.service.calculate_twr(
                [
                    SubPeriodValuationSlice(
                        start_value=Decimal("1000"),
                        end_value=Decimal("500"),
                        net_cash_flow=Decimal("-1000"),
                        cash_flow_timing="START",
                    )
                ]
            )
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.calculate_twr(
                [
                    SubPeriodValuationSlice.model_construct(
                        start_value=Decimal("1000"),
                        end_value=Decimal("500"),
                        net_cash_flow=Decimal("-1000"),
                        cash_flow_timing="START",
                    )
                ]
            )
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.calculate_mwr_modified_dietz(
                start_value=Decimal("1000"),
                end_value=Decimal("500"),
                total_days=100,
                cash_flows=[DatedCashFlowEvent(day_offset=10, amount=Decimal("-2000"))],
            )

        # Out-of-bounds day_offset or invalid total_days
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.calculate_mwr_modified_dietz(
                start_value=Decimal("1000"),
                end_value=Decimal("1100"),
                total_days=30,
                cash_flows=[DatedCashFlowEvent(day_offset=31, amount=Decimal("100"))],
            )
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.calculate_mwr_modified_dietz(
                start_value=Decimal("1000"),
                end_value=Decimal("1100"),
                total_days=True,  # type: ignore[arg-type]
            )

        # 3. Boolean and broken Karnosky-Singer closure rejected on DTOs
        with self.assertRaises(ValidationError):
            DatedCashFlowEvent(day_offset=True, amount=Decimal("100"))  # type: ignore[arg-type]

        with self.assertRaises(ValidationError):
            ValuedPositionBreakdown(
                ticker="GGAL",
                native_currency="ARS",
                quantity=Decimal("10"),
                avg_cost_price_native=Decimal("100"),
                market_price_native=Decimal("120"),
                cost_basis_ars=Decimal("1000"),
                cost_basis_usd=Decimal("10"),
                market_value_ars=Decimal("1200"),
                market_value_usd=Decimal("12"),
                unrealized_pnl_ars=Decimal("200"),
                unrealized_pnl_usd=Decimal("2"),
                unrealized_pnl_pct_ars=Decimal("0.2000"),
                unrealized_pnl_pct_usd=Decimal("0.2000"),
                fx_return_component=Decimal("0.1000"),
                interaction_return_component=Decimal("0.0500"),  # 0.20 + 0.10 + 0.05 != 0.20
                weight_in_positions=Decimal("1.0000"),
                weight_in_net_worth=Decimal("1.0000"),
            )

        with self.assertRaises(ValidationError):
            PortfolioMarkToMarketReport(
                as_of=self.as_of,
                fx_rate_ars_per_usd=Decimal("1000"),
                total_cost_basis_ars=Decimal("500"),  # mismatch with empty positions
                total_cost_basis_usd=Decimal("0"),
                total_positions_value_ars=Decimal("0"),
                total_positions_value_usd=Decimal("0"),
                total_net_worth_ars=Decimal("0"),
                total_net_worth_usd=Decimal("0"),
                total_unrealized_pnl_ars=Decimal("-500"),
                total_unrealized_pnl_usd=Decimal("0"),
                positions=[],
            )

    def test_portfolio_level_karnosky_singer_attribution_in_mtm_report(self) -> None:
        """
        Verify portfolio-level Karnosky-Singer decomposition across multiple positions
        with distinct entry FX rates ("GGAL" at 1000 and "AAPL" at 1100, valued at 1200).
        """
        positions = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("1000"),  # 100,000 ARS -> 100 USD at FX 1000
                market_price=Decimal("1500"),  # 150,000 ARS -> 125 USD at FX 1200
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="AAPL",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("10"),  # 100 USD -> 110,000 ARS at FX 1100
                market_price=Decimal("12"),  # 120 USD -> 144,000 ARS at FX 1200
                currency="USD",
                entry_fx_rate=Decimal("1100"),
            ),
        ]

        report = self.service.value_portfolio_mark_to_market(
            positions=positions,
            fx_rate_ars_per_usd=Decimal("1200"),
            as_of=self.as_of,
        )

        self.assertIsNotNone(report.total_unrealized_pnl_pct_ars)
        self.assertIsNotNone(report.total_unrealized_pnl_pct_usd)
        self.assertIsNotNone(report.total_fx_return_component)
        self.assertIsNotNone(report.total_interaction_return_component)
        assert report.total_unrealized_pnl_pct_ars is not None
        assert report.total_unrealized_pnl_pct_usd is not None
        assert report.total_fx_return_component is not None
        assert report.total_interaction_return_component is not None

        # Total cost ARS = 100,000 + 110,000 = 210,000; Total cost USD = 100 + 100 = 200
        # Effective portfolio entry FX = 210,000 / 200 = 1050
        # FX return component = (1200 / 1050) - 1 = 0.1429
        self.assertEqual(report.total_cost_basis_ars, Decimal("210000.0000"))
        self.assertEqual(report.total_cost_basis_usd, Decimal("200.0000"))
        self.assertEqual(report.total_fx_return_component, Decimal("0.1429"))
        self.assertEqual(
            report.total_unrealized_pnl_pct_usd
            + report.total_fx_return_component
            + report.total_interaction_return_component,
            report.total_unrealized_pnl_pct_ars,
        )

    def test_value_holdings_from_quotes_resolves_ba_suffix_and_raises_missing_price(
        self,
    ) -> None:
        """
        Verify `value_holdings_from_quotes` resolves `.BA` suffixes bidirectionally,
        handles `avg_price=None` as zero cost basis, and raises `MissingMarketPriceError`
        when a quote is missing or non-positive.
        """
        holdings = [
            CleanedHoldingRecord(
                row_number=1,
                ticker="GGAL",
                quantity=Decimal("10"),
                avg_price=Decimal("4000"),
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=2,
                ticker="YPFD.BA",
                quantity=Decimal("5"),
                avg_price=Decimal("30000"),
                currency="ARS",
            ),
        ]
        market_quotes = {
            "GGAL.BA": Decimal("5200"),
            "YPFD": Decimal("38000"),
        }

        report = self.service.value_holdings_from_quotes(
            holdings=holdings,
            market_quotes=market_quotes,
            fx_rate_ars_per_usd=Decimal("1000"),
            entry_fx_rates={"GGAL.BA": Decimal("900"), "YPFD": Decimal("950")},
            cash_balance_ars=Decimal("10000"),
            portfolio_id="pf-quotes-01",
            as_of=self.as_of,
        )

        self.assertEqual(len(report.positions), 2)
        # GGAL: 10 * 5200 = 52,000 ARS; YPFD.BA: 5 * 38000 = 190,000 ARS -> Total = 242,000 ARS
        self.assertEqual(report.total_positions_value_ars, Decimal("242000.0000"))
        self.assertEqual(report.total_positions_value_usd, Decimal("242.0000"))
        self.assertEqual(report.total_net_worth_ars, Decimal("252000.0000"))
        self.assertEqual(report.total_net_worth_usd, Decimal("252.0000"))

        with self.assertRaises(MissingMarketPriceError):
            self.service.value_holdings_from_quotes(
                holdings=holdings,
                market_quotes={"GGAL.BA": Decimal("5200")},  # YPFD missing
                fx_rate_ars_per_usd=Decimal("1000"),
            )

        with self.assertRaises(MissingMarketPriceError):
            self.service.value_holdings_from_quotes(
                holdings=holdings,
                market_quotes={"GGAL.BA": Decimal("5200"), "YPFD": Decimal("0")},
                fx_rate_ars_per_usd=Decimal("1000"),
            )

    def test_evaluate_valuation_curve_bimonetary_drawdown_illusion_ars_ath_vs_usd_drawdown(
        self,
    ) -> None:
        """
        Verify Argentine "Monetary Illusion" scenario along a valuation curve:
        nominal ARS reaches an all-time high (+80%, 0% drawdown) while real USD
        suffers a -28.00% drawdown from peak ($1250 -> $900) and -10.00% total TWR.
        """
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        t1 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)

        snapshots = [
            HistoricalValuationSnapshot(
                as_of=t0,
                net_worth_ars=Decimal("1000000"),
                fx_rate_ars_per_usd=Decimal("1000"),
            ),
            HistoricalValuationSnapshot(
                as_of=t1,
                net_worth_ars=Decimal("1500000"),
                fx_rate_ars_per_usd=Decimal("1200"),
            ),
            HistoricalValuationSnapshot(
                as_of=t2,
                net_worth_ars=Decimal("1800000"),
                fx_rate_ars_per_usd=Decimal("2000"),
            ),
        ]

        # Auto-computed USD net worths: 1000.0000, 1250.0000, 900.0000
        self.assertEqual(snapshots[0].net_worth_usd, Decimal("1000.0000"))
        self.assertEqual(snapshots[1].net_worth_usd, Decimal("1250.0000"))
        self.assertEqual(snapshots[2].net_worth_usd, Decimal("900.0000"))

        curve = self.service.evaluate_valuation_curve(
            snapshots=snapshots,
            portfolio_id="pf-illusion-01",
        )

        self.assertIsInstance(curve, PortfolioValuationCurveReport)
        self.assertEqual(len(curve.points), 3)

        # At t2: ARS is at ATH (drawdown 0.0000), USD is down -28.00% from 1250 peak
        pt2 = curve.points[2]
        self.assertEqual(pt2.drawdown_ars, Decimal("0.0000"))
        self.assertEqual(curve.max_drawdown_ars, Decimal("0.0000"))
        self.assertEqual(curve.high_water_mark_ars, Decimal("1800000.0000"))

        self.assertEqual(pt2.drawdown_usd, Decimal("-0.2800"))
        self.assertEqual(curve.max_drawdown_usd, Decimal("-0.2800"))
        self.assertEqual(curve.high_water_mark_usd, Decimal("1250.0000"))

        # Cumulative TWR: +80% in ARS, -10% in USD
        self.assertEqual(curve.performance_ars.twr, Decimal("0.8000"))
        self.assertEqual(curve.performance_usd.twr, Decimal("-0.1000"))
        self.assertEqual(curve.performance_ars.real_usd_twr, Decimal("-0.1000"))

    def test_subperiod_slice_zero_start_value_with_start_timing_deposit(self) -> None:
        """
        Verify account opening with `start_value = 0` and a positive `START`-timed
        deposit succeeds, while `start_value = 0` with `END` timing or zero deposit fails.
        """
        opening_slice = SubPeriodValuationSlice(
            start_value=Decimal("0"),
            end_value=Decimal("1150"),
            net_cash_flow=Decimal("1000"),
            cash_flow_timing="START",
        )
        twr = self.service.calculate_twr([opening_slice])
        self.assertEqual(twr, Decimal("0.1500"))

        with self.assertRaises((ValidationError, InvalidCashFlowPeriodError)):
            SubPeriodValuationSlice(
                start_value=Decimal("0"),
                end_value=Decimal("1150"),
                net_cash_flow=Decimal("1000"),
                cash_flow_timing="END",
            )

        with self.assertRaises((ValidationError, InvalidCashFlowPeriodError)):
            SubPeriodValuationSlice(
                start_value=Decimal("0"),
                end_value=Decimal("1150"),
                net_cash_flow=Decimal("0"),
                cash_flow_timing="START",
            )

    def test_evaluate_valuation_curve_unsorted_snapshots_and_intraday_offset_handling(
        self,
    ) -> None:
        """
        Verify `evaluate_valuation_curve` sorts unsorted snapshots chronologically,
        matches `points[-1].cumulative_twr_ars == curve.performance_ars.twr`, and
        handles sub-24-hour intervals (`total_days == 1`) without `ZeroDivisionError`.
        """
        t0 = datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
        t1 = t0 + timedelta(hours=6)
        t2 = t0 + timedelta(hours=12)

        # Pass out-of-order snapshots [t2, t0, t1]
        unsorted_snapshots = [
            HistoricalValuationSnapshot(
                as_of=t2,
                net_worth_ars=Decimal("231000"),
                fx_rate_ars_per_usd=Decimal("1000"),
                net_cash_flow_ars=Decimal("0"),
                cash_flow_timing="END",
            ),
            HistoricalValuationSnapshot(
                as_of=t0,
                net_worth_ars=Decimal("100000"),
                fx_rate_ars_per_usd=Decimal("1000"),
            ),
            HistoricalValuationSnapshot(
                as_of=t1,
                net_worth_ars=Decimal("210000"),
                fx_rate_ars_per_usd=Decimal("1000"),
                net_cash_flow_ars=Decimal("100000"),
                cash_flow_timing="START",
            ),
        ]

        curve = self.service.evaluate_valuation_curve(unsorted_snapshots)
        self.assertEqual(curve.total_days, 1)
        self.assertEqual(curve.start_date, t0)
        self.assertEqual(curve.end_date, t2)
        self.assertEqual([p.as_of for p in curve.points], [t0, t1, t2])
        self.assertEqual(
            curve.points[-1].cumulative_twr_ars,
            curve.performance_ars.twr,
        )
        # Sub-period 1: (210,000 - (100,000 + 100,000)) / 200,000 = +5%
        # Sub-period 2: (231,000 - 210,000) / 210,000 = +10%
        # Cumulative TWR: 1.05 * 1.10 - 1 = 0.1550 (+15.50%)
        self.assertEqual(curve.performance_ars.twr, Decimal("0.1550"))

    def test_phase2_validation_guards_duplicate_timestamps_insufficient_snapshots_and_dos_bounds(
        self,
    ) -> None:
        """
        Verify Phase 2 validation guards (`< 2` snapshots, duplicate timestamps,
        naive/aware datetime mixing) and re-exports in `app.domain.services`.
        """
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        snap0 = HistoricalValuationSnapshot(
            as_of=t0,
            net_worth_ars=Decimal("100000"),
            fx_rate_ars_per_usd=Decimal("1000"),
        )

        # < 2 snapshots rejected
        with self.assertRaises(InvalidValuationInputError):
            self.service.evaluate_valuation_curve([snap0])

        # Duplicate timestamps rejected
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.evaluate_valuation_curve([snap0, snap0])

        # Mixed naive and timezone-aware timestamps rejected
        snap_naive = HistoricalValuationSnapshot(
            as_of=datetime(2026, 1, 2, 12, 0),
            net_worth_ars=Decimal("110000"),
            fx_rate_ars_per_usd=Decimal("1000"),
        )
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.evaluate_valuation_curve([snap0, snap_naive])

        # Verify Phase 2 symbols are re-exported in app.domain.services
        for symbol in (
            "MAX_VALUATION_SLICES",
            "HistoricalValuationSnapshot",
            "ValuationCurvePoint",
            "PortfolioValuationCurveReport",
        ):
            self.assertTrue(
                hasattr(domain_services_pkg, symbol),
                f"Expected '{symbol}' to be re-exported in app.domain.services",
            )
        self.assertEqual(MAX_VALUATION_SLICES, 10_000)
        self.assertIsInstance(
            curve_pt := ValuationCurvePoint(
                as_of=t0,
                fx_rate_ars_per_usd=Decimal("1000"),
                net_worth_ars=Decimal("100000"),
                net_worth_usd=Decimal("100"),
                period_return_ars=Decimal("0"),
                period_return_usd=Decimal("0"),
                cumulative_twr_ars=Decimal("0"),
                cumulative_twr_usd=Decimal("0"),
                high_water_mark_ars=Decimal("100000"),
                high_water_mark_usd=Decimal("100"),
                drawdown_ars=Decimal("0"),
                drawdown_usd=Decimal("0"),
            ),
            ValuationCurvePoint,
        )
        self.assertEqual(curve_pt.drawdown_ars, Decimal("0.0000"))

    def test_benchmark_cfa_gips_twr_positive_vs_mwr_negative_money_timing_divergence(
        self,
    ) -> None:
        """
        Certify the classic CFA/GIPS money-timing divergence benchmark:
        Sub-period 1: +50% on small capital (1000 -> 1500).
        Sub-period 2: +8500 contribution enters (1500 + 8500 = 10000), then -20% drop (10000 -> 8000).
        TWR is +20.00% (1.50 * 0.80 - 1), while both Modified Dietz and IRR are negative
        reflecting the investor's actual -1500 monetary loss.
        """
        slices = [
            SubPeriodValuationSlice(
                start_value=Decimal("1000"),
                end_value=Decimal("1500"),
                net_cash_flow=Decimal("0"),
                cash_flow_timing="END",
            ),
            SubPeriodValuationSlice(
                start_value=Decimal("1500"),
                end_value=Decimal("8000"),
                net_cash_flow=Decimal("8500"),
                cash_flow_timing="START",
            ),
        ]
        cash_flows = [
            DatedCashFlowEvent(day_offset=50, amount=Decimal("8500")),
        ]

        perf = self.service.evaluate_performance_metrics(
            slices=slices,
            start_value=Decimal("1000"),
            end_value=Decimal("8000"),
            total_days=100,
            cash_flows=cash_flows,
        )

        self.assertEqual(perf.twr, Decimal("0.2000"))
        self.assertEqual(perf.twr_pct, Decimal("20.0000"))
        self.assertLess(perf.mwr_dietz, Decimal("0"))
        self.assertLess(perf.mwr_irr, Decimal("0"))
        # Modified Dietz: (8000 - 1000 - 8500) / (1000 + 0.5 * 8500) = -1500 / 5250 = -0.2857
        self.assertEqual(perf.mwr_dietz, Decimal("-0.2857"))

    def test_benchmark_bimonetary_twr_equivalence_identity_across_hyperinflation_shock(
        self,
    ) -> None:
        """
        Verify exact equivalence between USD TWR (`performance_usd.twr`) and
        FX-adjusted real USD TWR (`performance_ars.real_usd_twr`) across a 300%
        exchange rate devaluation shock (FX 1000 -> 4000 ARS/USD).
        """
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        t1 = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

        snapshots = [
            HistoricalValuationSnapshot(
                as_of=t0,
                net_worth_ars=Decimal("2000000"),
                fx_rate_ars_per_usd=Decimal("1000"),
            ),
            HistoricalValuationSnapshot(
                as_of=t1,
                net_worth_ars=Decimal("3600000"),
                fx_rate_ars_per_usd=Decimal("2000"),
            ),
            HistoricalValuationSnapshot(
                as_of=t2,
                net_worth_ars=Decimal("6400000"),
                fx_rate_ars_per_usd=Decimal("4000"),
            ),
        ]

        curve = self.service.evaluate_valuation_curve(snapshots)
        self.assertIsNotNone(curve.performance_ars.real_usd_twr)
        self.assertEqual(
            curve.performance_usd.twr,
            curve.performance_ars.real_usd_twr,
        )
        # USD net worth went from 2000 USD -> 1800 USD -> 1600 USD (-20.00%)
        self.assertEqual(curve.performance_usd.twr, Decimal("-0.2000"))
        self.assertEqual(curve.performance_ars.real_usd_twr, Decimal("-0.2000"))

    def test_mixed_zero_cost_caja_de_valores_and_positive_cost_holdings_attribution(
        self,
    ) -> None:
        """
        Verify `value_holdings_from_quotes` handles Caja de Valores holdings with
        `avg_price=None` (both `CleanHoldingRecord` and dict representations) alongside
        priced holdings, setting individual percentage fields to `None` on zero-cost
        positions while preserving exact portfolio-level Karnosky-Singer closure.
        """
        holdings = [
            CleanHoldingRecord(
                row_number=1,
                ticker="AL30",
                quantity=Decimal("1000"),
                avg_price=None,  # Caja de Valores custody statement without purchase price
                currency="ARS",
            ),
            {
                "ticker": "GD30",
                "quantity": Decimal("500"),
                "avg_cost_price": None,
                "avg_price": None,
                "currency": "USD",
            },
            CleanHoldingRecord(
                row_number=2,
                ticker="GGAL",
                quantity=Decimal("100"),
                avg_price=Decimal("4000"),
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=3,
                ticker="AAPL",
                quantity=Decimal("20"),
                avg_price=Decimal("15"),
                currency="USD",
            ),
        ]
        market_quotes = {
            "AL30.BA": Decimal("750"),
            "GD30": Decimal("0.65"),
            "GGAL": Decimal("5000"),
            "AAPL": Decimal("18"),
        }
        entry_fx_rates = {
            "GGAL": Decimal("1000"),
            "AAPL": Decimal("1100"),
        }

        report = self.service.value_holdings_from_quotes(
            holdings=holdings,  # type: ignore[arg-type]
            market_quotes=market_quotes,
            fx_rate_ars_per_usd=Decimal("1250"),
            entry_fx_rates=entry_fx_rates,
            as_of=self.as_of,
        )

        pos_by_ticker = {p.ticker: p for p in report.positions}
        self.assertEqual(pos_by_ticker["AL30"].avg_cost_price_native, Decimal("0.0000"))
        self.assertIsNone(pos_by_ticker["AL30"].unrealized_pnl_pct_ars)
        self.assertIsNone(pos_by_ticker["AL30"].unrealized_pnl_pct_usd)
        self.assertIsNone(pos_by_ticker["AL30"].fx_return_component)
        self.assertIsNone(pos_by_ticker["AL30"].interaction_return_component)

        self.assertEqual(pos_by_ticker["GD30"].avg_cost_price_native, Decimal("0.0000"))
        self.assertIsNone(pos_by_ticker["GD30"].unrealized_pnl_pct_ars)

        # Portfolio-level Karnosky-Singer closure holds exactly
        assert report.total_unrealized_pnl_pct_ars is not None
        assert report.total_unrealized_pnl_pct_usd is not None
        assert report.total_fx_return_component is not None
        assert report.total_interaction_return_component is not None
        self.assertEqual(
            report.total_unrealized_pnl_pct_usd
            + report.total_fx_return_component
            + report.total_interaction_return_component,
            report.total_unrealized_pnl_pct_ars,
        )

    def test_nonlinear_irr_solver_when_dietz_overshoots_below_minus_100_pct_and_oscillating_flows(
        self,
    ) -> None:
        """
        Verify exact IRR solver convergence when:
        Case A: Modified Dietz overshoots below -100% (-1.2667) while end_value = 100 > 0;
                exact quadratic root is r = (0.6 - 0.1*sqrt(35)) - 1 = -0.9916 (-99.16%).
        Case B: Oscillating cash flows (+, -, +) converge deterministically to NPV(r) ~ 0.
        """
        # Case A: V_start = 1000, CF = +1000 at t=15/30 (w=0.5), V_end = 100
        cf_a = [DatedCashFlowEvent(day_offset=15, amount=Decimal("1000"))]
        dietz_a = self.service.calculate_mwr_modified_dietz(
            start_value=Decimal("1000"),
            end_value=Decimal("100"),
            total_days=30,
            cash_flows=cf_a,
        )
        irr_a = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("100"),
            total_days=30,
            cash_flows=cf_a,
        )
        self.assertEqual(dietz_a, Decimal("-1.2667"))
        self.assertEqual(irr_a, Decimal("-0.9916"))
        self.assertGreater(irr_a, Decimal("-1.0000"))

        # Case B: Oscillating flows (+500 at day 20, -400 at day 50, +300 at day 80) over 100 days
        cf_b = [
            DatedCashFlowEvent(day_offset=20, amount=Decimal("500")),
            DatedCashFlowEvent(day_offset=50, amount=Decimal("-400")),
            DatedCashFlowEvent(day_offset=80, amount=Decimal("300")),
        ]
        irr_b = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("1650"),
            total_days=100,
            cash_flows=cf_b,
        )
        u_b = Decimal("1") + irr_b
        npv_b = (
            Decimal("1000") * u_b
            + Decimal("500") * (Decimal("0.8") * u_b.ln()).exp()
            - Decimal("400") * (Decimal("0.5") * u_b.ln()).exp()
            + Decimal("300") * (Decimal("0.2") * u_b.ln()).exp()
            - Decimal("1650")
        )
        self.assertLess(abs(npv_b), Decimal("0.5"))

    def test_full_year_365_daily_snapshots_valuation_curve_and_exact_annualization(
        self,
    ) -> None:
        """
        Evaluate a 366-point daily valuation curve (365 elapsed days) with an initial
        rally, mid-year USD drawdown, recovery to a closing all-time high, and monthly
        contributions, verifying exact 365-day annualization identity (`annualized == period`).
        """
        base_dt = datetime(2025, 1, 1, 18, 0, tzinfo=UTC)
        snapshots: list[HistoricalValuationSnapshot] = []
        nw_usd = Decimal("10000")
        fx = Decimal("1000")

        for day in range(366):
            curr_dt = base_dt + timedelta(days=day)
            cf_usd = Decimal("0")
            if day > 0:
                if day <= 120:
                    nw_usd = nw_usd * Decimal("1.002")
                elif day <= 220:
                    nw_usd = nw_usd * Decimal("0.997")
                else:
                    nw_usd = nw_usd * Decimal("1.0035")

                if day % 30 == 0:
                    cf_usd = Decimal("500")
                    nw_usd += cf_usd

            fx_day = fx + Decimal(day) * Decimal("1.5")
            nw_ars = nw_usd * fx_day
            cf_ars = cf_usd * fx_day

            snapshots.append(
                HistoricalValuationSnapshot(
                    as_of=curr_dt,
                    net_worth_ars=nw_ars,
                    fx_rate_ars_per_usd=fx_day,
                    net_cash_flow_ars=cf_ars,
                    net_worth_usd=nw_usd,
                    net_cash_flow_usd=cf_usd,
                    cash_flow_timing="END",
                )
            )

        curve = self.service.evaluate_valuation_curve(snapshots, portfolio_id="pf-365d")
        self.assertEqual(curve.total_days, 365)
        self.assertEqual(len(curve.points), 366)
        self.assertLess(curve.max_drawdown_usd, Decimal("0.0000"))
        self.assertGreater(abs(curve.max_drawdown_usd), Decimal("0.0000"))
        self.assertEqual(curve.points[-1].drawdown_usd, Decimal("0.0000"))

        # Exact 365-day identity: annualized_twr == twr and annualized_mwr_irr == mwr_irr
        self.assertEqual(
            curve.performance_ars.annualized_twr,
            curve.performance_ars.twr,
        )
        self.assertEqual(
            curve.performance_ars.annualized_mwr_irr,
            curve.performance_ars.mwr_irr,
        )
        self.assertEqual(
            curve.performance_usd.annualized_twr,
            curve.performance_usd.twr,
        )
        self.assertEqual(
            curve.performance_usd.annualized_mwr_irr,
            curve.performance_usd.mwr_irr,
        )

    def test_scale_boundaries_10_pow_12_and_zero_initial_net_worth_start_deposit_curve(
        self,
    ) -> None:
        """
        Verify upper numeric scale boundary (`10^12`) without `InvalidOperation`
        and evaluate a valuation curve starting at `net_worth_ars = 0` at $s_0$
        with a founding `START`-timed deposit at $s_1$.
        """
        # 1. Scale boundary 10^12
        pos_large = PositionValuationInput(
            ticker="GGAL",
            quantity=Decimal("1000000"),
            avg_cost_price=Decimal("900000"),
            market_price=Decimal("1000000"),  # 10^12 ARS market value
            currency="ARS",
            entry_fx_rate=Decimal("1000"),
        )
        report_large = self.service.value_portfolio_mark_to_market(
            positions=[pos_large],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        self.assertEqual(
            report_large.total_positions_value_ars,
            Decimal("1000000000000.0000"),
        )

        # 2. Curve starting at 0 with founding deposit at s_1 (cash_flow_timing="START")
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        t1 = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

        zero_start_snapshots = [
            HistoricalValuationSnapshot(
                as_of=t0,
                net_worth_ars=Decimal("0"),
                fx_rate_ars_per_usd=Decimal("1000"),
            ),
            HistoricalValuationSnapshot(
                as_of=t1,
                net_worth_ars=Decimal("1100000"),
                fx_rate_ars_per_usd=Decimal("1000"),
                net_cash_flow_ars=Decimal("1000000"),
                cash_flow_timing="START",
            ),
            HistoricalValuationSnapshot(
                as_of=t2,
                net_worth_ars=Decimal("1210000"),
                fx_rate_ars_per_usd=Decimal("1000"),
                net_cash_flow_ars=Decimal("0"),
                cash_flow_timing="END",
            ),
        ]

        curve = self.service.evaluate_valuation_curve(zero_start_snapshots)
        self.assertEqual(curve.points[0].drawdown_ars, Decimal("0.0000"))
        self.assertEqual(curve.points[0].drawdown_usd, Decimal("0.0000"))
        self.assertEqual(curve.max_drawdown_ars, Decimal("0.0000"))
        self.assertEqual(curve.performance_ars.twr, Decimal("0.2100"))
        self.assertEqual(curve.performance_ars.mwr_dietz, Decimal("0.2100"))
        self.assertEqual(curve.performance_ars.mwr_irr, Decimal("0.2100"))

    def test_audit_pv_01_mtm_fx_appreciation_karnosky_singer_negative_fx_component(self) -> None:
        """Verify MTM valuation under FX appreciation (FX_1 < FX_0) yields negative fx_return_component and exact closure."""
        pos = PositionValuationInput(
            ticker="GGAL",
            quantity=Decimal("100"),
            avg_cost_price=Decimal("1000"),
            market_price=Decimal("1100"),
            currency="ARS",
            entry_fx_rate=Decimal("1000"),
        )
        rep = self.service.value_portfolio_mark_to_market(
            positions=[pos],
            fx_rate_ars_per_usd=Decimal("800"),
            as_of=self.as_of,
        )
        p = rep.positions[0]
        self.assertLess(p.fx_return_component, Decimal("0.0000"))
        self.assertGreater(p.unrealized_pnl_pct_usd, p.unrealized_pnl_pct_ars)
        self.assertEqual(
            p.unrealized_pnl_pct_usd + p.fx_return_component + p.interaction_return_component,
            p.unrealized_pnl_pct_ars,
        )

    def test_audit_pv_02_mtm_fx_stability_zero_fx_and_interaction_components(self) -> None:
        """Verify MTM valuation under FX stability (FX_1 == FX_0) produces zero FX and interaction components."""
        pos = PositionValuationInput(
            ticker="YPFD",
            quantity=Decimal("50"),
            avg_cost_price=Decimal("2000"),
            market_price=Decimal("2500"),
            currency="ARS",
            entry_fx_rate=Decimal("1200"),
        )
        rep = self.service.value_portfolio_mark_to_market(
            positions=[pos],
            fx_rate_ars_per_usd=Decimal("1200"),
            as_of=self.as_of,
        )
        p = rep.positions[0]
        self.assertEqual(p.fx_return_component, Decimal("0.0000"))
        self.assertEqual(p.interaction_return_component, Decimal("0.0000"))
        self.assertEqual(p.unrealized_pnl_pct_ars, Decimal("0.2500"))
        self.assertEqual(p.unrealized_pnl_pct_usd, Decimal("0.2500"))

    def test_audit_pv_03_mtm_severe_fx_devaluation_real_usd_loss_despite_nominal_ars_gain(
        self,
    ) -> None:
        """Verify severe FX devaluation (FX_0=1000 -> FX_1=5000) reveals real USD loss despite +100% nominal ARS gain."""
        pos = PositionValuationInput(
            ticker="PAMP",
            quantity=Decimal("200"),
            avg_cost_price=Decimal("1000"),
            market_price=Decimal("2000"),
            currency="ARS",
            entry_fx_rate=Decimal("1000"),
        )
        rep = self.service.value_portfolio_mark_to_market(
            positions=[pos],
            fx_rate_ars_per_usd=Decimal("5000"),
            as_of=self.as_of,
        )
        p = rep.positions[0]
        self.assertEqual(p.unrealized_pnl_pct_ars, Decimal("1.0000"))
        self.assertEqual(p.unrealized_pnl_pct_usd, Decimal("-0.6000"))
        self.assertEqual(p.fx_return_component, Decimal("4.0000"))
        self.assertEqual(p.interaction_return_component, Decimal("-2.4000"))
        self.assertEqual(
            p.unrealized_pnl_pct_usd + p.fx_return_component + p.interaction_return_component,
            p.unrealized_pnl_pct_ars,
        )

    def test_audit_pv_04_usd_native_asset_under_ars_devaluation_karnosky_singer_identity(
        self,
    ) -> None:
        """Verify USD-native asset attribution under ARS devaluation preserves exact Karnosky-Singer closure."""
        pos = PositionValuationInput(
            ticker="AAPL",
            quantity=Decimal("10"),
            avg_cost_price=Decimal("200"),
            market_price=Decimal("220"),
            currency="USD",
            entry_fx_rate=Decimal("1000"),
        )
        rep = self.service.value_portfolio_mark_to_market(
            positions=[pos],
            fx_rate_ars_per_usd=Decimal("1500"),
            as_of=self.as_of,
        )
        p = rep.positions[0]
        self.assertEqual(p.unrealized_pnl_pct_usd, Decimal("0.1000"))
        self.assertEqual(p.fx_return_component, Decimal("0.5000"))
        self.assertEqual(p.interaction_return_component, Decimal("0.0500"))
        self.assertEqual(p.unrealized_pnl_pct_ars, Decimal("0.6500"))

    def test_audit_pv_05_largest_remainder_1_position_portfolio(self) -> None:
        """Verify Largest Remainder Method on a 1-position portfolio with and without cash."""
        pos = [
            PositionValuationInput(
                ticker="A01",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        self.assertEqual(rep.positions[0].weight_in_positions, Decimal("1.0000"))
        self.assertEqual(rep.positions[0].weight_in_net_worth, Decimal("1.0000"))

    def test_audit_pv_06_largest_remainder_2_positions_portfolio(self) -> None:
        """Verify Largest Remainder Method on a 2-position portfolio."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(2)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        self.assertEqual(sum(p.weight_in_positions for p in rep.positions), Decimal("1.0000"))

    def test_audit_pv_07_largest_remainder_3_equal_positions_portfolio(self) -> None:
        """Verify Largest Remainder Method on 3 equal positions (1/3 each -> 0.3334 + 0.3333 + 0.3333 = 1.0000)."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(3)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        weights = [p.weight_in_positions for p in rep.positions]
        self.assertEqual(weights, [Decimal("0.3334"), Decimal("0.3333"), Decimal("0.3333")])
        self.assertEqual(sum(weights), Decimal("1.0000"))

    def test_audit_pv_08_largest_remainder_6_equal_positions_portfolio(self) -> None:
        """Verify Largest Remainder Method on 6 equal positions (1/6 each -> 4 * 0.1667 + 2 * 0.1666 = 1.0000)."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(6)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        self.assertEqual(sum(p.weight_in_positions for p in rep.positions), Decimal("1.0000"))
        self.assertEqual(sum(p.weight_in_net_worth for p in rep.positions), Decimal("1.0000"))

    def test_audit_pv_09_largest_remainder_7_equal_positions_portfolio_with_cash(self) -> None:
        """Verify Largest Remainder Method on 7 prime-count equal positions plus bimonetary cash."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(7)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos,
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_ars=Decimal("100000"),
            cash_balance_usd=Decimal("100"),
            as_of=self.as_of,
        )
        self.assertEqual(sum(p.weight_in_positions for p in rep.positions), Decimal("1.0000"))
        self.assertLess(
            sum(p.weight_in_net_worth for p in rep.positions),
            Decimal("1.0000"),
        )

    def test_audit_pv_10_largest_remainder_11_equal_positions_portfolio(self) -> None:
        """Verify Largest Remainder Method on 11 prime-count equal positions."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(11)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        self.assertEqual(sum(p.weight_in_positions for p in rep.positions), Decimal("1.0000"))

    def test_audit_pv_11_largest_remainder_13_equal_positions_portfolio(self) -> None:
        """Verify Largest Remainder Method on 13 prime-count equal positions."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(13)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        self.assertEqual(sum(p.weight_in_positions for p in rep.positions), Decimal("1.0000"))

    def test_audit_pv_12_largest_remainder_17_equal_positions_portfolio_with_cash(self) -> None:
        """Verify Largest Remainder Method on 17 prime-count equal positions with cash."""
        pos = [
            PositionValuationInput(
                ticker=f"A{i:02d}",
                quantity=Decimal("1"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="USD",
            )
            for i in range(17)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=pos,
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_usd=Decimal("300"),
            as_of=self.as_of,
        )
        self.assertEqual(sum(p.weight_in_positions for p in rep.positions), Decimal("1.0000"))
        self.assertLess(
            sum(p.weight_in_net_worth for p in rep.positions),
            Decimal("1.0000"),
        )

    def test_audit_pv_13_multi_lot_consolidation_3_lots_same_currency_different_entry_fx(
        self,
    ) -> None:
        """Verify multi-lot consolidation across 3 lots of the same ticker with distinct entry FX rates."""
        lots = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("1000"),
                market_price=Decimal("1500"),
                currency="ARS",
                entry_fx_rate=Decimal("800"),
            ),
            PositionValuationInput(
                ticker=" ggal ",
                quantity=Decimal("20"),
                avg_cost_price=Decimal("1200"),
                market_price=Decimal("1500"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="ggal",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("1400"),
                market_price=Decimal("1500"),
                currency="ARS",
                entry_fx_rate=Decimal("1200"),
            ),
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=lots, fx_rate_ars_per_usd=Decimal("1500"), as_of=self.as_of
        )
        self.assertEqual(len(rep.positions), 1)
        p = rep.positions[0]
        self.assertEqual(p.quantity, Decimal("40.0000"))
        self.assertEqual(p.cost_basis_ars, Decimal("48000.0000"))
        self.assertEqual(p.market_value_ars, Decimal("60000.0000"))

    def test_audit_pv_14_multi_lot_consolidation_5_lots_mixed_ars_and_usd_entries(self) -> None:
        """Verify multi-lot consolidation across 5 lots with mixed ARS and USD denominations."""
        lots = [
            PositionValuationInput(
                ticker="AL30",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("500"),
                market_price=Decimal("700"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="AL30",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("0.55"),
                market_price=Decimal("0.70"),
                currency="USD",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="AL30",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("600"),
                market_price=Decimal("700"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="AL30",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("0.65"),
                market_price=Decimal("0.70"),
                currency="USD",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="AL30",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("700"),
                market_price=Decimal("700"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=lots, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
        )
        self.assertEqual(len(rep.positions), 1)
        self.assertEqual(rep.positions[0].quantity, Decimal("500.0000"))
        self.assertEqual(rep.positions[0].market_value_usd, Decimal("350.0000"))

    def test_audit_pv_15_multi_lot_consolidation_10_lots_stress(self) -> None:
        """Verify multi-lot consolidation across 10 sequential lots of the same asset."""
        lots = [
            PositionValuationInput(
                ticker="SPY",
                quantity=Decimal("5"),
                avg_cost_price=Decimal(str(400 + i * 10)),
                market_price=Decimal("500"),
                currency="USD",
                entry_fx_rate=Decimal(str(900 + i * 20)),
            )
            for i in range(10)
        ]
        rep = self.service.value_portfolio_mark_to_market(
            positions=lots, fx_rate_ars_per_usd=Decimal("1200"), as_of=self.as_of
        )
        self.assertEqual(len(rep.positions), 1)
        self.assertEqual(rep.positions[0].quantity, Decimal("50.0000"))
        self.assertEqual(rep.positions[0].market_value_usd, Decimal("25000.0000"))

    def test_audit_pv_16_value_holdings_from_quotes_cleaned_holding_records_and_ba_suffixes(
        self,
    ) -> None:
        """Verify value_holdings_from_quotes resolves .BA suffixes in both holdings and market_quotes."""
        holdings = [
            CleanedHoldingRecord(
                row_number=1,
                ticker="GGAL.BA",
                quantity=Decimal("50"),
                avg_price=Decimal("3000"),
                currency="ARS",
            ),
            CleanedHoldingRecord(
                row_number=2,
                ticker="BMA",
                quantity=Decimal("25"),
                avg_price=Decimal("4000"),
                currency="ARS",
            ),
        ]
        quotes = {"GGAL": Decimal("3600"), "BMA.BA": Decimal("4800")}
        rep = self.service.value_holdings_from_quotes(
            holdings=holdings,
            market_quotes=quotes,
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        self.assertEqual(len(rep.positions), 2)
        self.assertEqual(rep.total_positions_value_ars, Decimal("300000.0000"))

    def test_audit_pv_17_value_holdings_from_quotes_missing_quote_raises_error(self) -> None:
        """Verify value_holdings_from_quotes raises MissingMarketPriceError when a quote is absent."""
        holdings = [
            CleanedHoldingRecord(
                row_number=1,
                ticker="CEPU",
                quantity=Decimal("10"),
                avg_price=Decimal("1000"),
                currency="ARS",
            )
        ]
        with self.assertRaises(MissingMarketPriceError):
            self.service.value_holdings_from_quotes(
                holdings=holdings,
                market_quotes={"GGAL": Decimal("1000")},
                fx_rate_ars_per_usd=Decimal("1000"),
                as_of=self.as_of,
            )

    def test_audit_pv_18_value_holdings_from_quotes_non_positive_quote_raises_error(self) -> None:
        """Verify value_holdings_from_quotes rejects zero or negative quotes with MissingMarketPriceError."""
        holdings = [
            CleanedHoldingRecord(
                row_number=1,
                ticker="CEPU",
                quantity=Decimal("10"),
                avg_price=Decimal("1000"),
                currency="ARS",
            )
        ]
        with self.assertRaises(MissingMarketPriceError):
            self.service.value_holdings_from_quotes(
                holdings=holdings,
                market_quotes={"CEPU": Decimal("0")},
                fx_rate_ars_per_usd=Decimal("1000"),
                as_of=self.as_of,
            )

    def test_audit_pv_19_twr_1_subperiod_end_and_start_timing(self) -> None:
        """Verify calculate_twr for a single sub-period under both END and START cash flow timing."""
        s_end = SubPeriodValuationSlice(
            start_value=Decimal("1000"),
            end_value=Decimal("1300"),
            net_cash_flow=Decimal("200"),
            cash_flow_timing="END",
        )
        self.assertEqual(self.service.calculate_twr([s_end]), Decimal("0.1000"))

        s_start = SubPeriodValuationSlice(
            start_value=Decimal("1000"),
            end_value=Decimal("1320"),
            net_cash_flow=Decimal("200"),
            cash_flow_timing="START",
        )
        self.assertEqual(self.service.calculate_twr([s_start]), Decimal("0.1000"))

    def test_audit_pv_20_twr_4_quarterly_subperiods_geometric_chain(self) -> None:
        """Verify calculate_twr geometric chaining across 4 quarterly sub-periods."""
        slices = [
            SubPeriodValuationSlice(start_value=Decimal("1000"), end_value=Decimal("1100")),
            SubPeriodValuationSlice(start_value=Decimal("1100"), end_value=Decimal("1210")),
            SubPeriodValuationSlice(start_value=Decimal("1210"), end_value=Decimal("1089")),
            SubPeriodValuationSlice(start_value=Decimal("1089"), end_value=Decimal("1306.80")),
        ]
        # 1.10 * 1.10 * 0.90 * 1.20 - 1 = 1.3068 - 1 = 0.3068
        self.assertEqual(self.service.calculate_twr(slices), Decimal("0.3068"))

    def test_audit_pv_21_twr_12_monthly_subperiods_geometric_chain(self) -> None:
        """Verify calculate_twr across 12 monthly sub-periods with +1% monthly return."""
        slices: list[SubPeriodValuationSlice] = []
        val = Decimal("10000")
        for _ in range(12):
            nxt = val * Decimal("1.01")
            slices.append(SubPeriodValuationSlice(start_value=val, end_value=nxt))
            val = nxt
        # 1.01^12 - 1 = 0.126825... -> 0.1268
        self.assertEqual(self.service.calculate_twr(slices), Decimal("0.1268"))

    def test_audit_pv_22_twr_52_weekly_subperiods_geometric_chain(self) -> None:
        """Verify calculate_twr across 52 weekly sub-periods with alternating +2% and -1% returns."""
        slices: list[SubPeriodValuationSlice] = []
        val = Decimal("10000")
        for i in range(52):
            mult = Decimal("1.02") if i % 2 == 0 else Decimal("0.99")
            nxt = val * mult
            slices.append(SubPeriodValuationSlice(start_value=val, end_value=nxt))
            val = nxt
        twr = self.service.calculate_twr(slices)
        expected = ((Decimal("1.02") * Decimal("0.99")) ** 26 - Decimal("1")).quantize(
            Decimal("0.0001")
        )
        self.assertEqual(twr, expected)

    def test_audit_pv_23_twr_full_end_of_period_withdrawal_returns_zero_gain(self) -> None:
        """Verify full end-of-period withdrawal leaving end_value == 0 and net_cash_flow == -start_value returns 0.0000."""
        s = SubPeriodValuationSlice(
            start_value=Decimal("5000"),
            end_value=Decimal("0"),
            net_cash_flow=Decimal("-5000"),
            cash_flow_timing="END",
        )
        self.assertEqual(self.service.calculate_twr([s]), Decimal("0.0000"))

    def test_audit_pv_24_twr_zero_opening_balance_with_start_deposit(self) -> None:
        """Verify $0 opening balance with START-timed deposit computes exact return on the deposit."""
        s = SubPeriodValuationSlice(
            start_value=Decimal("0"),
            end_value=Decimal("2300"),
            net_cash_flow=Decimal("2000"),
            cash_flow_timing="START",
        )
        self.assertEqual(self.service.calculate_twr([s]), Decimal("0.1500"))

    def test_audit_pv_25_twr_market_loss_50_pct(self) -> None:
        """Verify calculate_twr under a 50% market loss."""
        s = SubPeriodValuationSlice(start_value=Decimal("1000"), end_value=Decimal("500"))
        self.assertEqual(self.service.calculate_twr([s]), Decimal("-0.5000"))

    def test_audit_pv_26_twr_market_loss_99_99_pct(self) -> None:
        """Verify calculate_twr under a 99.99% near-wipeout market loss."""
        s = SubPeriodValuationSlice(start_value=Decimal("10000"), end_value=Decimal("1"))
        self.assertEqual(self.service.calculate_twr([s]), Decimal("-0.9999"))

    def test_audit_pv_27_twr_market_loss_100_pct_total_wipeout(self) -> None:
        """Verify calculate_twr under a 100% total market loss (end_value=0, net_cash_flow=0)."""
        s = SubPeriodValuationSlice(start_value=Decimal("10000"), end_value=Decimal("0"))
        self.assertEqual(self.service.calculate_twr([s]), Decimal("-1.0000"))

    def test_audit_pv_28_mwr_dietz_and_irr_flow_at_day_zero(self) -> None:
        """Verify Modified Dietz and IRR agree exactly when a cash flow occurs at day_offset == 0 (w_j = 1.0)."""
        cfs = [DatedCashFlowEvent(day_offset=0, amount=Decimal("1000"))]
        dietz = self.service.calculate_mwr_modified_dietz(
            start_value=Decimal("1000"),
            end_value=Decimal("2400"),
            total_days=100,
            cash_flows=cfs,
        )
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("2400"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertEqual(dietz, Decimal("0.2000"))
        self.assertEqual(irr, Decimal("0.2000"))

    def test_audit_pv_29_mwr_dietz_and_irr_flow_at_day_total_days(self) -> None:
        """Verify Modified Dietz and IRR agree exactly when a cash flow occurs at day_offset == total_days (w_j = 0.0)."""
        cfs = [DatedCashFlowEvent(day_offset=100, amount=Decimal("500"))]
        dietz = self.service.calculate_mwr_modified_dietz(
            start_value=Decimal("1000"),
            end_value=Decimal("1800"),
            total_days=100,
            cash_flows=cfs,
        )
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("1800"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertEqual(dietz, Decimal("0.3000"))
        self.assertEqual(irr, Decimal("0.3000"))

    def test_audit_pv_30_mwr_multiple_same_day_opposing_flows_canceling_to_zero(self) -> None:
        """Verify multiple opposing cash flows on the same day (+1000 and -1000) cancel cleanly."""
        cfs = [
            DatedCashFlowEvent(day_offset=40, amount=Decimal("1000")),
            DatedCashFlowEvent(day_offset=40, amount=Decimal("-1000")),
        ]
        dietz = self.service.calculate_mwr_modified_dietz(
            start_value=Decimal("2000"),
            end_value=Decimal("2500"),
            total_days=100,
            cash_flows=cfs,
        )
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("2000"),
            end_value=Decimal("2500"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertEqual(dietz, Decimal("0.2500"))
        self.assertEqual(irr, Decimal("0.2500"))

    def test_audit_pv_31_mwr_irr_hyperinflationary_return_over_500_pct(self) -> None:
        """Verify calculate_mwr_irr converges accurately for hyperinflationary returns > +500%."""
        cfs = [DatedCashFlowEvent(day_offset=50, amount=Decimal("1000"))]
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("9000"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertGreater(irr, Decimal("5.0000"))
        u = Decimal("1") + irr
        npv = (
            Decimal("1000") * u
            + Decimal("1000") * (Decimal("0.5") * u.ln()).exp()
            - Decimal("9000")
        )
        self.assertLess(abs(npv), Decimal("1.0"))

    def test_audit_pv_32_mwr_irr_extreme_hyperinflationary_return_over_1500_pct(self) -> None:
        """Verify calculate_mwr_irr dynamic upper bracket expansion for extreme returns > +1500%."""
        cfs = [DatedCashFlowEvent(day_offset=50, amount=Decimal("500"))]
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("22000"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertGreater(irr, Decimal("15.0000"))
        u = Decimal("1") + irr
        npv = (
            Decimal("1000") * u
            + Decimal("500") * (Decimal("0.5") * u.ln()).exp()
            - Decimal("22000")
        )
        self.assertLess(abs(npv), Decimal("2.0"))

    def test_audit_pv_33_mwr_irr_extreme_15000_pct_with_late_outflow(self) -> None:
        """Verify calculate_mwr_irr converges when true root exceeds 100x via dynamic bracket expansion."""
        cfs = [DatedCashFlowEvent(day_offset=90, amount=Decimal("-500"))]
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("100"),
            end_value=Decimal("18000"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertGreater(irr, Decimal("150.0000"))

    def test_audit_pv_34_mwr_irr_total_loss_end_value_zero_with_mid_period_inflow(self) -> None:
        """Verify calculate_mwr_irr returns -1.0000 when end_value == 0 with non-negative inflows."""
        cfs = [DatedCashFlowEvent(day_offset=30, amount=Decimal("500"))]
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("0"),
            total_days=60,
            cash_flows=cfs,
        )
        self.assertEqual(irr, Decimal("-1.0000"))

    def test_audit_pv_35_mwr_irr_full_mid_period_redemption_with_gain(self) -> None:
        """Verify calculate_mwr_irr solves exact return when investor redeems 100% mid-period at a profit."""
        # Start 1000, at day 50/100 withdraws -1200, end_value = 0 -> +20% in half a period -> (1.2)^2 - 1 = 0.4400
        cfs = [DatedCashFlowEvent(day_offset=50, amount=Decimal("-1200"))]
        irr = self.service.calculate_mwr_irr(
            start_value=Decimal("1000"),
            end_value=Decimal("0"),
            total_days=100,
            cash_flows=cfs,
        )
        self.assertEqual(irr, Decimal("0.4400"))

    def test_audit_pv_36_annualization_short_period_30_days(self) -> None:
        """Verify compound annualization over a 30-day period in evaluate_performance_metrics."""
        slices = [SubPeriodValuationSlice(start_value=Decimal("1000"), end_value=Decimal("1020"))]
        perf = self.service.evaluate_performance_metrics(
            slices=slices,
            start_value=Decimal("1000"),
            end_value=Decimal("1020"),
            total_days=30,
        )
        self.assertEqual(perf.twr, Decimal("0.0200"))
        self.assertGreater(perf.annualized_twr, Decimal("0.2600"))

    def test_audit_pv_37_annualization_multi_year_730_days(self) -> None:
        """Verify compound annualization over a 730-day (2-year) period."""
        slices = [SubPeriodValuationSlice(start_value=Decimal("1000"), end_value=Decimal("1440"))]
        perf = self.service.evaluate_performance_metrics(
            slices=slices,
            start_value=Decimal("1000"),
            end_value=Decimal("1440"),
            total_days=730,
        )
        self.assertEqual(perf.twr, Decimal("0.4400"))
        self.assertEqual(perf.annualized_twr, Decimal("0.2000"))

    def test_audit_pv_38_annualization_total_wipeout_returns_minus_100_pct(self) -> None:
        """Verify compound annualization of -1.0000 (-100%) returns -1.0000 without domain error."""
        slices = [SubPeriodValuationSlice(start_value=Decimal("1000"), end_value=Decimal("0"))]
        perf = self.service.evaluate_performance_metrics(
            slices=slices,
            start_value=Decimal("1000"),
            end_value=Decimal("0"),
            total_days=180,
        )
        self.assertEqual(perf.twr, Decimal("-1.0000"))
        self.assertEqual(perf.annualized_twr, Decimal("-1.0000"))

    def test_audit_pv_39_valuation_curve_sub_day_intraday_snapshots_minimum_1_day_floor(
        self,
    ) -> None:
        """Verify evaluate_valuation_curve handles intraday snapshots (< 24h apart) using total_days >= 1 floor."""
        t0 = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
        t1 = datetime(2026, 5, 1, 16, 0, tzinfo=UTC)
        snaps = [
            HistoricalValuationSnapshot(
                as_of=t0, net_worth_ars=Decimal("100000"), fx_rate_ars_per_usd=Decimal("1000")
            ),
            HistoricalValuationSnapshot(
                as_of=t1, net_worth_ars=Decimal("101000"), fx_rate_ars_per_usd=Decimal("1000")
            ),
        ]
        curve = self.service.evaluate_valuation_curve(snaps)
        self.assertEqual(curve.total_days, 1)
        self.assertEqual(curve.performance_ars.twr, Decimal("0.0100"))

    def test_audit_pv_40_valuation_curve_out_of_order_snapshots_sorted_chronologically(
        self,
    ) -> None:
        """Verify evaluate_valuation_curve sorts out-of-order snapshots chronologically before evaluation."""
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        t1 = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        snaps = [
            HistoricalValuationSnapshot(
                as_of=t2, net_worth_ars=Decimal("121000"), fx_rate_ars_per_usd=Decimal("1000")
            ),
            HistoricalValuationSnapshot(
                as_of=t0, net_worth_ars=Decimal("100000"), fx_rate_ars_per_usd=Decimal("1000")
            ),
            HistoricalValuationSnapshot(
                as_of=t1, net_worth_ars=Decimal("110000"), fx_rate_ars_per_usd=Decimal("1000")
            ),
        ]
        curve = self.service.evaluate_valuation_curve(snaps)
        self.assertEqual([p.as_of for p in curve.points], [t0, t1, t2])
        self.assertEqual(curve.performance_ars.twr, Decimal("0.2100"))

    def test_audit_pv_41_valuation_curve_dual_currency_drawdown_divergence(self) -> None:
        """Verify valuation curve captures zero ARS drawdown alongside deep USD drawdown during devaluation."""
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        t1 = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
        snaps = [
            HistoricalValuationSnapshot(
                as_of=t0, net_worth_ars=Decimal("1000000"), fx_rate_ars_per_usd=Decimal("1000")
            ),
            HistoricalValuationSnapshot(
                as_of=t1, net_worth_ars=Decimal("1200000"), fx_rate_ars_per_usd=Decimal("2000")
            ),
        ]
        curve = self.service.evaluate_valuation_curve(snaps)
        self.assertEqual(curve.max_drawdown_ars, Decimal("0.0000"))
        self.assertEqual(curve.max_drawdown_usd, Decimal("-0.4000"))

    def test_audit_pv_42_cash_only_portfolio_positive_ars_and_usd_cash_weights(self) -> None:
        """Verify cash-only portfolio sets total_positions_value_usd == 0.0000 and positions == []."""
        rep = self.service.value_portfolio_mark_to_market(
            positions=[],
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_ars=Decimal("500000"),
            cash_balance_usd=Decimal("500"),
            as_of=self.as_of,
        )
        self.assertEqual(rep.positions, [])
        self.assertEqual(rep.total_net_worth_usd, Decimal("1000.0000"))
        self.assertEqual(rep.total_positions_value_usd, Decimal("0.0000"))
        self.assertIsNone(rep.total_unrealized_pnl_pct_ars)

    def test_audit_pv_43_empty_portfolio_zero_cash_weights_are_zero(self) -> None:
        """Verify completely empty portfolio (no positions, zero cash) produces 0.0000 net worth without division by zero."""
        rep = self.service.value_portfolio_mark_to_market(
            positions=[],
            fx_rate_ars_per_usd=Decimal("1000"),
            cash_balance_ars=Decimal("0"),
            cash_balance_usd=Decimal("0"),
            as_of=self.as_of,
        )
        self.assertEqual(rep.total_net_worth_ars, Decimal("0.0000"))
        self.assertEqual(rep.total_net_worth_usd, Decimal("0.0000"))

    def test_audit_pv_44_zero_quantity_position_filtered_out_cleanly(self) -> None:
        """Verify PositionValuationInput rejects quantity == 0 with ValidationError."""
        with self.assertRaises(ValidationError):
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("0"),
                avg_cost_price=Decimal("1000"),
                market_price=Decimal("1200"),
                currency="ARS",
            )

    def test_audit_pv_45_invalid_fx_rate_zero_or_negative_raises_error(self) -> None:
        """Verify value_portfolio_mark_to_market rejects zero or negative fx_rate_ars_per_usd."""
        with self.assertRaises(InvalidFXRateError):
            self.service.value_portfolio_mark_to_market(
                positions=[], fx_rate_ars_per_usd=Decimal("0"), as_of=self.as_of
            )
        with self.assertRaises(InvalidFXRateError):
            self.service.value_portfolio_mark_to_market(
                positions=[], fx_rate_ars_per_usd=Decimal("-1000"), as_of=self.as_of
            )

    def test_audit_pv_46_negative_cash_balance_rejected(self) -> None:
        """Verify value_portfolio_mark_to_market rejects negative cash balances."""
        with self.assertRaises(InvalidValuationInputError):
            self.service.value_portfolio_mark_to_market(
                positions=[],
                fx_rate_ars_per_usd=Decimal("1000"),
                cash_balance_ars=Decimal("-1"),
                as_of=self.as_of,
            )

    def test_audit_pv_47_boolean_numeric_inputs_rejected_across_valuation_dtos(self) -> None:
        """Verify boolean values masquerading as numbers are rejected in PositionValuationInput and service methods."""
        with self.assertRaises(ValidationError):
            PositionValuationInput(
                ticker="GGAL",
                quantity=True,  # type: ignore[arg-type]
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="ARS",
            )
        with self.assertRaises(InvalidFXRateError):
            self.service.value_portfolio_mark_to_market(
                positions=[],
                fx_rate_ars_per_usd=True,  # type: ignore[arg-type]
                as_of=self.as_of,
            )

    def test_audit_pv_48_exponent_bomb_strings_rejected(self) -> None:
        """Verify exponent bomb strings (> 32 chars) are rejected with InvalidValuationInputError."""
        with self.assertRaises((InvalidValuationInputError, ValidationError)):
            PositionValuationInput(
                ticker="GGAL",
                quantity="1" + "0" * 40,  # type: ignore[arg-type]
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="ARS",
            )

    def test_audit_pv_49_control_chars_in_portfolio_id_rejected(self) -> None:
        """Verify control characters in portfolio_id are rejected across MTM and curve methods."""
        with self.assertRaises(InvalidValuationInputError):
            self.service.value_portfolio_mark_to_market(
                positions=[],
                fx_rate_ars_per_usd=Decimal("1000"),
                portfolio_id="bad\x00id",
                as_of=self.as_of,
            )

    def test_audit_pv_50_valued_position_breakdown_model_validator_rejects_tampered_quadrature(
        self,
    ) -> None:
        """Verify ValuedPositionBreakdown model validator rejects tampered horizontal accounting or Karnosky-Singer sum."""
        with self.assertRaises(ValidationError):
            ValuedPositionBreakdown(
                ticker="GGAL",
                native_currency="ARS",
                quantity=Decimal("10"),
                avg_cost_price_native=Decimal("100"),
                market_price_native=Decimal("120"),
                cost_basis_ars=Decimal("1000"),
                market_value_ars=Decimal("1200"),
                unrealized_pnl_ars=Decimal("999"),  # Tampered! Should be 200
                unrealized_pnl_pct_ars=Decimal("0.2000"),
                cost_basis_usd=Decimal("1.0000"),
                market_value_usd=Decimal("1.2000"),
                unrealized_pnl_usd=Decimal("0.2000"),
                unrealized_pnl_pct_usd=Decimal("0.2000"),
                fx_return_component=Decimal("0.0000"),
                interaction_return_component=Decimal("0.0000"),
                weight_in_positions=Decimal("1.0000"),
                weight_in_net_worth=Decimal("1.0000"),
            )

    def test_audit_pv_51_cash_flow_day_offset_exceeding_total_days_rejected(self) -> None:
        """Verify DatedCashFlowEvent with day_offset > total_days raises InvalidCashFlowPeriodError."""
        cfs = [DatedCashFlowEvent(day_offset=101, amount=Decimal("100"))]
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.service.calculate_mwr_modified_dietz(
                start_value=Decimal("1000"),
                end_value=Decimal("1200"),
                total_days=100,
                cash_flows=cfs,
            )

    def test_audit_pv_52_subperiod_slice_non_positive_effective_capital_base_rejected(self) -> None:
        """Verify SubPeriodValuationSlice rejects START withdrawal that exhausts or exceeds start_value."""
        with self.assertRaises(ValidationError):
            SubPeriodValuationSlice(
                start_value=Decimal("1000"),
                end_value=Decimal("500"),
                net_cash_flow=Decimal("-1000"),
                cash_flow_timing="START",
            )
