"""
Integration tests for Alembic migration lifecycle, referential integrity (CASCADE / RESTRICT),
compound unique constraints, transactional rollback atomicity, and schema roundtrip
(Module 8.1 - Phase 3: `backend/tests/integration/test_alembic_lifecycle.py`).
"""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_DOMAIN_TABLES = {
    "users",
    "assets",
    "portfolios",
    "market_bars",
    "holdings",
    "rebalance_orders",
    "risk_audit_snapshots",
}


@pytest.mark.integration
class TestAlembicLifecycleIntegration(unittest.TestCase):
    """Integration test suite certifying Alembic DDL lifecycle and relational integrity."""

    def test_alembic_lifecycle_upgrade_head_applies_and_stamps_version(self) -> None:
        """
        Execute command.upgrade(head) against an isolated database and verify that
        the version stored in alembic_version matches ScriptDirectory head and
        MigrationContext.get_current_revision().
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_upgrade.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            script_dir = ScriptDirectory.from_config(cfg)
            expected_head = script_dir.get_current_head()
            self.assertIsNotNone(expected_head)

            command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    # 1. Verify version via MigrationContext
                    mc = MigrationContext.configure(conn)
                    current_rev = mc.get_current_revision()
                    self.assertEqual(current_rev, expected_head)

                    # 2. Verify version directly via SQL query
                    db_version = conn.execute(
                        sa.text("SELECT version_num FROM alembic_version")
                    ).scalar_one_or_none()
                    self.assertEqual(db_version, expected_head)

                    # 3. Verify all 7 domain tables exist
                    inspector = sa.inspect(conn)
                    existing_tables = set(inspector.get_table_names())
                    self.assertTrue(_DOMAIN_TABLES.issubset(existing_tables))
            finally:
                engine.dispose()

    def test_alembic_lifecycle_downgrade_base_removes_all_domain_tables_and_clears_version(
        self,
    ) -> None:
        """
        Execute command.upgrade(head) followed by command.downgrade(base) and verify
        that all 7 domain tables are dropped and alembic_version is cleared.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_downgrade.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            command.upgrade(cfg, "head")
            command.downgrade(cfg, "base")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    remaining_tables = set(inspector.get_table_names())

                    # Verify no domain tables remain
                    self.assertEqual(
                        _DOMAIN_TABLES & remaining_tables,
                        set(),
                        "Domain tables were not fully dropped during downgrade",
                    )

                    # Verify alembic_version has no active revision
                    mc = MigrationContext.configure(conn)
                    self.assertIsNone(mc.get_current_revision())

                    version_count = conn.execute(
                        sa.text("SELECT COUNT(*) FROM alembic_version")
                    ).scalar()
                    self.assertEqual(version_count, 0)
            finally:
                engine.dispose()

    def test_alembic_lifecycle_full_roundtrip_upgrade_downgrade_upgrade_idempotency(
        self,
    ) -> None:
        """
        Execute full roundtrip upgrade('head') -> downgrade('base') -> upgrade('head')
        followed by an idempotent second upgrade('head') call, verifying index preservation
        and zero duplicate schema collision errors.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_roundtrip.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            # Roundtrip 1: upgrade -> downgrade -> upgrade
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "base")
            command.upgrade(cfg, "head")

            # Roundtrip 2: Idempotent no-op execution on already migrated head
            command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    current_tables = set(inspector.get_table_names())
                    self.assertTrue(_DOMAIN_TABLES.issubset(current_tables))

                    # Verify key indexes survived clean recreation
                    user_indexes = {ix["name"] for ix in inspector.get_indexes("users")}
                    self.assertIn("ix_users_email", user_indexes)

                    port_indexes = {ix["name"] for ix in inspector.get_indexes("portfolios")}
                    self.assertIn("ix_portfolios_user_id", port_indexes)

                    holding_indexes = {ix["name"] for ix in inspector.get_indexes("holdings")}
                    self.assertIn("ix_holdings_portfolio_id", holding_indexes)
                    self.assertIn("ix_holdings_asset_ticker", holding_indexes)

                    mb_indexes = {ix["name"] for ix in inspector.get_indexes("market_bars")}
                    self.assertIn("ix_market_bars_ticker", mb_indexes)
                    self.assertIn("ix_market_bars_timestamp", mb_indexes)
            finally:
                engine.dispose()

    def test_alembic_lifecycle_foreign_key_enforcement_cascade_and_restrict(
        self,
    ) -> None:
        """
        Verify real engine-level foreign key enforcement with PRAGMA foreign_keys=ON:
        1. Rejecting invalid parent foreign keys on insert.
        2. Rejecting asset deletion when referenced by holdings (RESTRICT).
        3. Cascading user deletion to portfolios and holdings (CASCADE).
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_fk_enforcement.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    conn.exec_driver_sql("PRAGMA foreign_keys=ON")

                    user_id = str(uuid.uuid4())
                    now_iso = datetime.now(UTC).isoformat()

                    # Insert valid User and Asset
                    conn.execute(
                        sa.text("""
                            INSERT INTO users (id, email, hashed_password, full_name, is_active, role, created_at, updated_at, investor_profile)
                            VALUES (:id, 'fk_test@investai.com', 'h_pw', 'FK User', 1, 'TRADER', :now, :now, 'AGGRESSIVE')
                        """),
                        {"id": user_id, "now": now_iso},
                    )

                    conn.execute(
                        sa.text("""
                            INSERT INTO assets (ticker, name, asset_type, currency, sector, market)
                            VALUES ('GGAL', 'Grupo Financiero Galicia', 'EQUITY', 'ARS', 'FINANCIAL', 'BYMA')
                        """)
                    )

                    portfolio_id = str(uuid.uuid4())
                    conn.execute(
                        sa.text("""
                            INSERT INTO portfolios (id, user_id, name, investor_profile, cash_balance_ars, cash_balance_usd, updated_at)
                            VALUES (:id, :uid, 'FK Portfolio', 'AGGRESSIVE', 50000.0, 100.0, :now)
                        """),
                        {"id": portfolio_id, "uid": user_id, "now": now_iso},
                    )

                    conn.execute(
                        sa.text("""
                            INSERT INTO holdings (portfolio_id, asset_ticker, quantity, average_buy_price, current_price)
                            VALUES (:pid, 'GGAL', 200.0, 3100.0, 3350.0)
                        """),
                        {"pid": portfolio_id},
                    )
                    conn.commit()

                    # Rule 1: Inserting portfolio with non-existent user_id raises IntegrityError
                    with self.assertRaises(IntegrityError):
                        with conn.begin_nested():
                            conn.execute(
                                sa.text("""
                                    INSERT INTO portfolios (id, user_id, name, investor_profile, cash_balance_ars, cash_balance_usd, updated_at)
                                    VALUES (:id, :uid, 'Invalid User Portfolio', 'MODERATE', 0.0, 0.0, :now)
                                """),
                                {"id": str(uuid.uuid4()), "uid": str(uuid.uuid4()), "now": now_iso},
                            )

                    # Rule 2: Deleting 'GGAL' asset referenced by holding (RESTRICT) raises IntegrityError
                    with self.assertRaises(IntegrityError):
                        with conn.begin_nested():
                            conn.execute(
                                sa.text("DELETE FROM assets WHERE ticker = :ticker"),
                                {"ticker": "GGAL"},
                            )

                    # Rule 3: Deleting user (CASCADE) cascades to delete portfolio and holding
                    conn.execute(
                        sa.text("DELETE FROM users WHERE id = :id"),
                        {"id": user_id},
                    )
                    conn.commit()

                    p_count = conn.execute(sa.text("SELECT COUNT(*) FROM portfolios")).scalar()
                    h_count = conn.execute(sa.text("SELECT COUNT(*) FROM holdings")).scalar()
                    self.assertEqual(p_count, 0, "CASCADE failed: portfolio was not deleted")
                    self.assertEqual(h_count, 0, "CASCADE failed: holding was not deleted")
            finally:
                engine.dispose()

    def test_alembic_lifecycle_unique_constraints_and_jsonb_roundtrip(self) -> None:
        """
        Verify compound and indexed uniqueness enforcement, structured JSON payload
        storage/retrieval, and decimal numeric precision roundtrip.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_constraints.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    now_iso = datetime.now(UTC).isoformat()
                    u1_id = str(uuid.uuid4())
                    u2_id = str(uuid.uuid4())

                    # Insert initial user
                    conn.execute(
                        sa.text("""
                            INSERT INTO users (id, email, hashed_password, full_name, is_active, role, created_at, updated_at, investor_profile)
                            VALUES (:id, 'unique_test@investai.com', 'h1', 'First User', 1, 'VIEWER', :now, :now, 'MODERATE')
                        """),
                        {"id": u1_id, "now": now_iso},
                    )
                    conn.commit()

                    # Uniqueness 1: Duplicate email must raise IntegrityError
                    with self.assertRaises(IntegrityError):
                        with conn.begin_nested():
                            conn.execute(
                                sa.text("""
                                    INSERT INTO users (id, email, hashed_password, full_name, is_active, role, created_at, updated_at, investor_profile)
                                    VALUES (:id, 'unique_test@investai.com', 'h2', 'Second User', 1, 'VIEWER', :now, :now, 'MODERATE')
                                """),
                                {"id": u2_id, "now": now_iso},
                            )

                    # Insert initial market bar
                    bar_id1 = str(uuid.uuid4())
                    bar_id2 = str(uuid.uuid4())
                    bar_ts = "2026-10-15T18:00:00+00:00"
                    conn.execute(
                        sa.text("""
                            INSERT INTO market_bars (id, ticker, timeframe, timestamp, open_price, high_price, low_price, close_price, volume, vwap)
                            VALUES (:id, 'YPFD', '1d', :ts, 25000.1234, 25500.5678, 24800.0000, 25200.4321, 500000.9876, 25150.0000)
                        """),
                        {"id": bar_id1, "ts": bar_ts},
                    )
                    conn.commit()

                    # Uniqueness 2: Duplicate compound (ticker, timeframe, timestamp) must raise IntegrityError
                    with self.assertRaises(IntegrityError):
                        with conn.begin_nested():
                            conn.execute(
                                sa.text("""
                                    INSERT INTO market_bars (id, ticker, timeframe, timestamp, open_price, high_price, low_price, close_price, volume, vwap)
                                    VALUES (:id, 'YPFD', '1d', :ts, 25100.0, 25600.0, 24900.0, 25300.0, 100000.0, 25200.0)
                                """),
                                {"id": bar_id2, "ts": bar_ts},
                            )

                    # Numeric precision verification
                    bar_row = conn.execute(
                        sa.text(
                            "SELECT open_price, high_price, volume FROM market_bars WHERE id = :id"
                        ),
                        {"id": bar_id1},
                    ).one()
                    self.assertEqual(Decimal(str(bar_row[0])), Decimal("25000.1234"))
                    self.assertEqual(Decimal(str(bar_row[1])), Decimal("25500.5678"))
                    self.assertEqual(Decimal(str(bar_row[2])), Decimal("500000.9876"))

                    # Structured JSON report payload roundtrip
                    port_id = str(uuid.uuid4())
                    conn.execute(
                        sa.text("""
                            INSERT INTO portfolios (id, user_id, name, investor_profile, cash_balance_ars, cash_balance_usd, updated_at)
                            VALUES (:id, :uid, 'Audit Portfolio', 'MODERATE', 0.0, 0.0, :now)
                        """),
                        {"id": port_id, "uid": u1_id, "now": now_iso},
                    )

                    snapshot_id = str(uuid.uuid4())
                    payload_dict = {
                        "rules_evaluated": [
                            {"rule": "MAX_EQUITY_EXPOSURE", "passed": True, "value": 0.65},
                            {"rule": "MIN_LIQUIDITY_BUFFER", "passed": True, "value": 0.05},
                        ],
                        "summary": {"score": 100, "status": "APPROVED"},
                    }
                    conn.execute(
                        sa.text("""
                            INSERT INTO risk_audit_snapshots (id, portfolio_id, compliance_status, total_rules_evaluated, critical_alerts_count, report_payload, notification_status, created_at)
                            VALUES (:id, :pid, 'COMPLIANT', 2, 0, :payload, 'DELIVERED', :now)
                        """),
                        {
                            "id": snapshot_id,
                            "pid": port_id,
                            "payload": json.dumps(payload_dict),
                            "now": now_iso,
                        },
                    )
                    conn.commit()

                    raw_payload = conn.execute(
                        sa.text("SELECT report_payload FROM risk_audit_snapshots WHERE id = :id"),
                        {"id": snapshot_id},
                    ).scalar()
                    recovered = (
                        json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    )
                    self.assertEqual(recovered["summary"]["status"], "APPROVED")
                    self.assertEqual(len(recovered["rules_evaluated"]), 2)
            finally:
                engine.dispose()

    def test_alembic_lifecycle_transactional_atomicity_on_mid_migration_failure(
        self,
    ) -> None:
        """
        Verify that a failure encountered during migration execution triggers a rollback
        in the migration transaction, leaving zero domain tables committed and no version
        stamped in alembic_version.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_tx_rollback.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            orig_run_migrations = MigrationContext.run_migrations

            def faulty_run_migrations(ctx_self: MigrationContext, **kw: Any) -> None:
                orig_migrations_fn = ctx_self._migrations_fn

                def failing_migrations_wrapper(heads: Any, ctx: Any) -> Any:
                    assert orig_migrations_fn is not None
                    for step in orig_migrations_fn(heads, ctx):

                        def failing_step_fn(**k: Any) -> None:
                            raise RuntimeError(
                                "Simulated catastrophic mid-migration hardware fault"
                            )

                        step.migration_fn = failing_step_fn
                        yield step

                ctx_self._migrations_fn = failing_migrations_wrapper
                return orig_run_migrations(ctx_self, **kw)

            with patch.object(MigrationContext, "run_migrations", faulty_run_migrations):
                with self.assertRaises(RuntimeError):
                    command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    tables_after_failure = set(inspector.get_table_names())

                    # Verify no domain tables were left created
                    self.assertEqual(
                        _DOMAIN_TABLES & tables_after_failure,
                        set(),
                        "Failure rollback leaked domain tables",
                    )

                    # Verify no revision stamp was recorded
                    mc = MigrationContext.configure(conn)
                    self.assertIsNone(
                        mc.get_current_revision(),
                        "Version was stamped despite migration failure",
                    )

                    if "alembic_version" in tables_after_failure:
                        row_count = conn.execute(
                            sa.text("SELECT COUNT(*) FROM alembic_version")
                        ).scalar()
                        self.assertEqual(row_count, 0)
            finally:
                engine.dispose()
