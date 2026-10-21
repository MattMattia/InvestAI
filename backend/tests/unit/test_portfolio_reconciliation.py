"""
Unit test suite for Module 6.3 Phase 1: Portfolio Reconciliation Service,
Duplicate Lot Consolidation, Snapshot vs. Merge Synchronization, and Anti-IDOR.
"""
from __future__ import annotations

from decimal import Decimal
import unittest
import uuid

from pydantic import ValidationError
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register ORM metadata
from app.core.database import Base
from app.domain.services.ingestion.data_cleaning_pipeline import (
    CleanHoldingRecord,
    CleaningErrorCode,
    InvalidHoldingRecord,
)
from app.domain.services.portfolio_reconciliation import (
    EmptyReconciliationSnapshotError,
    HoldingReconciliationEvent,
    PortfolioReconciliationService,
    ReconciliationAction,
    ReconciliationMode,
    ReconciliationPortfolioNotFoundError,
    ReconciliationReport,
)
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.ingestion import IngestionReportSummary


@pytest.mark.unit
class TestPortfolioReconciliation(unittest.IsolatedAsyncioTestCase):
    """Comprehensive unit tests for PortfolioReconciliationService and contracts."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.session: AsyncSession = self.session_factory()
        self.service = PortfolioReconciliationService()

        # Seed owner user and second user for anti-IDOR checks
        self.owner_id = str(uuid.uuid4())
        self.other_user_id = str(uuid.uuid4())
        self.portfolio_id = str(uuid.uuid4())

        owner = UserModel(
            id=self.owner_id,
            email="owner@investai.com",
            hashed_password="hashed_password_1",
        )
        other = UserModel(
            id=self.other_user_id,
            email="other@investai.com",
            hashed_password="hashed_password_2",
        )
        portfolio = PortfolioModel(
            id=self.portfolio_id,
            user_id=self.owner_id,
            name="Cartera Principal ALyC",
            cash_balance_ars=100000.0,
            cash_balance_usd=500.0,
        )
        self.session.add_all([owner, other, portfolio])

        # Seed initial assets and holdings: GGAL (100 @ 1500), YPFD (50 @ 20000), COME (500 @ 120)
        assets = [
            AssetModel(
                ticker="GGAL",
                name="Grupo Financiero Galicia",
                asset_type="EQUITY",
                currency="ARS",
                sector="FINANCIALS",
                market="BYMA",
            ),
            AssetModel(
                ticker="YPFD",
                name="YPF S.A.",
                asset_type="EQUITY",
                currency="ARS",
                sector="ENERGY",
                market="BYMA",
            ),
            AssetModel(
                ticker="COME",
                name="Sociedad Comercial del Plata",
                asset_type="EQUITY",
                currency="ARS",
                sector="CONGLOMERATE",
                market="BYMA",
            ),
        ]
        holdings = [
            HoldingModel(
                portfolio_id=self.portfolio_id,
                asset_ticker="GGAL",
                quantity=100.0,
                average_buy_price=1500.0,
                current_price=1550.0,
            ),
            HoldingModel(
                portfolio_id=self.portfolio_id,
                asset_ticker="YPFD",
                quantity=50.0,
                average_buy_price=20000.0,
                current_price=21000.0,
            ),
            HoldingModel(
                portfolio_id=self.portfolio_id,
                asset_ticker="COME",
                quantity=500.0,
                average_buy_price=120.0,
                current_price=125.0,
            ),
        ]
        self.session.add_all(assets + holdings)
        await self.session.commit()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.engine.dispose()

    def test_consolidate_clean_records_single_and_duplicate_lots_weighted_avg_price(
        self,
    ) -> None:
        """
        Verify duplicate lots of the same ticker (e.g. free balance + pledged/caucion)
        are consolidated with summed quantity and exact quantity-weighted average
        purchase price, preserving first-appearance order.
        """
        records = [
            CleanHoldingRecord(
                row_number=2,
                ticker="GGAL",
                quantity=Decimal("100"),
                avg_price=Decimal("1500.00"),
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=3,
                ticker="AAPL",
                quantity=Decimal("10"),
                avg_price=Decimal("24000.12345"),
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=4,
                ticker="GGAL",
                quantity=Decimal("300"),
                avg_price=Decimal("1700.00"),
                currency="ARS",
            ),
        ]

        consolidated, warnings = self.service.consolidate_clean_records(records)
        self.assertEqual(len(consolidated), 2)
        self.assertEqual([r.ticker for r in consolidated], ["GGAL", "AAPL"])

        # GGAL: total_qty = 400, weighted_avg_price = (100*1500 + 300*1700) / 400 = 1650.0000
        ggal = consolidated[0]
        self.assertEqual(ggal.quantity, Decimal("400.0000"))
        self.assertEqual(ggal.avg_price, Decimal("1650.0000"))
        self.assertEqual(ggal.currency, "ARS")

        # AAPL: single lot quantized to 4 decimals
        aapl = consolidated[1]
        self.assertEqual(aapl.quantity, Decimal("10.0000"))
        self.assertEqual(aapl.avg_price, Decimal("24000.1235"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Consolidated 2 lots for ticker 'GGAL'", warnings[0])

    def test_consolidate_clean_records_cross_currency_and_partial_price_warnings(
        self,
    ) -> None:
        """
        Verify cross-currency duplicate lots emit an explicit warning and never
        average ARS with USD prices, and partial missing prices compute weighted
        average strictly over priced lots.
        """
        records = [
            CleanHoldingRecord(
                row_number=2,
                ticker="AL30",
                quantity=Decimal("1000"),
                avg_price=Decimal("700.00"),
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=3,
                ticker="AL30",
                quantity=Decimal("500"),
                avg_price=Decimal("0.55"),
                currency="USD",
            ),
            CleanHoldingRecord(
                row_number=4,
                ticker="PAMP",
                quantity=Decimal("200"),
                avg_price=Decimal("2500.00"),
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=5,
                ticker="PAMP",
                quantity=Decimal("100"),
                avg_price=None,
                currency="ARS",
            ),
        ]

        consolidated, warnings = self.service.consolidate_clean_records(records)
        self.assertEqual(len(consolidated), 2)

        al30 = consolidated[0]
        self.assertEqual(al30.quantity, Decimal("1500.0000"))
        self.assertEqual(al30.currency, "ARS")
        # USD lot price (0.55) must not pollute ARS average price (700.0000)
        self.assertEqual(al30.avg_price, Decimal("700.0000"))

        pamp = consolidated[1]
        self.assertEqual(pamp.quantity, Decimal("300.0000"))
        self.assertEqual(pamp.avg_price, Decimal("2500.0000"))

        self.assertTrue(
            any("Cross-currency lots detected for ticker 'AL30'" in w for w in warnings)
        )
        self.assertTrue(
            any("Partial average purchase price across lots for ticker 'PAMP'" in w for w in warnings)
        )

    async def test_reconcile_portfolio_snapshot_lifecycle_added_updated_unchanged_removed(
        self,
    ) -> None:
        """
        Verify SNAPSHOT reconciliation adds new holdings, updates modified holdings,
        marks identical holdings as UNCHANGED, and removes holdings absent from
        the incoming statement without orphan or FK constraint errors.
        """
        incoming = [
            # GGAL: quantity increased from 100 -> 150, avg_price 1500 -> 1600 (UPDATED)
            CleanHoldingRecord(
                row_number=2,
                ticker="GGAL",
                quantity=Decimal("150"),
                avg_price=Decimal("1600"),
                currency="ARS",
            ),
            # YPFD: identical 50 @ 20000 (UNCHANGED)
            CleanHoldingRecord(
                row_number=3,
                ticker="YPFD",
                quantity=Decimal("50"),
                avg_price=Decimal("20000"),
                currency="ARS",
            ),
            # AAPL: brand new position 10 @ 24000 (ADDED)
            CleanHoldingRecord(
                row_number=4,
                ticker="AAPL",
                quantity=Decimal("10"),
                avg_price=Decimal("24000"),
                currency="ARS",
            ),
            # COME is omitted -> must be REMOVED in SNAPSHOT mode
        ]

        report = await self.service.reconcile_portfolio(
            db=self.session,
            portfolio_id=self.portfolio_id,
            clean_records=incoming,
            mode=ReconciliationMode.SNAPSHOT,
            user_id=self.owner_id,
        )
        await self.session.commit()

        self.assertEqual(report.portfolio_id, self.portfolio_id)
        self.assertEqual(report.mode, ReconciliationMode.SNAPSHOT)
        self.assertEqual(report.added_count, 1)
        self.assertEqual(report.updated_count, 1)
        self.assertEqual(report.unchanged_count, 1)
        self.assertEqual(report.removed_count, 1)
        self.assertEqual(report.total_holdings_after, 3)

        events_by_ticker = {e.ticker: e for e in report.events}
        self.assertEqual(events_by_ticker["GGAL"].action, ReconciliationAction.UPDATED)
        self.assertEqual(events_by_ticker["GGAL"].quantity_delta, Decimal("50.0000"))
        self.assertEqual(events_by_ticker["YPFD"].action, ReconciliationAction.UNCHANGED)
        self.assertEqual(events_by_ticker["YPFD"].quantity_delta, Decimal("0.0000"))
        self.assertEqual(events_by_ticker["AAPL"].action, ReconciliationAction.ADDED)
        self.assertEqual(events_by_ticker["AAPL"].quantity_delta, Decimal("10.0000"))
        self.assertEqual(events_by_ticker["COME"].action, ReconciliationAction.REMOVED)
        self.assertEqual(events_by_ticker["COME"].previous_quantity, Decimal("500.0000"))
        self.assertEqual(events_by_ticker["COME"].new_quantity, Decimal("0.0000"))
        self.assertEqual(events_by_ticker["COME"].quantity_delta, Decimal("-500.0000"))

        # Verify persisted DB state
        stmt = select(HoldingModel).where(
            HoldingModel.portfolio_id == self.portfolio_id
        )
        persisted = (await self.session.execute(stmt)).scalars().all()
        persisted_tickers = {h.asset_ticker: h for h in persisted}
        self.assertEqual(set(persisted_tickers.keys()), {"GGAL", "YPFD", "AAPL"})
        self.assertEqual(persisted_tickers["GGAL"].quantity, 150.0)
        self.assertEqual(persisted_tickers["GGAL"].average_buy_price, 1600.0)
        self.assertEqual(persisted_tickers["AAPL"].quantity, 10.0)

    async def test_reconcile_portfolio_merge_mode_preserves_unmentioned_holdings(
        self,
    ) -> None:
        """
        Verify MERGE mode upserts incoming holdings without deleting existing
        portfolio positions absent from the statement, and preserves historical
        average purchase price when an incoming update has avg_price=None.
        """
        incoming = [
            # GGAL updated quantity with missing avg_price -> preserves 1500.0000
            CleanHoldingRecord(
                row_number=2,
                ticker="GGAL",
                quantity=Decimal("125"),
                avg_price=None,
                currency="ARS",
            ),
            # NVDA added without avg_price -> stored as 0.0 in ORM, None in event
            CleanHoldingRecord(
                row_number=3,
                ticker="NVDA",
                quantity=Decimal("20"),
                avg_price=None,
                currency="USD",
            ),
        ]

        report = await self.service.reconcile_portfolio(
            db=self.session,
            portfolio_id=self.portfolio_id,
            clean_records=incoming,
            mode=ReconciliationMode.MERGE,
            user_id=self.owner_id,
        )
        await self.session.commit()

        self.assertEqual(report.mode, ReconciliationMode.MERGE)
        self.assertEqual(report.added_count, 1)
        self.assertEqual(report.updated_count, 1)
        self.assertEqual(report.removed_count, 0)
        self.assertEqual(report.unchanged_count, 0)
        # 3 initial (GGAL, YPFD, COME) + 1 added (NVDA) = 4 total holdings after
        self.assertEqual(report.total_holdings_after, 4)

        events_by_ticker = {e.ticker: e for e in report.events}
        self.assertEqual(
            events_by_ticker["GGAL"].new_avg_price, Decimal("1500.0000")
        )
        self.assertIsNone(events_by_ticker["NVDA"].new_avg_price)
        self.assertTrue(
            any("preserved historical average price" in w for w in report.warnings)
        )

    async def test_reconcile_portfolio_empty_snapshot_guard_and_override(self) -> None:
        """
        Verify empty SNAPSHOT is blocked by default with EmptyReconciliationSnapshotError,
        and allowed only when allow_empty_snapshot=True.
        """
        with self.assertRaises(EmptyReconciliationSnapshotError):
            await self.service.reconcile_portfolio(
                db=self.session,
                portfolio_id=self.portfolio_id,
                clean_records=[],
                mode=ReconciliationMode.SNAPSHOT,
                user_id=self.owner_id,
                allow_empty_snapshot=False,
            )

        report = await self.service.reconcile_portfolio(
            db=self.session,
            portfolio_id=self.portfolio_id,
            clean_records=[],
            mode=ReconciliationMode.SNAPSHOT,
            user_id=self.owner_id,
            allow_empty_snapshot=True,
        )
        await self.session.commit()

        self.assertEqual(report.removed_count, 3)
        self.assertEqual(report.total_holdings_after, 0)

    async def test_reconcile_portfolio_anti_idor_ownership_and_missing_portfolio(
        self,
    ) -> None:
        """
        Verify non-existent portfolio IDs and cross-tenant access attempts raise
        ReconciliationPortfolioNotFoundError without modifying database holdings.
        """
        incoming = [
            CleanHoldingRecord(
                row_number=2,
                ticker="GGAL",
                quantity=Decimal("999"),
                avg_price=Decimal("1500"),
                currency="ARS",
            )
        ]

        # Wrong user_id (anti-IDOR/BOLA)
        with self.assertRaises(ReconciliationPortfolioNotFoundError):
            await self.service.reconcile_portfolio(
                db=self.session,
                portfolio_id=self.portfolio_id,
                clean_records=incoming,
                mode=ReconciliationMode.SNAPSHOT,
                user_id=self.other_user_id,
            )

        # Non-existent portfolio_id
        with self.assertRaises(ReconciliationPortfolioNotFoundError):
            await self.service.reconcile_portfolio(
                db=self.session,
                portfolio_id=str(uuid.uuid4()),
                clean_records=incoming,
                mode=ReconciliationMode.SNAPSHOT,
                user_id=self.owner_id,
            )

    def test_reconciliation_event_and_report_model_validators(self) -> None:
        """
        Verify HoldingReconciliationEvent and ReconciliationReport enforce strict
        accounting delta and action count invariants.
        """
        # Mismatched delta
        with self.assertRaises(ValidationError):
            HoldingReconciliationEvent(
                ticker="GGAL",
                action=ReconciliationAction.UPDATED,
                previous_quantity=Decimal("100"),
                new_quantity=Decimal("150"),
                quantity_delta=Decimal("20"),
            )

        # ADDED with previous_quantity > 0
        with self.assertRaises(ValidationError):
            HoldingReconciliationEvent(
                ticker="GGAL",
                action=ReconciliationAction.ADDED,
                previous_quantity=Decimal("10"),
                new_quantity=Decimal("50"),
                quantity_delta=Decimal("40"),
            )

        # REMOVED with new_quantity > 0
        with self.assertRaises(ValidationError):
            HoldingReconciliationEvent(
                ticker="GGAL",
                action=ReconciliationAction.REMOVED,
                previous_quantity=Decimal("50"),
                new_quantity=Decimal("10"),
                quantity_delta=Decimal("-40"),
            )

        # UNCHANGED with non-zero delta
        with self.assertRaises(ValidationError):
            HoldingReconciliationEvent(
                ticker="GGAL",
                action=ReconciliationAction.UNCHANGED,
                previous_quantity=Decimal("50"),
                new_quantity=Decimal("60"),
                quantity_delta=Decimal("10"),
            )

        # ReconciliationReport with mismatched event counts
        with self.assertRaises(ValidationError):
            ReconciliationReport(
                portfolio_id="p-1",
                mode=ReconciliationMode.SNAPSHOT,
                events=[],
                added_count=1,
                updated_count=0,
                removed_count=0,
                unchanged_count=0,
                total_holdings_after=1,
            )

    def test_ingestion_report_summary_contract_invariants(self) -> None:
        """
        Verify IngestionReportSummary enforces row count invariants
        (valid_records_count + invalid_records_count == total_rows_parsed and
        invalid_records_count == len(invalid_records)) and extra='forbid'.
        """
        rec_report = ReconciliationReport(
            portfolio_id="p-1",
            mode=ReconciliationMode.SNAPSHOT,
            events=[
                HoldingReconciliationEvent(
                    ticker="GGAL",
                    action=ReconciliationAction.ADDED,
                    previous_quantity=Decimal("0.0000"),
                    new_quantity=Decimal("100.0000"),
                    quantity_delta=Decimal("100.0000"),
                )
            ],
            added_count=1,
            updated_count=0,
            removed_count=0,
            unchanged_count=0,
            total_holdings_after=1,
        )
        invalid_item = InvalidHoldingRecord(
            row_number=3,
            raw_ticker="BAD",
            raw_quantity="-10",
            error_code=CleaningErrorCode.NEGATIVE_QUANTITY,
            reason="Quantity must be positive",
        )

        valid_summary = IngestionReportSummary(
            filename="balanz_tenencias.csv",
            portfolio_id="p-1",
            mode=ReconciliationMode.SNAPSHOT,
            total_rows_parsed=2,
            valid_records_count=1,
            invalid_records_count=1,
            invalid_records=[invalid_item],
            reconciliation=rec_report,
            warnings=["Row 3 rejected"],
        )
        self.assertEqual(valid_summary.total_rows_parsed, 2)
        self.assertEqual(valid_summary.valid_records_count, 1)
        self.assertEqual(valid_summary.invalid_records_count, 1)

        # Mismatch between valid + invalid and total_rows_parsed
        with self.assertRaises(ValidationError):
            IngestionReportSummary(
                filename="balanz_tenencias.csv",
                portfolio_id="p-1",
                mode=ReconciliationMode.SNAPSHOT,
                total_rows_parsed=5,
                valid_records_count=1,
                invalid_records_count=1,
                invalid_records=[invalid_item],
                reconciliation=rec_report,
            )

        # Mismatch between invalid_records_count and len(invalid_records)
        with self.assertRaises(ValidationError):
            IngestionReportSummary(
                filename="balanz_tenencias.csv",
                portfolio_id="p-1",
                mode=ReconciliationMode.SNAPSHOT,
                total_rows_parsed=2,
                valid_records_count=1,
                invalid_records_count=1,
                invalid_records=[],
                reconciliation=rec_report,
            )

        # extra="forbid" enforcement
        with self.assertRaises(ValidationError):
            IngestionReportSummary(
                filename="balanz_tenencias.csv",
                portfolio_id="p-1",
                mode=ReconciliationMode.SNAPSHOT,
                total_rows_parsed=1,
                valid_records_count=1,
                invalid_records_count=0,
                invalid_records=[],
                reconciliation=rec_report,
                unexpected_field="injected",  # type: ignore[call-arg]
            )


