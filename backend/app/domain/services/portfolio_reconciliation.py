"""
Portfolio reconciliation service and transactional holding synchronization
engine (Module 6.3 - Phase 1).

Compares persisted database holdings (`PortfolioModel` / `HoldingModel`) against
validated records (`CleanHoldingRecord`) extracted from broker statements,
generating deterministic inventory adjustment events under `SNAPSHOT` or `MERGE`
reconciliation modes.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
import math
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.services.ingestion.data_cleaning_pipeline import CleanHoldingRecord
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.schemas.envelope import BaseSchema

# ============================================================================
# Quantitative & Numerical Precision Constants
# ============================================================================
RECONCILIATION_QUANTIZE: Decimal = Decimal("0.0001")

_KNOWN_SOVEREIGN_TICKERS: frozenset[str] = frozenset(
    {
        "AL30",
        "GD30",
        "AL29",
        "GD29",
        "AL35",
        "GD35",
        "AE38",
        "GD38",
        "AL41",
        "GD41",
        "GD46",
        "TX26",
        "TX28",
        "T2V4",
        "TV24",
        "TO26",
        "DICP",
        "PARP",
    }
)

_KNOWN_LOCAL_EQUITIES: frozenset[str] = frozenset(
    {
        "GGAL",
        "YPFD",
        "PAMP",
        "BMA",
        "BBAR",
        "ALUA",
        "TXAR",
        "CRES",
        "TGSU2",
        "TECO2",
        "CEPU",
        "EDN",
        "TRAN",
        "LOMA",
        "MIRG",
        "COME",
        "BYMA",
        "VALO",
        "SUPV",
        "MORI",
        "BHIP",
        "BPAT",
        "DGCU2",
        "CGPA2",
        "BOLT",
        "AUSO",
        "OEST",
        "INVJ",
        "HAVA",
        "SEMI",
        "MOLI",
        "AGRO",
    }
)


# ============================================================================
# Domain Exception Hierarchy
# ============================================================================
class PortfolioReconciliationError(Exception):
    """Base domain exception for portfolio reconciliation failures."""


class ReconciliationPortfolioNotFoundError(PortfolioReconciliationError):
    """
    Raised when the target portfolio does not exist or belongs to another user
    (enforcing strict multi-tenant anti-IDOR/BOLA isolation).
    """


class EmptyReconciliationSnapshotError(PortfolioReconciliationError):
    """
    Raised when a `SNAPSHOT` reconciliation is attempted with zero valid holding
    records without explicit `allow_empty_snapshot=True`, preventing accidental
    full-portfolio wipeouts.
    """


# ============================================================================
# Canonical Enums & Immutable DTO Contracts
# ============================================================================
class ReconciliationMode(str, Enum):
    """Execution strategy for portfolio holding synchronization."""

    SNAPSHOT = "SNAPSHOT"
    MERGE = "MERGE"


class ReconciliationAction(str, Enum):
    """Inventory transition applied to an individual holding position."""

    ADDED = "ADDED"
    UPDATED = "UPDATED"
    REMOVED = "REMOVED"
    UNCHANGED = "UNCHANGED"


def _coerce_finite_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Boolean or None value is not permitted for '{field_name}'")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float is not permitted for '{field_name}'")
        dec = Decimal(str(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid Decimal string for '{field_name}'") from exc
    else:
        raise ValueError(
            f"Unsupported type '{type(value).__name__}' for '{field_name}'"
        )

    if not dec.is_finite():
        raise ValueError(f"Non-finite Decimal is not permitted for '{field_name}'")
    return dec


class HoldingReconciliationEvent(BaseSchema):
    """
    Immutable audit event capturing the before/after state of a reconciled holding.
    """

    ticker: str = Field(min_length=1, max_length=20)
    action: ReconciliationAction
    previous_quantity: Decimal = Field(default=Decimal("0.0000"), ge=0)
    new_quantity: Decimal = Field(default=Decimal("0.0000"), ge=0)
    quantity_delta: Decimal
    previous_avg_price: Decimal | None = Field(default=None, gt=0)
    new_avg_price: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="ARS", pattern=r"^(ARS|USD)$")

    @field_validator(
        "previous_quantity",
        "new_quantity",
        "quantity_delta",
        mode="before",
    )
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator("previous_avg_price", "new_avg_price", mode="before")
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_accounting_invariants(self) -> HoldingReconciliationEvent:
        expected_delta = self.new_quantity - self.previous_quantity
        if self.quantity_delta != expected_delta:
            raise ValueError(
                f"quantity_delta ({self.quantity_delta}) must equal "
                f"new_quantity - previous_quantity ({expected_delta})"
            )

        if self.action == ReconciliationAction.ADDED:
            if self.previous_quantity != Decimal("0") or self.new_quantity <= Decimal("0"):
                raise ValueError(
                    "ADDED event requires previous_quantity == 0 and new_quantity > 0"
                )
        elif self.action == ReconciliationAction.REMOVED:
            if self.previous_quantity <= Decimal("0") or self.new_quantity != Decimal("0"):
                raise ValueError(
                    "REMOVED event requires previous_quantity > 0 and new_quantity == 0"
                )
        elif self.action == ReconciliationAction.UNCHANGED:
            if self.quantity_delta != Decimal("0"):
                raise ValueError(
                    "UNCHANGED event requires quantity_delta == 0"
                )

        return self


class ReconciliationReport(BaseSchema):
    """
    Immutable summary of a completed portfolio reconciliation transaction.
    """

    portfolio_id: str
    mode: ReconciliationMode
    events: list[HoldingReconciliationEvent] = Field(default_factory=list)
    added_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    removed_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    total_holdings_after: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_event_count_consistency(self) -> ReconciliationReport:
        total_counted = (
            self.added_count
            + self.updated_count
            + self.removed_count
            + self.unchanged_count
        )
        if total_counted != len(self.events):
            raise ValueError(
                f"Sum of action counts ({total_counted}) must equal "
                f"len(events) ({len(self.events)})"
            )
        return self


# ============================================================================
# Portfolio Reconciliation Domain Service
# ============================================================================
class PortfolioReconciliationService:
    """
    Domain service that consolidates duplicate holding lots from broker reports
    and synchronizes them transactionally against persisted portfolio holdings.
    """

    @staticmethod
    def _extract_db_decimal(val: Any) -> Decimal:
        """
        Safely convert a database numeric value (`float | int | Decimal`) into a
        4-decimal quantized `Decimal`.
        """
        if val is None:
            return Decimal("0.0000")
        if isinstance(val, Decimal):
            raw = val
        else:
            raw = Decimal(str(val))
        quantized = raw.quantize(RECONCILIATION_QUANTIZE, rounding=ROUND_HALF_UP)
        if quantized == Decimal("0"):
            return Decimal("0.0000")
        return quantized

    @staticmethod
    def _infer_asset_type(ticker: str) -> str:
        """Infer a canonical asset_type string for newly registered tickers."""
        t = ticker.strip().upper()
        if t in _KNOWN_SOVEREIGN_TICKERS or (
            t.startswith(("AL", "GD", "AE", "TX", "TV", "TO", "T2"))
            and len(t) in (4, 5)
        ):
            return "BOND_SOVEREIGN"
        if t.startswith(("YMC", "IRC", "TLC", "MTC")):
            return "BOND_CORPORATE"
        if t.startswith(("S", "LE", "BONCAP")) and len(t) > 3:
            return "TREASURY_BILL"
        if t in _KNOWN_LOCAL_EQUITIES:
            return "EQUITY"
        return "CEDEAR"

    async def _ensure_asset_model(
        self,
        db: AsyncSession,
        ticker: str,
        currency: str,
    ) -> AssetModel:
        """
        Ensure an `AssetModel` row exists in the database for `ticker` before
        inserting a `HoldingModel` (satisfying foreign key constraints).
        """
        normalized_ticker = ticker.strip().upper()
        stmt = select(AssetModel).where(AssetModel.ticker == normalized_ticker)
        result = await db.execute(stmt)
        asset = result.scalar_one_or_none()
        if asset is None:
            asset = AssetModel(
                ticker=normalized_ticker,
                name=normalized_ticker,
                asset_type=self._infer_asset_type(normalized_ticker),
                currency=currency,
                sector="OTHER",
                market="BYMA",
            )
            db.add(asset)
            await db.flush()
        return asset

    def consolidate_clean_records(
        self, records: Sequence[CleanHoldingRecord]
    ) -> tuple[list[CleanHoldingRecord], list[str]]:
        """
        Group and consolidate `CleanHoldingRecord` items sharing the same ticker
        while preserving deterministic first-appearance order.

        - Sums quantities across duplicate lots (e.g. free balance + pledged/caucion).
        - Computes quantity-weighted average purchase price across lots sharing the
          primary currency without ever mixing `ARS` and `USD` prices.
        """
        grouped: dict[str, list[CleanHoldingRecord]] = {}
        for rec in records:
            key = rec.ticker.strip().upper()
            grouped.setdefault(key, []).append(rec)

        consolidated: list[CleanHoldingRecord] = []
        warnings: list[str] = []

        for ticker, group in grouped.items():
            if len(group) == 1:
                single = group[0]
                q_qty = single.quantity.quantize(
                    RECONCILIATION_QUANTIZE, rounding=ROUND_HALF_UP
                )
                q_price = (
                    single.avg_price.quantize(
                        RECONCILIATION_QUANTIZE, rounding=ROUND_HALF_UP
                    )
                    if single.avg_price is not None
                    else None
                )
                consolidated.append(
                    CleanHoldingRecord(
                        row_number=single.row_number,
                        ticker=ticker,
                        quantity=q_qty,
                        avg_price=q_price,
                        currency=single.currency,
                        raw_fields=single.raw_fields,
                    )
                )
                continue

            total_qty = sum((r.quantity for r in group), Decimal("0")).quantize(
                RECONCILIATION_QUANTIZE, rounding=ROUND_HALF_UP
            )
            primary_currency = group[0].currency

            mismatched_lots = [r for r in group if r.currency != primary_currency]
            if mismatched_lots:
                warnings.append(
                    f"Cross-currency lots detected for ticker '{ticker}' "
                    f"(primary={primary_currency}); excluding {len(mismatched_lots)} "
                    "mismatched currency lot(s) from weighted average price."
                )

            same_currency_lots = [r for r in group if r.currency == primary_currency]
            priced_lots = [r for r in same_currency_lots if r.avg_price is not None]

            if priced_lots and len(priced_lots) < len(same_currency_lots):
                warnings.append(
                    f"Partial average purchase price across lots for ticker '{ticker}'; "
                    f"computed weighted average price using {len(priced_lots)} of "
                    f"{len(same_currency_lots)} lot(s)."
                )

            weighted_avg_price: Decimal | None = None
            if priced_lots:
                priced_qty = sum((r.quantity for r in priced_lots), Decimal("0"))
                if priced_qty > Decimal("0"):
                    total_cost = sum(
                        (
                            r.quantity * r.avg_price
                            for r in priced_lots
                            if r.avg_price is not None
                        ),
                        Decimal("0"),
                    )
                    weighted_avg_price = (total_cost / priced_qty).quantize(
                        RECONCILIATION_QUANTIZE, rounding=ROUND_HALF_UP
                    )

            warnings.append(
                f"Consolidated {len(group)} lots for ticker '{ticker}' "
                f"into total quantity {total_qty}."
            )

            consolidated.append(
                CleanHoldingRecord(
                    row_number=group[0].row_number,
                    ticker=ticker,
                    quantity=total_qty,
                    avg_price=weighted_avg_price,
                    currency=primary_currency,
                    raw_fields=group[0].raw_fields,
                )
            )

        return consolidated, warnings

    async def reconcile_portfolio(
        self,
        db: AsyncSession,
        portfolio_id: str,
        clean_records: Sequence[CleanHoldingRecord],
        mode: ReconciliationMode = ReconciliationMode.SNAPSHOT,
        user_id: str | UUID | None = None,
        allow_empty_snapshot: bool = False,
    ) -> ReconciliationReport:
        """
        Reconcile persisted holdings of `portfolio_id` against `clean_records`
        within the active database transaction.
        """
        # 1. Accidental Full-Portfolio Wipeout Guard
        if (
            mode == ReconciliationMode.SNAPSHOT
            and len(clean_records) == 0
            and not allow_empty_snapshot
        ):
            raise EmptyReconciliationSnapshotError(
                "Cannot execute SNAPSHOT reconciliation with zero valid records "
                "unless allow_empty_snapshot=True"
            )

        # 2. Load PortfolioModel with eager-loaded holdings & assets + Anti-IDOR check
        stmt = (
            select(PortfolioModel)
            .where(PortfolioModel.id == str(portfolio_id))
            .options(
                selectinload(PortfolioModel.holdings).selectinload(HoldingModel.asset)
            )
        )
        result = await db.execute(stmt)
        portfolio = result.scalar_one_or_none()

        if portfolio is None or (
            user_id is not None and str(portfolio.user_id) != str(user_id)
        ):
            raise ReconciliationPortfolioNotFoundError(
                f"Portfolio '{portfolio_id}' not found"
            )

        # 3. Consolidate incoming CleanHoldingRecord items
        consolidated_records, warnings = self.consolidate_clean_records(clean_records)

        # 4. Map existing database holdings by normalized ticker
        existing_by_ticker: dict[str, HoldingModel] = {}
        for h in portfolio.holdings:
            raw_t = getattr(h, "asset_ticker", None) or getattr(h, "ticker", "")
            existing_by_ticker[str(raw_t).strip().upper()] = h

        events: list[HoldingReconciliationEvent] = []
        seen_tickers: set[str] = set()

        # 5. Process consolidated incoming records
        for record in consolidated_records:
            ticker = record.ticker
            seen_tickers.add(ticker)

            if ticker not in existing_by_ticker:
                # Case A: New position (ADDED)
                asset = await self._ensure_asset_model(
                    db=db, ticker=ticker, currency=record.currency
                )
                if record.avg_price is None:
                    db_avg_price = 0.0
                    event_new_avg_price: Decimal | None = None
                    warnings.append(
                        f"Ticker '{ticker}' added without average purchase price "
                        "(persisted as 0.0 in ORM)."
                    )
                else:
                    db_avg_price = float(record.avg_price)
                    event_new_avg_price = record.avg_price

                new_holding = HoldingModel(
                    portfolio_id=portfolio.id,
                    asset_ticker=ticker,
                    quantity=float(record.quantity),
                    average_buy_price=db_avg_price,
                    current_price=db_avg_price,
                )
                new_holding.asset = asset
                portfolio.holdings.append(new_holding)

                events.append(
                    HoldingReconciliationEvent(
                        ticker=ticker,
                        action=ReconciliationAction.ADDED,
                        previous_quantity=Decimal("0.0000"),
                        new_quantity=record.quantity,
                        quantity_delta=record.quantity,
                        previous_avg_price=None,
                        new_avg_price=event_new_avg_price,
                        currency=record.currency,
                    )
                )
            else:
                # Case B: Existing position (UPDATED or UNCHANGED)
                existing_holding = existing_by_ticker[ticker]
                prev_qty = self._extract_db_decimal(existing_holding.quantity)
                raw_prev_price = self._extract_db_decimal(
                    existing_holding.average_buy_price
                )
                prev_avg_price: Decimal | None = (
                    raw_prev_price if raw_prev_price > Decimal("0") else None
                )

                if record.avg_price is not None:
                    effective_new_avg_price: Decimal | None = record.avg_price
                else:
                    if prev_avg_price is not None:
                        effective_new_avg_price = prev_avg_price
                        warnings.append(
                            f"Ticker '{ticker}' missing average purchase price in report; "
                            f"preserved historical average price {prev_avg_price}."
                        )
                    else:
                        effective_new_avg_price = None

                qty_changed = (
                    abs(record.quantity - prev_qty) >= RECONCILIATION_QUANTIZE
                )
                if effective_new_avg_price is None and prev_avg_price is None:
                    price_changed = False
                elif effective_new_avg_price is None or prev_avg_price is None:
                    price_changed = True
                else:
                    price_changed = (
                        abs(effective_new_avg_price - prev_avg_price)
                        >= RECONCILIATION_QUANTIZE
                    )

                if qty_changed or price_changed:
                    existing_holding.quantity = float(record.quantity)
                    existing_holding.average_buy_price = (
                        float(effective_new_avg_price)
                        if effective_new_avg_price is not None
                        else 0.0
                    )
                    if (
                        existing_holding.current_price <= 0.0
                        and effective_new_avg_price is not None
                    ):
                        existing_holding.current_price = float(effective_new_avg_price)
                    if (
                        existing_holding.asset is not None
                        and existing_holding.asset.currency != record.currency
                    ):
                        existing_holding.asset.currency = record.currency

                    events.append(
                        HoldingReconciliationEvent(
                            ticker=ticker,
                            action=ReconciliationAction.UPDATED,
                            previous_quantity=prev_qty,
                            new_quantity=record.quantity,
                            quantity_delta=record.quantity - prev_qty,
                            previous_avg_price=prev_avg_price,
                            new_avg_price=effective_new_avg_price,
                            currency=record.currency,
                        )
                    )
                else:
                    events.append(
                        HoldingReconciliationEvent(
                            ticker=ticker,
                            action=ReconciliationAction.UNCHANGED,
                            previous_quantity=prev_qty,
                            new_quantity=prev_qty,
                            quantity_delta=Decimal("0.0000"),
                            previous_avg_price=prev_avg_price,
                            new_avg_price=effective_new_avg_price,
                            currency=record.currency,
                        )
                    )

        # 6. Process persisted holdings absent from the incoming report
        for ticker in sorted(existing_by_ticker.keys()):
            if ticker in seen_tickers:
                continue

            existing_holding = existing_by_ticker[ticker]
            if mode == ReconciliationMode.SNAPSHOT:
                prev_qty = self._extract_db_decimal(existing_holding.quantity)
                raw_prev_price = self._extract_db_decimal(
                    existing_holding.average_buy_price
                )
                prev_avg_price = (
                    raw_prev_price if raw_prev_price > Decimal("0") else None
                )
                holding_currency = "ARS"
                if (
                    existing_holding.asset is not None
                    and existing_holding.asset.currency in ("ARS", "USD")
                ):
                    holding_currency = existing_holding.asset.currency

                portfolio.holdings.remove(existing_holding)
                await db.delete(existing_holding)

                if prev_qty > Decimal("0"):
                    events.append(
                        HoldingReconciliationEvent(
                            ticker=ticker,
                            action=ReconciliationAction.REMOVED,
                            previous_quantity=prev_qty,
                            new_quantity=Decimal("0.0000"),
                            quantity_delta=-prev_qty,
                            previous_avg_price=prev_avg_price,
                            new_avg_price=None,
                            currency=holding_currency,
                        )
                    )
            else:
                # ReconciliationMode.MERGE: keep existing holding intact in DB
                pass

        portfolio.updated_at = datetime.now(timezone.utc)
        await db.flush()

        added_count = sum(
            1 for e in events if e.action == ReconciliationAction.ADDED
        )
        updated_count = sum(
            1 for e in events if e.action == ReconciliationAction.UPDATED
        )
        removed_count = sum(
            1 for e in events if e.action == ReconciliationAction.REMOVED
        )
        unchanged_count = sum(
            1 for e in events if e.action == ReconciliationAction.UNCHANGED
        )

        return ReconciliationReport(
            portfolio_id=str(portfolio.id),
            mode=mode,
            events=events,
            added_count=added_count,
            updated_count=updated_count,
            removed_count=removed_count,
            unchanged_count=unchanged_count,
            total_holdings_after=len(portfolio.holdings),
            warnings=warnings,
        )

