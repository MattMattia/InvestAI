"""
Unit tests for Alembic base migration 001_initial_schema, topological ordering,
Zero Schema Drift certification, full lifecycle idempotency, and offline SQL generation
(Module 8.1 - Phase 2: `backend/alembic/versions/001_initial_schema.py`).
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.database import Base

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.mark.unit
class TestAlembicMigrations(unittest.TestCase):
    """Unit test suite verifying base Alembic schema migration and reversibility."""

    def test_migration_001_revision_metadata_and_script_directory_head(self) -> None:
        """
        Verify that revision 001_initial_schema is registered as the base head,
        has no down_revision, has no broken dependencies/branches, and exposes
        valid callable upgrade and downgrade functions.
        """
        cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        script_dir = ScriptDirectory.from_config(cfg)
        head_rev = script_dir.get_current_head()
        self.assertEqual(head_rev, "001_initial_schema")

        rev = script_dir.get_revision("001_initial_schema")
        self.assertIsNotNone(rev)
        self.assertIsNone(rev.down_revision)
        self.assertIn(rev.dependencies, (None, []))
        self.assertTrue(hasattr(rev.module, "upgrade"))
        self.assertTrue(callable(rev.module.upgrade))
        self.assertTrue(hasattr(rev.module, "downgrade"))
        self.assertTrue(callable(rev.module.downgrade))

    def test_upgrade_and_downgrade_topological_table_order(self) -> None:
        """
        Verify that upgrade() creates the 7 domain tables following strict topological
        order (roots before dependents), and downgrade() drops tables in reverse
        order (leaves before roots), executing drop_index prior to drop_table.
        """
        cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        script_dir = ScriptDirectory.from_config(cfg)
        rev = script_dir.get_revision("001_initial_schema")

        created_tables: list[str] = []
        mock_op = MagicMock()
        mock_op.f = lambda x: x
        mock_op.create_table.side_effect = lambda name, *args, **kwargs: created_tables.append(name)

        with patch.object(rev.module, "op", mock_op):
            rev.module.upgrade()

        expected_upgrade_order = [
            "users",
            "assets",
            "portfolios",
            "market_bars",
            "holdings",
            "rebalance_orders",
            "risk_audit_snapshots",
        ]
        self.assertEqual(created_tables, expected_upgrade_order)

        # Verify topological constraints: roots must precede dependent tables
        self.assertLess(created_tables.index("users"), created_tables.index("portfolios"))
        self.assertLess(created_tables.index("assets"), created_tables.index("holdings"))
        self.assertLess(created_tables.index("portfolios"), created_tables.index("holdings"))
        self.assertLess(
            created_tables.index("portfolios"), created_tables.index("rebalance_orders")
        )
        self.assertLess(
            created_tables.index("portfolios"), created_tables.index("risk_audit_snapshots")
        )

        # Verify downgrade order and drop_index calls preceding drop_table
        actions: list[tuple[str, str]] = []
        dropped_tables: list[str] = []
        mock_op.drop_table.side_effect = lambda name, *args, **kwargs: (
            actions.append(("drop_table", name)),
            dropped_tables.append(name),
        )
        mock_op.drop_index.side_effect = lambda name, *args, **kwargs: actions.append(
            ("drop_index", kwargs.get("table_name", ""))
        )

        with patch.object(rev.module, "op", mock_op):
            rev.module.downgrade()

        expected_downgrade_order = [
            "risk_audit_snapshots",
            "rebalance_orders",
            "holdings",
            "market_bars",
            "portfolios",
            "assets",
            "users",
        ]
        self.assertEqual(dropped_tables, expected_downgrade_order)

        # Verify drop_index occurs before drop_table for every table with explicit indexes
        tables_with_indexes = [
            "risk_audit_snapshots",
            "rebalance_orders",
            "holdings",
            "market_bars",
            "portfolios",
            "assets",
            "users",
        ]
        for tbl in tables_with_indexes:
            drop_table_idx = actions.index(("drop_table", tbl))
            drop_index_indices = [
                i for i, a in enumerate(actions) if a[0] == "drop_index" and a[1] == tbl
            ]
            self.assertTrue(
                len(drop_index_indices) > 0,
                f"Table '{tbl}' should have had its explicit indexes dropped",
            )
            for di_idx in drop_index_indices:
                self.assertLess(
                    di_idx,
                    drop_table_idx,
                    f"Index for '{tbl}' must be dropped before dropping the table",
                )

    def test_programmatic_upgrade_head_creates_all_tables_columns_and_indexes(self) -> None:
        """
        Execute command.upgrade(head) against an isolated SQLite database and verify with
        sa.inspect that all 7 domain tables plus alembic_version are created with all
        required columns and explicit indexes.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_migration.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    table_names = inspector.get_table_names()
                    expected_tables = {
                        "alembic_version",
                        "users",
                        "assets",
                        "portfolios",
                        "market_bars",
                        "holdings",
                        "rebalance_orders",
                        "risk_audit_snapshots",
                    }
                    self.assertTrue(expected_tables.issubset(set(table_names)))

                    # Verify column existence in key tables
                    user_cols = {c["name"] for c in inspector.get_columns("users")}
                    self.assertTrue(
                        {
                            "id",
                            "email",
                            "hashed_password",
                            "role",
                            "is_active",
                            "full_name",
                        }.issubset(user_cols)
                    )

                    mb_cols = {c["name"] for c in inspector.get_columns("market_bars")}
                    self.assertTrue(
                        {
                            "id",
                            "ticker",
                            "timeframe",
                            "timestamp",
                            "open_price",
                            "close_price",
                            "volume",
                        }.issubset(mb_cols)
                    )

                    # Verify explicit indexes exist
                    user_indexes = {ix["name"] for ix in inspector.get_indexes("users")}
                    self.assertIn("ix_users_email", user_indexes)

                    mb_indexes = {ix["name"] for ix in inspector.get_indexes("market_bars")}
                    self.assertIn("ix_market_bars_ticker", mb_indexes)
                    self.assertIn("ix_market_bars_timestamp", mb_indexes)
            finally:
                engine.dispose()

    def test_migrated_schema_matches_orm_base_metadata_zero_drift(self) -> None:
        """
        Certify Zero Schema Drift: inspect SQLite database after upgrade(head) and compare
        columns, primary keys, and foreign keys 1:1 against Base.metadata.tables.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_drift.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            command.upgrade(cfg, "head")

            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    domain_tables = [
                        "users",
                        "assets",
                        "portfolios",
                        "market_bars",
                        "holdings",
                        "rebalance_orders",
                        "risk_audit_snapshots",
                    ]
                    for table_name in domain_tables:
                        orm_table = Base.metadata.tables[table_name]

                        # 1. Column names match 100%
                        orm_cols = {c.name for c in orm_table.columns}
                        db_cols = {c["name"] for c in inspector.get_columns(table_name)}
                        self.assertEqual(
                            orm_cols ^ db_cols,
                            set(),
                            f"Column drift detected in table '{table_name}': {orm_cols ^ db_cols}",
                        )

                        # 2. Primary key columns match 100%
                        orm_pk = {c.name for c in orm_table.primary_key.columns}
                        db_pk = set(inspector.get_pk_constraint(table_name)["constrained_columns"])
                        self.assertEqual(
                            orm_pk ^ db_pk,
                            set(),
                            f"Primary key drift detected in table '{table_name}': {orm_pk ^ db_pk}",
                        )

                        # 3. Foreign key constraints match 100%
                        orm_fks = {
                            (fk.parent.name, fk.column.table.name) for fk in orm_table.foreign_keys
                        }
                        db_fks = set()
                        for fk_info in inspector.get_foreign_keys(table_name):
                            for col_name in fk_info["constrained_columns"]:
                                db_fks.add((col_name, fk_info["referred_table"]))
                        self.assertEqual(
                            orm_fks ^ db_fks,
                            set(),
                            f"Foreign key drift detected in table '{table_name}': {orm_fks ^ db_fks}",
                        )
            finally:
                engine.dispose()

    def test_programmatic_full_cycle_upgrade_downgrade_base_and_reupgrade_idempotency(
        self,
    ) -> None:
        """
        Execute full lifecycle on single DB: upgrade('head') -> verify 7 tables ->
        downgrade('base') -> verify all 7 tables cleanly dropped ->
        upgrade('head') -> verify clean re-creation without orphaned artifacts.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_lifecycle.db"
            db_url = f"sqlite:///{db_path}"
            cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", db_url)

            domain_tables = {
                "users",
                "assets",
                "portfolios",
                "market_bars",
                "holdings",
                "rebalance_orders",
                "risk_audit_snapshots",
            }

            # 1. Initial Upgrade
            command.upgrade(cfg, "head")
            engine = sa.create_engine(db_url)
            try:
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    current_tables = set(inspector.get_table_names())
                    self.assertTrue(domain_tables.issubset(current_tables))

                # 2. Downgrade to base
                command.downgrade(cfg, "base")
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    remaining_tables = set(inspector.get_table_names())
                    self.assertEqual(domain_tables & remaining_tables, set())

                # 3. Re-upgrade to head (Idempotency check)
                command.upgrade(cfg, "head")
                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    recreated_tables = set(inspector.get_table_names())
                    self.assertTrue(domain_tables.issubset(recreated_tables))
            finally:
                engine.dispose()

    def test_offline_sql_generation_renders_valid_ddl_statements(self) -> None:
        """
        Execute command.upgrade(sql=True) in offline mode targeting PostgreSQL dialect,
        capturing standard output and certifying valid DDL statements for all 7 tables,
        exact numeric precision, JSONB types, and version tracking.
        """
        cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option(
            "sqlalchemy.url",
            "postgresql+asyncpg://investai_user:safe_pass@localhost:5432/investai_prod",
        )

        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            command.upgrade(cfg, "head", sql=True)

        sql_script = captured_stdout.getvalue()
        self.assertGreater(len(sql_script), 1000)

        domain_tables = [
            "users",
            "assets",
            "portfolios",
            "market_bars",
            "holdings",
            "rebalance_orders",
            "risk_audit_snapshots",
        ]
        for tbl in domain_tables:
            self.assertIn(f"CREATE TABLE {tbl}", sql_script, f"Missing CREATE TABLE for {tbl}")

        # Exact numeric precision
        self.assertIn("NUMERIC(18, 4)", sql_script)
        self.assertIn("NUMERIC(24, 4)", sql_script)

        # Native PostgreSQL JSONB variant
        self.assertIn("JSONB", sql_script)

        # Alembic version metadata
        self.assertIn("001_initial_schema", sql_script)
