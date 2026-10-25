"""
Unit test suite for Module 7.2 Phase 1:
Dynamic Mark-to-Market Bimonetary Portfolio Valuation & TWR/MWR Attribution Engine
(`backend/app/domain/services/portfolio_valuation_service.py`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from pydantic import ValidationError
import pytest

import app.domain.services as domain_services_pkg
from app.domain.services.portfolio_valuation_service import (
    DatedCashFlowEvent,
    InvalidCashFlowPeriodError,
    InvalidFXRateError,
    InvalidValuationInputError,
    PortfolioMarkToMarketReport,
    PortfolioValuationService,
    PositionValuationInput,
    SubPeriodValuationSlice,
    ValuedPositionBreakdown,
)


@pytest.mark.unit
class TestPortfolioValuation(unittest.TestCase):
    """Unit tests verifying bimonetary Mark-to-Market valuation, Karnosky-Singer attribution, TWR, and MWR."""

    def setUp(self) -> None:
        self.service = PortfolioValuationService()
        self.as_of = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)

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
                    SubPeriodValuationSlice(
                        start_value=Decimal("100"), end_value=Decimal("110")
                    )
                ],
                start_value=Decimal("100"),
                end_value=Decimal("110"),
                total_days=30,
                start_fx_rate=Decimal("1000"),
                end_fx_rate=None,
            )

        # 2. Negative capital base in TWR (START withdrawal >= start_value) and Modified Dietz
        with self.assertRaises(InvalidCashFlowPeriodError):
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
