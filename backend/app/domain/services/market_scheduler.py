"""
BYMA Market Calendar Engine, Distributed Locks, Immutable DTO Contracts,
and Market-Close Orchestrator (Module 8.2 - Phases 1 & 2: `backend/app/domain/services/market_scheduler.py`).

Provides:
- Argentine national holiday calendar and BYMA trading session validation (`BYMACalendarService`).
- Strongly typed, immutable DTO contracts for market-close jobs and portfolio results (`BaseSchema`).
- In-Memory and Redis-backed distributed locks with atomic Lua release (`DistributedLockProtocol`).
- Asynchronous end-of-day market-close orchestrator with concurrency locking, snapshot persistence,
  and per-portfolio fault isolation (`MarketCloseSchedulerService`).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from app.domain.services.tolerance_band_rebalancer import (
    AssetTargetBandSpec,
    RebalancePositionInput,
    ToleranceBandRebalancerConfig,
    ToleranceBandRebalancerService,
)
from app.schemas.envelope import BaseSchema


# ============================================================================
# Enums
# ============================================================================
class MarketCloseJobStatus(str, Enum):
    """Execution status for an end-of-day market-close scheduled or manual run."""

    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    SKIPPED_HOLIDAY = "SKIPPED_HOLIDAY"
    SKIPPED_ALREADY_RUNNING = "SKIPPED_ALREADY_RUNNING"
    FAILED = "FAILED"


class MarketCloseTriggerType(str, Enum):
    """Trigger modality initiating the market-close orchestration cycle."""

    AUTOMATIC_SCHEDULE = "AUTOMATIC_SCHEDULE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    BACKTEST_SIMULATION = "BACKTEST_SIMULATION"


# ============================================================================
# Immutable DTO Contracts
# ============================================================================
class LockAcquireResult(BaseSchema):
    """
    Immutable representation of a distributed lock acquisition outcome.
    """

    acquired: bool
    lock_key: str
    token: str | None = None
    ttl_seconds: int = Field(default=600, ge=1)
    error_message: str | None = Field(default=None, max_length=255)


class PortfolioCloseInput(BaseSchema):
    """
    Immutable input payload representing a single portfolio to be valued and
    evaluated for rebalancing drift at market close.
    """

    portfolio_id: str = Field(min_length=1, max_length=64)
    cash_balance: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    positions: list[RebalancePositionInput] = Field(default_factory=list)
    target_specs: list[AssetTargetBandSpec] = Field(default_factory=list)
    rebalancer_config: ToleranceBandRebalancerConfig | None = None

    @field_validator("portfolio_id", mode="before")
    @classmethod
    def _validate_portfolio_id(cls, v: Any) -> str:
        if not isinstance(v, str) or isinstance(v, bool):
            raise ValueError("portfolio_id must be a non-empty string.")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("portfolio_id cannot be blank.")
        if any(ord(ch) < 32 for ch in cleaned):
            raise ValueError("Control characters are forbidden in portfolio_id.")
        return cleaned

    @field_validator("cash_balance", mode="before")
    @classmethod
    def _validate_cash_balance(cls, v: Any) -> Decimal:
        if isinstance(v, bool) or v is None:
            raise ValueError("cash_balance must be a valid numeric Decimal.")
        try:
            dec = Decimal(str(v))
            if not dec.is_finite():
                raise ValueError("cash_balance must be finite.")
            return dec
        except Exception as exc:
            raise ValueError(f"Invalid cash_balance '{v}': {exc}") from exc


class MarketCloseJobConfig(BaseSchema):
    """
    Configuration parameters governing an end-of-day close job execution.
    """

    target_date: date
    trigger_type: MarketCloseTriggerType = MarketCloseTriggerType.AUTOMATIC_SCHEDULE
    force_rerun: bool = False
    dry_run: bool = False
    base_currency: str = Field(default="USD", pattern=r"^(ARS|USD)$")


class PortfolioCloseProcessResult(BaseSchema):
    """
    Individual evaluation result for a single portfolio processed during market close.
    """

    portfolio_id: str
    status: Literal["SUCCESS", "FAILED", "SKIPPED"]
    total_portfolio_value: Decimal | None = None
    needs_rebalancing: bool = False
    breached_tickers: list[str] = Field(default_factory=list)
    orders_generated_count: int = Field(default=0, ge=0)
    fsm_batch_id: str | None = None
    snapshot_id: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=255)


class MarketCloseJobReport(BaseSchema):
    """
    Consolidated immutable report summarizing the end-of-day market-close execution,
    accounting closure invariants, and generated rebalance orders.
    """

    job_id: str = Field(min_length=16, max_length=64)
    target_date: date
    trigger_type: MarketCloseTriggerType
    status: MarketCloseJobStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0.0)
    portfolios_processed: int = Field(ge=0)
    portfolios_succeeded: int = Field(ge=0)
    portfolios_failed: int = Field(ge=0)
    total_net_worth_processed: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    total_rebalance_orders_generated: int = Field(ge=0)
    dry_run: bool = False
    results: list[PortfolioCloseProcessResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_invariants(self) -> MarketCloseJobReport:
        if self.portfolios_processed != self.portfolios_succeeded + self.portfolios_failed:
            raise ValueError(
                f"portfolios_processed ({self.portfolios_processed}) must equal "
                f"portfolios_succeeded ({self.portfolios_succeeded}) + "
                f"portfolios_failed ({self.portfolios_failed})."
            )
        computed_orders = sum(r.orders_generated_count for r in self.results)
        if self.total_rebalance_orders_generated != computed_orders:
            raise ValueError(
                f"total_rebalance_orders_generated ({self.total_rebalance_orders_generated}) "
                f"must equal sum of orders in results ({computed_orders})."
            )
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at.")
        return self


# ============================================================================
# Distributed Lock & Snapshot Protocols
# ============================================================================
@runtime_checkable
class DistributedLockProtocol(Protocol):
    """Protocol defining asynchronous distributed lock operations."""

    async def acquire(self, key: str, ttl_seconds: int = 600) -> LockAcquireResult:
        """Attempt to acquire a mutual exclusion lock with the specified TTL."""
        ...

    async def release(self, key: str, token: str) -> bool:
        """Release the lock if the provided token matches the held token."""
        ...


@runtime_checkable
class SnapshotPersistenceProtocol(Protocol):
    """Protocol for persisting portfolio audit snapshots during market close."""

    async def persist_audit_snapshot(
        self,
        portfolio_id: str,
        as_of: datetime,
        compliance_status: str,
        report_payload: dict[str, Any],
        critical_alerts_count: int = 0,
    ) -> str:
        """Persist an audit snapshot and return its unique identifier."""
        ...


# ============================================================================
# Lock Managers
# ============================================================================
class InMemoryLockManager:
    """
    In-memory asynchronous distributed lock manager for single-node runtimes and unit tests.
    Enforces atomic acquisition and release protected by an internal asyncio.Lock,
    using monotonic time to track TTL expirations.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._locks: dict[str, tuple[str, float]] = {}

    async def acquire(self, key: str, ttl_seconds: int = 600) -> LockAcquireResult:
        async with self._lock:
            now = time.monotonic()
            existing = self._locks.get(key)
            if existing is not None:
                token, expires_at = existing
                if now < expires_at:
                    return LockAcquireResult(
                        acquired=False,
                        lock_key=key,
                        token=None,
                        ttl_seconds=ttl_seconds,
                        error_message="Lock already held",
                    )
            # Create or overwrite expired entry
            token = str(uuid.uuid4())
            self._locks[key] = (token, now + ttl_seconds)
            return LockAcquireResult(
                acquired=True,
                lock_key=key,
                token=token,
                ttl_seconds=ttl_seconds,
            )

    async def release(self, key: str, token: str) -> bool:
        async with self._lock:
            now = time.monotonic()
            existing = self._locks.get(key)
            if existing is None:
                return False
            held_token, expires_at = existing
            if held_token != token:
                return False
            del self._locks[key]
            return now < expires_at


class RedisLockManager:
    """
    Redis-backed asynchronous distributed lock manager using SET NX EX for acquisition
    and an atomic Lua script for token-safe release.
    """

    LUA_RELEASE_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    async def acquire(self, key: str, ttl_seconds: int = 600) -> LockAcquireResult:
        token = str(uuid.uuid4())
        try:
            ok = await self.redis.set(key, token, nx=True, ex=ttl_seconds)
            if ok:
                return LockAcquireResult(
                    acquired=True,
                    lock_key=key,
                    token=token,
                    ttl_seconds=ttl_seconds,
                )
            return LockAcquireResult(
                acquired=False,
                lock_key=key,
                token=None,
                ttl_seconds=ttl_seconds,
                error_message="Lock already held in Redis",
            )
        except Exception as exc:
            return LockAcquireResult(
                acquired=False,
                lock_key=key,
                token=None,
                ttl_seconds=ttl_seconds,
                error_message=f"Redis acquire failure: {exc}"[:255],
            )

    async def release(self, key: str, token: str) -> bool:
        try:
            res = await self.redis.eval(self.LUA_RELEASE_SCRIPT, 1, key, token)
            return bool(res == 1 or res == b"1" or res is True)
        except Exception:
            return False


# ============================================================================
# Calendar Service
# ============================================================================
class BYMACalendarService:
    """
    Argentine financial market calendar tracking BYMA trading days, weekends,
    canonical national holidays, and Buenos Aires market timezone.
    """

    _FIXED_HOLIDAYS: frozenset[tuple[int, int]] = frozenset(
        {
            (1, 1),  # Año Nuevo
            (3, 24),  # Día Nacional de la Memoria por la Verdad y la Justicia
            (4, 2),  # Día del Veterano y de los Caídos en la Guerra de Malvinas
            (5, 1),  # Día del Trabajador
            (5, 25),  # Día de la Revolución de Mayo
            (6, 17),  # Paso a la Inmortalidad del Gral. Don Martín Miguel de Güemes
            (6, 20),  # Paso a la Inmortalidad del Gral. Manuel Belgrano / Día de la Bandera
            (7, 9),  # Día de la Independencia
            (8, 17),  # Paso a la Inmortalidad del Gral. José de San Martín
            (10, 12),  # Día del Respeto a la Diversidad Cultural
            (11, 20),  # Día de la Soberanía Nacional
            (12, 8),  # Inmaculada Concepción de María
            (12, 25),  # Navidad
        }
    )

    _KNOWN_VARIABLE_HOLIDAYS: frozenset[date] = frozenset(
        {
            # 2024
            date(2024, 2, 12),
            date(2024, 2, 13),
            date(2024, 3, 29),
            # 2025
            date(2025, 3, 3),
            date(2025, 3, 4),
            date(2025, 4, 18),
            # 2026
            date(2026, 2, 16),
            date(2026, 2, 17),
            date(2026, 4, 3),
            # 2027
            date(2027, 2, 8),
            date(2027, 2, 9),
            date(2027, 3, 26),
        }
    )

    def __init__(self, custom_holidays: set[date] | None = None) -> None:
        self._custom_holidays: set[date] = set(custom_holidays or set())

    def is_trading_day(self, target_date: date) -> bool:
        """
        Return True if target_date is a valid BYMA trading session; False if it
        falls on a weekend (Saturday/Sunday) or an observed Argentine national holiday.
        """
        if target_date.weekday() in (5, 6):
            return False
        if (target_date.month, target_date.day) in self._FIXED_HOLIDAYS:
            return False
        if target_date in self._KNOWN_VARIABLE_HOLIDAYS:
            return False
        if target_date in self._custom_holidays:
            return False
        return True

    def get_market_tz(self) -> timezone | ZoneInfo:
        """
        Return the authoritative Buenos Aires financial market timezone
        ('America/Argentina/Buenos_Aires') with fallback to UTC-3.
        """
        try:
            return ZoneInfo("America/Argentina/Buenos_Aires")
        except (ZoneInfoNotFoundError, Exception):
            return timezone(timedelta(hours=-3))


# ============================================================================
# Market Close Scheduler Service
# ============================================================================
class MarketCloseSchedulerService:
    """
    Stateless domain orchestrator responsible for executing end-of-day market-close
    processing across active client portfolios, integrating BYMA calendar checks,
    concurrency locking, portfolio valuation, dynamic tolerance-band evaluation,
    and idempotent order batching.
    """

    def __init__(
        self,
        calendar_service: BYMACalendarService | None = None,
        rebalancer_service: ToleranceBandRebalancerService | None = None,
        lock_manager: DistributedLockProtocol | None = None,
        snapshot_repo: SnapshotPersistenceProtocol | None = None,
    ) -> None:
        self.calendar = calendar_service or BYMACalendarService()
        self.rebalancer = rebalancer_service or ToleranceBandRebalancerService()
        self.lock_manager = lock_manager
        self.snapshot_repo = snapshot_repo

    @staticmethod
    def _generate_job_id(config: MarketCloseJobConfig) -> str:
        """
        Generate a deterministic, idempotent 36-character SHA-256 job identifier.
        """
        preimage = (
            f"close-{config.target_date.isoformat()}:"
            f"{config.trigger_type.value}:"
            f"{config.base_currency}:"
            f"{config.force_rerun}:"
            f"{config.dry_run}"
        )
        digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest()[:32]
        return f"job-{digest}"

    @staticmethod
    def _generate_lock_key(config: MarketCloseJobConfig) -> str:
        """
        Generate the canonical distributed lock key for a market-close execution.
        """
        return f"lock:market_close:{config.target_date.isoformat()}:{config.base_currency}"

    def execute_market_close(
        self,
        config: MarketCloseJobConfig,
        portfolios: Sequence[PortfolioCloseInput],
    ) -> MarketCloseJobReport:
        """
        Synchronously execute the end-of-day market-close workflow across portfolios (Phase 1).
        """
        started_at = datetime.now(UTC)
        t0 = time.perf_counter()
        job_id = self._generate_job_id(config)

        if not self.calendar.is_trading_day(config.target_date) and not config.force_rerun:
            completed_at = datetime.now(UTC)
            duration_ms = max(0.0, (time.perf_counter() - t0) * 1000.0)
            return MarketCloseJobReport(
                job_id=job_id,
                target_date=config.target_date,
                trigger_type=config.trigger_type,
                status=MarketCloseJobStatus.SKIPPED_HOLIDAY,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round(duration_ms, 2),
                portfolios_processed=0,
                portfolios_succeeded=0,
                portfolios_failed=0,
                total_net_worth_processed=Decimal("0.0000"),
                total_rebalance_orders_generated=0,
                dry_run=config.dry_run,
                results=[],
            )

        results: list[PortfolioCloseProcessResult] = []
        portfolios_succeeded = 0
        portfolios_failed = 0
        total_net_worth = Decimal("0.0000")
        total_orders = 0

        for p in portfolios:
            try:
                if not p.target_specs:
                    with localcontext(prec=50):
                        cash_dec = Decimal(str(p.cash_balance))
                        pos_value = sum(
                            (
                                Decimal(str(pos.quantity)) * Decimal(str(pos.market_price))
                                for pos in p.positions
                            ),
                            Decimal("0"),
                        )
                        net_worth = (cash_dec + pos_value).quantize(Decimal("0.0001"))

                    result = PortfolioCloseProcessResult(
                        portfolio_id=p.portfolio_id,
                        status="SUCCESS",
                        total_portfolio_value=net_worth,
                        needs_rebalancing=False,
                        breached_tickers=[],
                        orders_generated_count=0,
                        fsm_batch_id=None,
                        snapshot_id=None,
                        error_message=None,
                    )
                    with localcontext(prec=50):
                        total_net_worth += net_worth
                    portfolios_succeeded += 1
                    results.append(result)
                else:
                    rebalancer = (
                        ToleranceBandRebalancerService(config=p.rebalancer_config)
                        if p.rebalancer_config is not None
                        else self.rebalancer
                    )
                    report = rebalancer.evaluate_and_rebalance(
                        positions=p.positions,
                        target_specs=p.target_specs,
                        initial_cash=p.cash_balance,
                        base_currency=config.base_currency,
                        portfolio_id=p.portfolio_id,
                        as_of=started_at,
                    )

                    orders_count = len(report.orders)
                    batch_id: str | None = None
                    if report.needs_rebalancing and orders_count > 0:
                        batch = rebalancer.build_fsm_execution_batch(
                            report=report,
                            portfolio_id=p.portfolio_id,
                        )
                        batch_id = batch.batch_id

                    result = PortfolioCloseProcessResult(
                        portfolio_id=p.portfolio_id,
                        status="SUCCESS",
                        total_portfolio_value=report.total_portfolio_value,
                        needs_rebalancing=report.needs_rebalancing,
                        breached_tickers=list(report.breached_tickers),
                        orders_generated_count=orders_count,
                        fsm_batch_id=batch_id,
                        snapshot_id=None,
                        error_message=None,
                    )
                    with localcontext(prec=50):
                        total_net_worth += report.total_portfolio_value
                    total_orders += orders_count
                    portfolios_succeeded += 1
                    results.append(result)

            except Exception as exc:
                portfolios_failed += 1
                result = PortfolioCloseProcessResult(
                    portfolio_id=p.portfolio_id,
                    status="FAILED",
                    total_portfolio_value=None,
                    needs_rebalancing=False,
                    breached_tickers=[],
                    orders_generated_count=0,
                    fsm_batch_id=None,
                    snapshot_id=None,
                    error_message=str(exc)[:255],
                )
                results.append(result)

        portfolios_processed = len(portfolios)
        if portfolios_processed == 0:
            global_status = MarketCloseJobStatus.COMPLETED
        elif portfolios_failed == 0:
            global_status = MarketCloseJobStatus.COMPLETED
        elif portfolios_succeeded > 0:
            global_status = MarketCloseJobStatus.PARTIALLY_COMPLETED
        else:
            global_status = MarketCloseJobStatus.FAILED

        completed_at = datetime.now(UTC)
        if completed_at < started_at:
            completed_at = started_at
        duration_ms = max(0.0, (time.perf_counter() - t0) * 1000.0)

        with localcontext(prec=50):
            quantized_total_net_worth = total_net_worth.quantize(Decimal("0.0001"))

        return MarketCloseJobReport(
            job_id=job_id,
            target_date=config.target_date,
            trigger_type=config.trigger_type,
            status=global_status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=round(duration_ms, 2),
            portfolios_processed=portfolios_processed,
            portfolios_succeeded=portfolios_succeeded,
            portfolios_failed=portfolios_failed,
            total_net_worth_processed=quantized_total_net_worth,
            total_rebalance_orders_generated=total_orders,
            dry_run=config.dry_run,
            results=results,
        )

    async def execute_market_close_async(
        self,
        config: MarketCloseJobConfig,
        portfolios: Sequence[PortfolioCloseInput],
    ) -> MarketCloseJobReport:
        """
        Asynchronously execute market close with distributed locking, snapshot persistence,
        and per-portfolio fault isolation (Phase 2).
        """
        started_at = datetime.now(UTC)
        t0 = time.perf_counter()
        job_id = self._generate_job_id(config)
        lock_key = self._generate_lock_key(config)

        # 1. Distributed lock acquisition
        acquired_lock = False
        lock_token: str | None = None
        if self.lock_manager is not None:
            lock_res = await self.lock_manager.acquire(lock_key, ttl_seconds=600)
            if not lock_res.acquired and not config.force_rerun:
                completed_at = datetime.now(UTC)
                duration_ms = max(0.0, (time.perf_counter() - t0) * 1000.0)
                return MarketCloseJobReport(
                    job_id=job_id,
                    target_date=config.target_date,
                    trigger_type=config.trigger_type,
                    status=MarketCloseJobStatus.SKIPPED_ALREADY_RUNNING,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=round(duration_ms, 2),
                    portfolios_processed=0,
                    portfolios_succeeded=0,
                    portfolios_failed=0,
                    total_net_worth_processed=Decimal("0.0000"),
                    total_rebalance_orders_generated=0,
                    dry_run=config.dry_run,
                    results=[],
                )
            acquired_lock = lock_res.acquired
            lock_token = lock_res.token

        try:
            # 2. Calendar validation
            if not self.calendar.is_trading_day(config.target_date) and not config.force_rerun:
                completed_at = datetime.now(UTC)
                duration_ms = max(0.0, (time.perf_counter() - t0) * 1000.0)
                return MarketCloseJobReport(
                    job_id=job_id,
                    target_date=config.target_date,
                    trigger_type=config.trigger_type,
                    status=MarketCloseJobStatus.SKIPPED_HOLIDAY,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=round(duration_ms, 2),
                    portfolios_processed=0,
                    portfolios_succeeded=0,
                    portfolios_failed=0,
                    total_net_worth_processed=Decimal("0.0000"),
                    total_rebalance_orders_generated=0,
                    dry_run=config.dry_run,
                    results=[],
                )

            # 3. Portfolio execution loop
            results: list[PortfolioCloseProcessResult] = []
            portfolios_succeeded = 0
            portfolios_failed = 0
            total_net_worth = Decimal("0.0000")
            total_orders = 0

            for p in portfolios:
                try:
                    if not p.target_specs:
                        with localcontext(prec=50):
                            cash_dec = Decimal(str(p.cash_balance))
                            pos_val = sum(
                                (
                                    Decimal(str(pos.quantity)) * Decimal(str(pos.market_price))
                                    for pos in p.positions
                                ),
                                Decimal("0"),
                            )
                            net_worth = (cash_dec + pos_val).quantize(Decimal("0.0001"))

                        snapshot_id: str | None = None
                        if not config.dry_run and self.snapshot_repo is not None:
                            snapshot_id = await self.snapshot_repo.persist_audit_snapshot(
                                portfolio_id=p.portfolio_id,
                                as_of=started_at,
                                compliance_status="COMPLIANCE_OK",
                                report_payload={
                                    "portfolio_id": p.portfolio_id,
                                    "total_value": str(net_worth),
                                    "needs_rebalancing": False,
                                },
                                critical_alerts_count=0,
                            )

                        result = PortfolioCloseProcessResult(
                            portfolio_id=p.portfolio_id,
                            status="SUCCESS",
                            total_portfolio_value=net_worth,
                            needs_rebalancing=False,
                            breached_tickers=[],
                            orders_generated_count=0,
                            fsm_batch_id=None,
                            snapshot_id=snapshot_id,
                            error_message=None,
                        )
                        with localcontext(prec=50):
                            total_net_worth += net_worth
                        portfolios_succeeded += 1
                        results.append(result)
                    else:
                        rebalancer = (
                            ToleranceBandRebalancerService(config=p.rebalancer_config)
                            if p.rebalancer_config is not None
                            else self.rebalancer
                        )
                        report = rebalancer.evaluate_and_rebalance(
                            positions=p.positions,
                            target_specs=p.target_specs,
                            initial_cash=p.cash_balance,
                            base_currency=config.base_currency,
                            portfolio_id=p.portfolio_id,
                            as_of=started_at,
                        )

                        orders_count = len(report.orders)
                        batch_id: str | None = None
                        if report.needs_rebalancing and orders_count > 0:
                            batch = rebalancer.build_fsm_execution_batch(
                                report=report,
                                portfolio_id=p.portfolio_id,
                            )
                            batch_id = batch.batch_id

                        snapshot_id = None
                        if not config.dry_run and self.snapshot_repo is not None:
                            compliance_st = (
                                "BREACH_DETECTED" if report.needs_rebalancing else "COMPLIANCE_OK"
                            )
                            snapshot_id = await self.snapshot_repo.persist_audit_snapshot(
                                portfolio_id=p.portfolio_id,
                                as_of=started_at,
                                compliance_status=compliance_st,
                                report_payload={
                                    "portfolio_id": p.portfolio_id,
                                    "total_value": str(report.total_portfolio_value),
                                    "needs_rebalancing": report.needs_rebalancing,
                                    "breached_tickers": list(report.breached_tickers),
                                    "orders_count": orders_count,
                                    "fsm_batch_id": batch_id,
                                },
                                critical_alerts_count=len(report.breached_tickers),
                            )

                        result = PortfolioCloseProcessResult(
                            portfolio_id=p.portfolio_id,
                            status="SUCCESS",
                            total_portfolio_value=report.total_portfolio_value,
                            needs_rebalancing=report.needs_rebalancing,
                            breached_tickers=list(report.breached_tickers),
                            orders_generated_count=orders_count,
                            fsm_batch_id=batch_id,
                            snapshot_id=snapshot_id,
                            error_message=None,
                        )
                        with localcontext(prec=50):
                            total_net_worth += report.total_portfolio_value
                        total_orders += orders_count
                        portfolios_succeeded += 1
                        results.append(result)

                except Exception as exc:
                    portfolios_failed += 1
                    result = PortfolioCloseProcessResult(
                        portfolio_id=p.portfolio_id,
                        status="FAILED",
                        total_portfolio_value=None,
                        needs_rebalancing=False,
                        breached_tickers=[],
                        orders_generated_count=0,
                        fsm_batch_id=None,
                        snapshot_id=None,
                        error_message=str(exc)[:255],
                    )
                    results.append(result)

            portfolios_processed = len(portfolios)
            if portfolios_processed == 0:
                global_status = MarketCloseJobStatus.COMPLETED
            elif portfolios_failed == 0:
                global_status = MarketCloseJobStatus.COMPLETED
            elif portfolios_succeeded > 0:
                global_status = MarketCloseJobStatus.PARTIALLY_COMPLETED
            else:
                global_status = MarketCloseJobStatus.FAILED

            completed_at = datetime.now(UTC)
            if completed_at < started_at:
                completed_at = started_at
            duration_ms = max(0.0, (time.perf_counter() - t0) * 1000.0)

            with localcontext(prec=50):
                quantized_total_net_worth = total_net_worth.quantize(Decimal("0.0001"))

            return MarketCloseJobReport(
                job_id=job_id,
                target_date=config.target_date,
                trigger_type=config.trigger_type,
                status=global_status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round(duration_ms, 2),
                portfolios_processed=portfolios_processed,
                portfolios_succeeded=portfolios_succeeded,
                portfolios_failed=portfolios_failed,
                total_net_worth_processed=quantized_total_net_worth,
                total_rebalance_orders_generated=total_orders,
                dry_run=config.dry_run,
                results=results,
            )

        finally:
            if acquired_lock and lock_token and self.lock_manager is not None:
                await self.lock_manager.release(lock_key, lock_token)
