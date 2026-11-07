"""
Unit tests for BYMA Market Calendar, Immutable DTO Contracts, and Market-Close Orchestrator
(Module 8.2 - Phase 1: `backend/app/domain/services/market_scheduler.py`).
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.domain.services.market_scheduler import (
    BYMACalendarService,
    MarketCloseJobConfig,
    MarketCloseJobReport,
    MarketCloseJobStatus,
    MarketCloseSchedulerService,
    MarketCloseTriggerType,
    PortfolioCloseInput,
    PortfolioCloseProcessResult,
)
from app.domain.services.tolerance_band_rebalancer import (
    AssetTargetBandSpec,
    BandType,
    RebalanceMode,
    RebalancePositionInput,
    ToleranceBandRebalancerConfig,
)
from pydantic import ValidationError


@pytest.mark.unit
class TestMarketScheduler(unittest.TestCase):
    """Unit test suite certifying MarketCloseSchedulerService and BYMACalendarService."""

    def setUp(self) -> None:
        self.calendar = BYMACalendarService()
        self.scheduler = MarketCloseSchedulerService(calendar_service=self.calendar)

    def test_byma_calendar_detects_weekends_and_national_holidays(self) -> None:
        """
        Verify that BYMACalendarService correctly identifies weekends, fixed and
        variable Argentine national holidays, custom holidays, and business trading days.
        """
        # Weekends (Saturday=5, Sunday=6)
        saturday = date(2026, 10, 17)
        sunday = date(2026, 10, 18)
        self.assertEqual(saturday.weekday(), 5)
        self.assertEqual(sunday.weekday(), 6)
        self.assertFalse(self.calendar.is_trading_day(saturday))
        self.assertFalse(self.calendar.is_trading_day(sunday))

        # Argentine fixed national holidays
        new_year = date(2026, 1, 1)
        revolution_day = date(2026, 5, 25)
        independence_day = date(2026, 7, 9)
        christmas = date(2026, 12, 25)
        self.assertFalse(self.calendar.is_trading_day(new_year))
        self.assertFalse(self.calendar.is_trading_day(revolution_day))
        self.assertFalse(self.calendar.is_trading_day(independence_day))
        self.assertFalse(self.calendar.is_trading_day(christmas))

        # Known variable holidays (e.g., Carnaval 2026: 16-17 Feb)
        carnaval_monday = date(2026, 2, 16)
        carnaval_tuesday = date(2026, 2, 17)
        self.assertFalse(self.calendar.is_trading_day(carnaval_monday))
        self.assertFalse(self.calendar.is_trading_day(carnaval_tuesday))

        # Regular business day (Wednesday 2026-10-14)
        regular_trading_day = date(2026, 10, 14)
        self.assertTrue(self.calendar.is_trading_day(regular_trading_day))

        # Custom holiday support
        special_closure = date(2026, 10, 15)
        custom_calendar = BYMACalendarService(custom_holidays={special_closure})
        self.assertFalse(custom_calendar.is_trading_day(special_closure))

        # Authoritative timezone check
        market_tz = self.calendar.get_market_tz()
        self.assertIsNotNone(market_tz)

    def test_scheduler_skips_non_trading_day_when_force_rerun_false(self) -> None:
        """
        Verify that execute_market_close immediately short-circuits with SKIPPED_HOLIDAY
        when target_date falls on a weekend or holiday and force_rerun=False.
        """
        holiday_date = date(2026, 5, 25)  # 25 de Mayo
        config = MarketCloseJobConfig(
            target_date=holiday_date,
            trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
            force_rerun=False,
        )
        sample_portfolio = PortfolioCloseInput(
            portfolio_id="port-holiday-001",
            cash_balance=Decimal("10000.00"),
        )

        report = self.scheduler.execute_market_close(config, [sample_portfolio])

        self.assertEqual(report.status, MarketCloseJobStatus.SKIPPED_HOLIDAY)
        self.assertEqual(report.portfolios_processed, 0)
        self.assertEqual(report.portfolios_succeeded, 0)
        self.assertEqual(report.portfolios_failed, 0)
        self.assertEqual(report.total_net_worth_processed, Decimal("0.0000"))
        self.assertEqual(report.total_rebalance_orders_generated, 0)
        self.assertEqual(report.results, [])
        self.assertGreaterEqual(report.duration_ms, 0.0)

    def test_scheduler_runs_holiday_when_force_rerun_true(self) -> None:
        """
        Verify that execute_market_close bypasses calendar closure when force_rerun=True
        (e.g., manual off-hours intervention or backtesting simulation).
        """
        holiday_date = date(2026, 1, 1)  # Año Nuevo
        config = MarketCloseJobConfig(
            target_date=holiday_date,
            trigger_type=MarketCloseTriggerType.MANUAL_OVERRIDE,
            force_rerun=True,
        )
        sample_portfolio = PortfolioCloseInput(
            portfolio_id="port-override-001",
            cash_balance=Decimal("50000.0000"),
            positions=[
                RebalancePositionInput(
                    ticker="AL30",
                    quantity=Decimal("100.0"),
                    market_price=Decimal("60.0"),
                )
            ],
        )

        report = self.scheduler.execute_market_close(config, [sample_portfolio])

        self.assertEqual(report.status, MarketCloseJobStatus.COMPLETED)
        self.assertEqual(report.portfolios_processed, 1)
        self.assertEqual(report.portfolios_succeeded, 1)
        self.assertEqual(report.portfolios_failed, 0)
        # Net worth = 50000 cash + (100 * 60) = 56000
        self.assertEqual(report.total_net_worth_processed, Decimal("56000.0000"))
        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].status, "SUCCESS")

    def test_scheduler_executes_e2e_pipeline_for_multiple_portfolios(self) -> None:
        """
        Verify comprehensive multi-portfolio execution:
        - Portfolio 1: Drifted portfolio triggering tolerance-band breach & order generation.
        - Portfolio 2: Balanced portfolio within tolerance corridors (0 rebalance orders).
        - Portfolio 3: Valuation-only portfolio without target specifications.
        """
        trading_day = date(2026, 10, 14)  # Wednesday
        config = MarketCloseJobConfig(
            target_date=trading_day,
            trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
        )

        # Portfolio 1: Needs rebalance (GGAL weight = 80%, target = 50% +/- 5%)
        # Total value: 1000 cash + (80 * 100) = 9000. GGAL is 8000/9000 = 88.8%
        p1 = PortfolioCloseInput(
            portfolio_id="port-drifted-001",
            cash_balance=Decimal("1000.0000"),
            positions=[
                RebalancePositionInput(
                    ticker="GGAL",
                    quantity=Decimal("80.0"),
                    market_price=Decimal("100.00"),
                ),
            ],
            target_specs=[
                AssetTargetBandSpec(
                    ticker="GGAL",
                    target_weight=Decimal("0.5000"),
                    absolute_tolerance_override=Decimal("0.0500"),
                ),
                AssetTargetBandSpec(
                    ticker="YPFD",
                    target_weight=Decimal("0.5000"),
                    reference_price=Decimal("100.00"),
                    absolute_tolerance_override=Decimal("0.0500"),
                ),
            ],
            rebalancer_config=ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
                rebalance_mode=RebalanceMode.FULL_TO_TARGET,
            ),
        )

        # Portfolio 2: Within bands (GGAL 50%, YPFD 50%, target 50%/50% +/- 10%)
        # Total value: (10 * 100) + (10 * 100) = 2000. Both are 50%
        p2 = PortfolioCloseInput(
            portfolio_id="port-balanced-002",
            cash_balance=Decimal("0.0000"),
            positions=[
                RebalancePositionInput(
                    ticker="GGAL",
                    quantity=Decimal("10.0"),
                    market_price=Decimal("100.00"),
                ),
                RebalancePositionInput(
                    ticker="YPFD",
                    quantity=Decimal("10.0"),
                    market_price=Decimal("100.00"),
                ),
            ],
            target_specs=[
                AssetTargetBandSpec(
                    ticker="GGAL",
                    target_weight=Decimal("0.5000"),
                    absolute_tolerance_override=Decimal("0.1000"),
                ),
                AssetTargetBandSpec(
                    ticker="YPFD",
                    target_weight=Decimal("0.5000"),
                    absolute_tolerance_override=Decimal("0.1000"),
                ),
            ],
            rebalancer_config=ToleranceBandRebalancerConfig(
                band_type=BandType.ABSOLUTE,
            ),
        )

        # Portfolio 3: Valuation only (no targets)
        p3 = PortfolioCloseInput(
            portfolio_id="port-valuation-003",
            cash_balance=Decimal("5000.0000"),
            positions=[
                RebalancePositionInput(
                    ticker="BMA",
                    quantity=Decimal("20.0"),
                    market_price=Decimal("50.00"),
                ),
            ],
        )

        report = self.scheduler.execute_market_close(config, [p1, p2, p3])

        self.assertEqual(report.status, MarketCloseJobStatus.COMPLETED)
        self.assertEqual(report.portfolios_processed, 3)
        self.assertEqual(report.portfolios_succeeded, 3)
        self.assertEqual(report.portfolios_failed, 0)
        self.assertEqual(len(report.results), 3)

        # Portfolio 1 verification
        r1 = report.results[0]
        self.assertEqual(r1.portfolio_id, "port-drifted-001")
        self.assertEqual(r1.status, "SUCCESS")
        self.assertTrue(r1.needs_rebalancing)
        self.assertGreater(r1.orders_generated_count, 0)
        self.assertIsNotNone(r1.fsm_batch_id)
        self.assertIn("GGAL", r1.breached_tickers)

        # Portfolio 2 verification
        r2 = report.results[1]
        self.assertEqual(r2.portfolio_id, "port-balanced-002")
        self.assertEqual(r2.status, "SUCCESS")
        self.assertFalse(r2.needs_rebalancing)
        self.assertEqual(r2.orders_generated_count, 0)
        self.assertIsNone(r2.fsm_batch_id)

        # Portfolio 3 verification
        r3 = report.results[2]
        self.assertEqual(r3.portfolio_id, "port-valuation-003")
        self.assertEqual(r3.status, "SUCCESS")
        self.assertFalse(r3.needs_rebalancing)
        # Net worth = 5000 + (20 * 50) = 6000
        self.assertEqual(r3.total_portfolio_value, Decimal("6000.0000"))

        # Invariant checks
        self.assertEqual(
            report.total_rebalance_orders_generated,
            r1.orders_generated_count + r2.orders_generated_count + r3.orders_generated_count,
        )
        expected_total_val = (
            r1.total_portfolio_value + r2.total_portfolio_value + r3.total_portfolio_value
        )
        self.assertEqual(report.total_net_worth_processed, expected_total_val)

    def test_scheduler_fault_isolation_continues_on_single_portfolio_error(self) -> None:
        """
        Verify fault isolation: an exception raised while processing one portfolio
        does not abort execution for subsequent portfolios, resulting in PARTIALLY_COMPLETED.
        """
        trading_day = date(2026, 10, 14)
        config = MarketCloseJobConfig(target_date=trading_day)

        # Portfolio 1: Valid
        p1 = PortfolioCloseInput(
            portfolio_id="port-success-001",
            cash_balance=Decimal("10000.0000"),
        )

        # Portfolio 2: Faulty targets (targets summing to > 1.0000 raises InvalidTargetAllocationError)
        p2 = PortfolioCloseInput(
            portfolio_id="port-faulty-002",
            cash_balance=Decimal("5000.0000"),
            positions=[
                RebalancePositionInput(
                    ticker="GGAL",
                    quantity=Decimal("10.0"),
                    market_price=Decimal("100.0"),
                )
            ],
            target_specs=[
                AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.8000")),
                AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.8000")),
            ],
        )

        # Portfolio 3: Valid
        p3 = PortfolioCloseInput(
            portfolio_id="port-success-003",
            cash_balance=Decimal("20000.0000"),
        )

        report = self.scheduler.execute_market_close(config, [p1, p2, p3])

        self.assertEqual(report.status, MarketCloseJobStatus.PARTIALLY_COMPLETED)
        self.assertEqual(report.portfolios_processed, 3)
        self.assertEqual(report.portfolios_succeeded, 2)
        self.assertEqual(report.portfolios_failed, 1)

        self.assertEqual(report.results[0].status, "SUCCESS")
        self.assertEqual(report.results[1].status, "FAILED")
        self.assertIsNotNone(report.results[1].error_message)
        self.assertEqual(report.results[2].status, "SUCCESS")

        # Total net worth must only aggregate succeeded portfolios (p1=10000 + p3=20000 = 30000)
        self.assertEqual(report.total_net_worth_processed, Decimal("30000.0000"))

    def test_scheduler_dry_run_flag_and_deterministic_job_id(self) -> None:
        """
        Verify that dry_run=True is honored throughout the report, and that the
        job_id is deterministic and reproducible under identical configurations.
        """
        target_d = date(2026, 10, 14)
        config_a = MarketCloseJobConfig(
            target_date=target_d,
            trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
            dry_run=True,
            base_currency="USD",
        )
        config_b = MarketCloseJobConfig(
            target_date=target_d,
            trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
            dry_run=True,
            base_currency="USD",
        )
        config_diff = MarketCloseJobConfig(
            target_date=target_d,
            trigger_type=MarketCloseTriggerType.MANUAL_OVERRIDE,
            dry_run=False,
            base_currency="ARS",
        )

        id_a = MarketCloseSchedulerService._generate_job_id(config_a)
        id_b = MarketCloseSchedulerService._generate_job_id(config_b)
        id_diff = MarketCloseSchedulerService._generate_job_id(config_diff)

        self.assertEqual(id_a, id_b)
        self.assertNotEqual(id_a, id_diff)
        self.assertTrue(id_a.startswith("job-"))
        self.assertEqual(len(id_a), 36)

        p = PortfolioCloseInput(
            portfolio_id="port-dryrun-001",
            cash_balance=Decimal("100.0"),
        )
        report = self.scheduler.execute_market_close(config_a, [p])
        self.assertTrue(report.dry_run)
        self.assertEqual(report.job_id, id_a)

    def test_scheduler_report_accounting_invariants_and_empty_portfolios(self) -> None:
        """
        Verify that empty portfolio lists complete gracefully, and that MarketCloseJobReport
        model validators strictly enforce accounting equality invariants.
        """
        trading_day = date(2026, 10, 14)
        config = MarketCloseJobConfig(target_date=trading_day)

        # Empty portfolios list
        report = self.scheduler.execute_market_close(config, [])
        self.assertEqual(report.status, MarketCloseJobStatus.COMPLETED)
        self.assertEqual(report.portfolios_processed, 0)
        self.assertEqual(report.portfolios_succeeded, 0)
        self.assertEqual(report.portfolios_failed, 0)
        self.assertEqual(report.total_net_worth_processed, Decimal("0.0000"))
        self.assertEqual(report.total_rebalance_orders_generated, 0)
        self.assertEqual(report.results, [])

        now = datetime.now(UTC)

        # Invariant 1: portfolios_processed != succeeded + failed must raise ValidationError
        with self.assertRaises(ValidationError):
            MarketCloseJobReport(
                job_id="job-test-invariant-12345",
                target_date=trading_day,
                trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
                status=MarketCloseJobStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=10.0,
                portfolios_processed=5,
                portfolios_succeeded=4,
                portfolios_failed=0,  # 4 + 0 != 5
                total_rebalance_orders_generated=0,
                results=[],
            )

        # Invariant 2: total_rebalance_orders_generated mismatch must raise ValidationError
        with self.assertRaises(ValidationError):
            MarketCloseJobReport(
                job_id="job-test-invariant-12345",
                target_date=trading_day,
                trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
                status=MarketCloseJobStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=10.0,
                portfolios_processed=1,
                portfolios_succeeded=1,
                portfolios_failed=0,
                total_rebalance_orders_generated=5,
                results=[
                    PortfolioCloseProcessResult(
                        portfolio_id="p1",
                        status="SUCCESS",
                        orders_generated_count=2,  # 2 != 5
                    )
                ],
            )

        # Invariant 3: completed_at < started_at must raise ValidationError
        with self.assertRaises(ValidationError):
            MarketCloseJobReport(
                job_id="job-test-invariant-12345",
                target_date=trading_day,
                trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
                status=MarketCloseJobStatus.COMPLETED,
                started_at=now,
                completed_at=now - timedelta(seconds=10),
                duration_ms=10.0,
                portfolios_processed=0,
                portfolios_succeeded=0,
                portfolios_failed=0,
                total_rebalance_orders_generated=0,
                results=[],
            )
