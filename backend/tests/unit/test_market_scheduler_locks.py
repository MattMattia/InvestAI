"""
Unit tests for Distributed Locks (InMemory and Redis), Snapshot Persistence,
and Asynchronous Concurrency Isolation in Market Close Scheduler
(Module 8.2 - Phase 2: `backend/tests/unit/test_market_scheduler_locks.py`).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import time
from typing import Any
import unittest
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.services.market_scheduler import (
    BYMACalendarService,
    InMemoryLockManager,
    LockAcquireResult,
    MarketCloseJobConfig,
    MarketCloseJobStatus,
    MarketCloseSchedulerService,
    MarketCloseTriggerType,
    PortfolioCloseInput,
    RedisLockManager,
    SnapshotPersistenceProtocol,
)
from app.domain.services.tolerance_band_rebalancer import (
    AssetTargetBandSpec,
    BandType,
    RebalancePositionInput,
    ToleranceBandRebalancerConfig,
)


class MockSnapshotRepository:
    """Mock implementation of SnapshotPersistenceProtocol for unit testing."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    async def persist_audit_snapshot(
        self,
        portfolio_id: str,
        as_of: datetime,
        compliance_status: str,
        report_payload: dict[str, Any],
        critical_alerts_count: int = 0,
    ) -> str:
        snapshot_id = f"snap-{portfolio_id}-{len(self.snapshots) + 1}"
        self.snapshots.append({
            "snapshot_id": snapshot_id,
            "portfolio_id": portfolio_id,
            "as_of": as_of,
            "compliance_status": compliance_status,
            "report_payload": report_payload,
            "critical_alerts_count": critical_alerts_count,
        })
        return snapshot_id


@pytest.mark.unit
class TestMarketSchedulerLocks(unittest.IsolatedAsyncioTestCase):
    """Unit test suite verifying InMemoryLockManager, RedisLockManager, and async scheduler locking."""

    async def asyncSetUp(self) -> None:
        self.lock_manager = InMemoryLockManager()
        self.calendar = BYMACalendarService()
        self.snapshot_repo = MockSnapshotRepository()
        self.scheduler = MarketCloseSchedulerService(
            calendar_service=self.calendar,
            lock_manager=self.lock_manager,
            snapshot_repo=self.snapshot_repo,
        )

    async def test_in_memory_lock_acquire_and_release_success(self) -> None:
        """
        Verify that an in-memory lock is successfully acquired with a UUID token,
        and that releasing with the exact token succeeds and clears the lock.
        """
        key = "lock:test:resource:1"
        res = await self.lock_manager.acquire(key, ttl_seconds=300)

        self.assertTrue(res.acquired)
        self.assertEqual(res.lock_key, key)
        self.assertIsNotNone(res.token)
        self.assertEqual(res.ttl_seconds, 300)
        self.assertIsNone(res.error_message)

        # Successful release with matching token
        released = await self.lock_manager.release(key, res.token)
        self.assertTrue(released)

        # Subsequent release fails because lock is already cleared
        released_again = await self.lock_manager.release(key, res.token)
        self.assertFalse(released_again)

    async def test_in_memory_lock_prevents_concurrent_acquisition_and_token_isolation(
        self,
    ) -> None:
        """
        Verify mutual exclusion: concurrent acquisition attempts on the same key fail,
        and releasing with an invalid or mismatched token is rejected without dropping the lock.
        """
        key = "lock:test:resource:2"
        res1 = await self.lock_manager.acquire(key, ttl_seconds=600)
        self.assertTrue(res1.acquired)

        # Concurrent acquisition attempt while active
        res2 = await self.lock_manager.acquire(key, ttl_seconds=600)
        self.assertFalse(res2.acquired)
        self.assertIsNone(res2.token)
        self.assertEqual(res2.error_message, "Lock already held")

        # Attempt release with wrong token
        wrong_release = await self.lock_manager.release(key, "invalid-bogus-token-uuid")
        self.assertFalse(wrong_release)

        # Verify lock is still held by original holder
        res3 = await self.lock_manager.acquire(key, ttl_seconds=600)
        self.assertFalse(res3.acquired)

        # Release with correct token succeeds
        correct_release = await self.lock_manager.release(key, res1.token)
        self.assertTrue(correct_release)

    async def test_in_memory_lock_allows_reacquisition_after_release(self) -> None:
        """
        Verify that once a lock is explicitly released, any coroutine can acquire
        it with a fresh unique token.
        """
        key = "lock:test:resource:3"
        first_acquire = await self.lock_manager.acquire(key, ttl_seconds=120)
        self.assertTrue(first_acquire.acquired)
        token_a = first_acquire.token

        await self.lock_manager.release(key, token_a)

        second_acquire = await self.lock_manager.acquire(key, ttl_seconds=120)
        self.assertTrue(second_acquire.acquired)
        token_b = second_acquire.token

        self.assertNotEqual(token_a, token_b)
        await self.lock_manager.release(key, token_b)

    async def test_in_memory_lock_auto_expires_after_ttl_using_monotonic_time(self) -> None:
        """
        Verify that locks automatically expire after their TTL based on monotonic time,
        allowing seamless re-acquisition without deadlock.
        """
        key = "lock:test:resource:expiry"
        base_time = 1000.0

        with patch("time.monotonic", return_value=base_time):
            acquire_res = await self.lock_manager.acquire(key, ttl_seconds=10)
            self.assertTrue(acquire_res.acquired)

        # Before expiry: acquisition rejected
        with patch("time.monotonic", return_value=base_time + 5.0):
            rejected_res = await self.lock_manager.acquire(key, ttl_seconds=10)
            self.assertFalse(rejected_res.acquired)

        # After expiry: acquisition succeeds and overrides the expired lock
        with patch("time.monotonic", return_value=base_time + 15.0):
            expired_res = await self.lock_manager.acquire(key, ttl_seconds=10)
            self.assertTrue(expired_res.acquired)
            self.assertNotEqual(acquire_res.token, expired_res.token)

    async def test_scheduler_async_acquires_lock_and_releases_in_finally_on_success_and_error(
        self,
    ) -> None:
        """
        Verify that execute_market_close_async:
        1. Acquires the distributed lock and persists snapshots upon success.
        2. Guarantees lock release in the finally block even if an exception occurs.
        """
        trading_day = date(2026, 10, 14)  # Wednesday
        config = MarketCloseJobConfig(
            target_date=trading_day,
            trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
            base_currency="USD",
        )
        lock_key = f"lock:market_close:{trading_day.isoformat()}:USD"

        # 1. Success case with snapshot persistence
        portfolio = PortfolioCloseInput(
            portfolio_id="port-async-001",
            cash_balance=Decimal("10000.0000"),
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

        report = await self.scheduler.execute_market_close_async(config, [portfolio])
        self.assertEqual(report.status, MarketCloseJobStatus.COMPLETED)
        self.assertEqual(report.portfolios_succeeded, 1)
        self.assertIsNotNone(report.results[0].snapshot_id)
        self.assertEqual(len(self.snapshot_repo.snapshots), 1)

        # Verify lock was released in finally: another acquire immediately succeeds
        check_lock = await self.lock_manager.acquire(lock_key, ttl_seconds=60)
        self.assertTrue(check_lock.acquired, "Lock was not released after successful execution")
        await self.lock_manager.release(lock_key, check_lock.token)

        # 2. Error case: ensure lock is released when an internal failure occurs
        with patch.object(
            self.scheduler.calendar, "is_trading_day", side_effect=RuntimeError("Simulated DB failure")
        ):
            with self.assertRaises(RuntimeError):
                await self.scheduler.execute_market_close_async(config, [portfolio])

        # Verify lock was released in finally even on unhandled exception
        check_lock_after_error = await self.lock_manager.acquire(lock_key, ttl_seconds=60)
        self.assertTrue(
            check_lock_after_error.acquired, "Lock was leaked following unhandled exception"
        )
        await self.lock_manager.release(lock_key, check_lock_after_error.token)

    async def test_scheduler_async_skips_when_concurrent_lock_is_active_and_force_rerun_false(
        self,
    ) -> None:
        """
        Verify concurrency isolation: if another worker holds the market-close lock,
        the scheduler immediately returns SKIPPED_ALREADY_RUNNING without processing portfolios,
        unless force_rerun=True is specified.
        """
        trading_day = date(2026, 10, 14)
        config = MarketCloseJobConfig(
            target_date=trading_day,
            trigger_type=MarketCloseTriggerType.AUTOMATIC_SCHEDULE,
            force_rerun=False,
            base_currency="USD",
        )
        lock_key = f"lock:market_close:{trading_day.isoformat()}:USD"

        # Pre-acquire the lock simulating a concurrent replica running the job
        held_lock = await self.lock_manager.acquire(lock_key, ttl_seconds=600)
        self.assertTrue(held_lock.acquired)

        portfolio = PortfolioCloseInput(
            portfolio_id="port-concurrent-001",
            cash_balance=Decimal("25000.00"),
        )

        # Attempt to run market close while lock is held
        report = await self.scheduler.execute_market_close_async(config, [portfolio])
        self.assertEqual(report.status, MarketCloseJobStatus.SKIPPED_ALREADY_RUNNING)
        self.assertEqual(report.portfolios_processed, 0)
        self.assertEqual(report.results, [])

        # Release held lock
        await self.lock_manager.release(lock_key, held_lock.token)

        # Test RedisLockManager basic mock verification for protocol compliance
        mock_redis = AsyncMock()
        mock_redis.set.return_value = True
        mock_redis.eval.return_value = 1
        redis_lock = RedisLockManager(mock_redis)

        r_acq = await redis_lock.acquire("redis:lock:test", ttl_seconds=300)
        self.assertTrue(r_acq.acquired)
        mock_redis.set.assert_awaited_once()

        r_rel = await redis_lock.release("redis:lock:test", r_acq.token)
        self.assertTrue(r_rel)
        mock_redis.eval.assert_awaited_once()

