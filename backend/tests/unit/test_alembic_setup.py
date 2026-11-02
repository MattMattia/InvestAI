"""
Unit tests for Alembic async configuration, naming conventions, and migration environment
(Module 8.1 - Phase 1: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`).
"""
from __future__ import annotations

import asyncio
from configparser import ConfigParser
import importlib.util
from pathlib import Path
import sys
from typing import Any
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from alembic import context
from alembic.config import Config
import pytest
from sqlalchemy import MetaData, UniqueConstraint

from app.core.config import settings
from app.core.database import POSTGRES_NAMING_CONVENTION, Base
import app.models as domain_models
from app.models import (
    AssetModel,
    AuditLogModel,
    HoldingModel,
    MarketBarModel,
    OrderModel,
    PortfolioModel,
    RebalanceOrderModel,
    RiskAuditSnapshotModel,
    UserModel,
)

# Dynamically import backend/alembic/env.py as a module for isolated unit testing
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_PY_PATH = _BACKEND_DIR / "alembic" / "env.py"
_spec = importlib.util.spec_from_file_location("investai_alembic_env", _ENV_PY_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Could not load spec for Alembic env at {_ENV_PY_PATH}")
alembic_env: Any = importlib.util.module_from_spec(_spec)
sys.modules["investai_alembic_env"] = alembic_env
sys.modules["alembic_env"] = alembic_env
sys.modules["alembic.env"] = alembic_env
_spec.loader.exec_module(alembic_env)


@pytest.mark.unit
class TestAlembicSetup(unittest.TestCase):
    """Unit test suite verifying Module 8.1 Phase 1 async Alembic and metadata setup."""

    def test_alembic_ini_and_template_structure_and_zero_hardcoded_secrets(self) -> None:
        """
        Verify alembic.ini and script.py.mako file existence, correct '%(here)s/alembic'
        relative pathing, neutral placeholder URL without hardcoded secrets (CWE-798),
        and typed upgrade/downgrade mako template definitions.
        """
        ini_path = _BACKEND_DIR / "alembic.ini"
        mako_path = _BACKEND_DIR / "alembic" / "script.py.mako"

        self.assertTrue(ini_path.is_file(), f"alembic.ini missing at {ini_path}")
        self.assertTrue(mako_path.is_file(), f"script.py.mako missing at {mako_path}")

        parser = ConfigParser()
        parser.read(str(ini_path), encoding="utf-8")

        self.assertTrue(parser.has_section("alembic"))
        raw_script_location = parser.get("alembic", "script_location", raw=True)
        raw_prepend_path = parser.get("alembic", "prepend_sys_path", raw=True)
        raw_url = parser.get("alembic", "sqlalchemy.url", raw=True)

        self.assertEqual(raw_script_location, "%(here)s/alembic")
        self.assertEqual(raw_prepend_path, "%(here)s")
        self.assertEqual(raw_url, "driver://user:pass@localhost/dbname")
        self.assertEqual(alembic_env.PLACEHOLDER_DB_URL, "driver://user:pass@localhost/dbname")

        # Confirm no actual production secrets are embedded in alembic.ini
        ini_content = ini_path.read_text(encoding="utf-8")
        self.assertNotIn("secret", ini_content.lower().replace("change_this", ""))
        self.assertNotIn("postgres:postgres", ini_content)

        # Verify typed mako template contents
        mako_content = mako_path.read_text(encoding="utf-8")
        self.assertIn("def upgrade() -> None:", mako_content)
        self.assertIn("def downgrade() -> None:", mako_content)
        self.assertIn("from typing import Sequence, Union", mako_content)
        self.assertIn("from alembic import op", mako_content)
        self.assertIn("import sqlalchemy as sa", mako_content)

    def test_target_metadata_registers_all_core_domain_tables(self) -> None:
        """
        Verify that target_metadata in alembic/env.py is Base.metadata and contains
        all core domain entities (users, portfolios, assets, holdings, orders/rebalance_orders,
        audit_logs/risk_audit_snapshots, market_bars) with clean package re-exports.
        """
        self.assertIs(alembic_env.target_metadata, Base.metadata)
        tables = set(alembic_env.target_metadata.tables.keys())

        # Core tables must be present
        self.assertIn("users", tables)
        self.assertIn("portfolios", tables)
        self.assertIn("assets", tables)
        self.assertIn("holdings", tables)
        self.assertIn("market_bars", tables)
        self.assertTrue("rebalance_orders" in tables or "orders" in tables)
        self.assertTrue("risk_audit_snapshots" in tables or "audit_logs" in tables)

        # Domain alias re-exports in app.models
        self.assertIs(domain_models.OrderModel, RebalanceOrderModel)
        self.assertIs(domain_models.AuditLogModel, RiskAuditSnapshotModel)
        self.assertIs(OrderModel, RebalanceOrderModel)
        self.assertIs(AuditLogModel, RiskAuditSnapshotModel)
        self.assertIn("OrderModel", domain_models.__all__)
        self.assertIn("AuditLogModel", domain_models.__all__)
        self.assertIn("MarketBarModel", domain_models.__all__)

    def test_postgres_naming_conventions_enforced_on_metadata(self) -> None:
        """
        Verify Base.metadata.naming_convention strictly enforces POSTGRES_NAMING_CONVENTION
        keys ('ix', 'uq', 'ck', 'fk', 'pk') without altering existing explicit constraint names.
        """
        self.assertEqual(Base.metadata.naming_convention, POSTGRES_NAMING_CONVENTION)
        self.assertEqual(POSTGRES_NAMING_CONVENTION["ix"], "ix_%(column_0_label)s")
        self.assertEqual(POSTGRES_NAMING_CONVENTION["uq"], "uq_%(table_name)s_%(column_0_name)s")
        self.assertEqual(POSTGRES_NAMING_CONVENTION["ck"], "ck_%(table_name)s_%(constraint_name)s")
        self.assertEqual(
            POSTGRES_NAMING_CONVENTION["fk"],
            "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        )
        self.assertEqual(POSTGRES_NAMING_CONVENTION["pk"], "pk_%(table_name)s")

        # Explicit constraints from MarketBarModel must remain untouched
        uq_constraints = [
            c for c in MarketBarModel.__table__.constraints if isinstance(c, UniqueConstraint)
        ]
        uq_names = [c.name for c in uq_constraints]
        self.assertIn("uq_market_bar_ticker_tf_timestamp", uq_names)

    def test_normalize_and_resolve_url_handles_sync_schemes_and_percent_encoded_passwords(
        self,
    ) -> None:
        """
        Verify normalize_async_database_url upgrades sync schemes (postgres://, postgresql://,
        sqlite://) to async drivers (+asyncpg, +aiosqlite), rejects control characters,
        and resolve_alembic_database_url escapes '%' as '%%' in ConfigParser.
        """
        # 1. Scheme transformations
        self.assertEqual(
            alembic_env.normalize_async_database_url("postgres://usr:pwd@host:5432/db"),
            "postgresql+asyncpg://usr:pwd@host:5432/db",
        )
        self.assertEqual(
            alembic_env.normalize_async_database_url("postgresql://usr:pwd@host:5432/db"),
            "postgresql+asyncpg://usr:pwd@host:5432/db",
        )
        self.assertEqual(
            alembic_env.normalize_async_database_url("sqlite:///./local.db"),
            "sqlite+aiosqlite:///./local.db",
        )
        self.assertEqual(
            alembic_env.normalize_async_database_url("postgresql+asyncpg://usr:pwd@host/db"),
            "postgresql+asyncpg://usr:pwd@host/db",
        )
        self.assertEqual(
            alembic_env.normalize_async_database_url("sqlite+aiosqlite:///./local.db"),
            "sqlite+aiosqlite:///./local.db",
        )

        # 2. Defensive input rejection
        with self.assertRaises(ValueError):
            alembic_env.normalize_async_database_url("")
        with self.assertRaises(ValueError):
            alembic_env.normalize_async_database_url("   ")
        with self.assertRaises(ValueError):
            alembic_env.normalize_async_database_url(True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            alembic_env.normalize_async_database_url("postgresql://usr:pwd@host/db\x00malicious")

        # 3. Percent-encoded password escaping in ConfigParser
        test_cfg = Config()
        # When setting a URL with percent-encoding into settings, resolve_alembic_database_url
        # must escape '%' to '%%' in ConfigParser so get_main_option does not raise InterpolationSyntaxError
        with patch.object(
            settings,
            "DATABASE_URL",
            "postgresql://user:p%40ss%23word@localhost:5432/investai",
        ):
            test_cfg.set_main_option("sqlalchemy.url", alembic_env.PLACEHOLDER_DB_URL)
            resolved_url = alembic_env.resolve_alembic_database_url(test_cfg)
            self.assertEqual(
                resolved_url,
                "postgresql+asyncpg://user:p%40ss%23word@localhost:5432/investai",
            )
            # Getting main option from Config must succeed without InterpolationSyntaxError
            stored_raw = test_cfg.get_main_option("sqlalchemy.url")
            self.assertEqual(
                stored_raw,
                "postgresql+asyncpg://user:p%40ss%23word@localhost:5432/investai",
            )

    def test_run_migrations_offline_configures_context_with_compare_flags(self) -> None:
        """
        Verify run_migrations_offline resolves database URL, configures context
        with literal_binds=True, compare_type=True, compare_server_default=True,
        and executes inside a transaction.
        """
        test_cfg = Config()
        test_cfg.set_main_option("sqlalchemy.url", "sqlite:///./offline_test.db")

        with patch.object(context, "configure") as mock_configure, patch.object(
            context, "begin_transaction"
        ) as mock_begin_tx, patch.object(context, "run_migrations") as mock_run_mig:
            mock_begin_tx.return_value.__enter__ = MagicMock()
            mock_begin_tx.return_value.__exit__ = MagicMock(return_value=None)

            alembic_env.run_migrations_offline(test_cfg)

            mock_configure.assert_called_once()
            _, kwargs = mock_configure.call_args
            self.assertEqual(kwargs["url"], "sqlite+aiosqlite:///./offline_test.db")
            self.assertIs(kwargs["target_metadata"], Base.metadata)
            self.assertTrue(kwargs["literal_binds"])
            self.assertTrue(kwargs["compare_type"])
            self.assertTrue(kwargs["compare_server_default"])
            self.assertTrue(kwargs["render_as_batch"])
            self.assertEqual(kwargs["dialect_opts"], {"paramstyle": "named"})

            mock_begin_tx.assert_called_once()
            mock_run_mig.assert_called_once()

    def test_run_migrations_online_with_injected_connection_and_dialect_batch_toggle(self) -> None:
        """
        Verify run_migrations_online reuses pre-injected connections and toggles
        render_as_batch=True for SQLite dialects vs render_as_batch=False for PostgreSQL.
        """
        # 1. SQLite dialect -> render_as_batch=True
        mock_sqlite_conn = MagicMock()
        mock_sqlite_conn.dialect.name = "sqlite"
        del mock_sqlite_conn.run_sync  # synchronous connection

        cfg_sqlite = Config()
        cfg_sqlite.attributes["connection"] = mock_sqlite_conn

        with patch.object(context, "configure") as mock_configure, patch.object(
            context, "begin_transaction"
        ) as mock_begin_tx, patch.object(context, "run_migrations") as mock_run_mig:
            mock_begin_tx.return_value.__enter__ = MagicMock()
            mock_begin_tx.return_value.__exit__ = MagicMock(return_value=None)

            alembic_env.run_migrations_online(cfg_sqlite)

            mock_configure.assert_called_once()
            _, kwargs = mock_configure.call_args
            self.assertIs(kwargs["connection"], mock_sqlite_conn)
            self.assertIs(kwargs["target_metadata"], Base.metadata)
            self.assertTrue(kwargs["render_as_batch"])
            self.assertTrue(kwargs["compare_type"])
            self.assertTrue(kwargs["compare_server_default"])
            mock_run_mig.assert_called_once()

        # 2. PostgreSQL dialect -> render_as_batch=False
        mock_pg_conn = MagicMock()
        mock_pg_conn.dialect.name = "postgresql"
        del mock_pg_conn.run_sync

        cfg_pg = Config()
        cfg_pg.attributes["connection"] = mock_pg_conn

        with patch.object(context, "configure") as mock_configure, patch.object(
            context, "begin_transaction"
        ) as mock_begin_tx, patch.object(context, "run_migrations") as mock_run_mig:
            mock_begin_tx.return_value.__enter__ = MagicMock()
            mock_begin_tx.return_value.__exit__ = MagicMock(return_value=None)

            alembic_env.run_migrations_online(cfg_pg)

            mock_configure.assert_called_once()
            _, kwargs = mock_configure.call_args
            self.assertIs(kwargs["connection"], mock_pg_conn)
            self.assertFalse(kwargs["render_as_batch"])
            mock_run_mig.assert_called_once()

    def test_run_migrations_online_async_engine_works_inside_running_event_loop_and_disposes_on_error(
        self,
    ) -> None:
        """
        Verify run_migrations_online executes safely when invoked from inside an active
        running event loop via ThreadPoolExecutor, and guarantees connectable.dispose()
        runs in the finally block even if a migration step raises an exception.
        """
        test_cfg = Config()
        test_cfg.set_main_option("sqlalchemy.url", "sqlite+aiosqlite:///:memory:")

        # 1. Verify connectable.dispose() runs in finally block on error
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_conn = MagicMock()
        mock_conn.run_sync = AsyncMock(side_effect=RuntimeError("Migration step failed"))

        class _MockConnectContext:
            async def __aenter__(self) -> Any:
                return mock_conn

            async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                return None

        mock_engine.connect.return_value = _MockConnectContext()

        with patch.object(
            alembic_env,
            "async_engine_from_config",
            return_value=mock_engine,
        ):
            with self.assertRaises(RuntimeError) as ctx_err:
                alembic_env.run_migrations_online(test_cfg)

            self.assertIn("Migration step failed", str(ctx_err.exception))
            mock_engine.dispose.assert_awaited_once()

        # 2. Verify invocation from inside an active running event loop works without RuntimeError
        async def _inside_loop_caller() -> None:
            # We are inside an active loop. run_migrations_online must delegate to ThreadPoolExecutor
            mock_engine_ok = MagicMock()
            mock_engine_ok.dispose = AsyncMock()
            mock_conn_ok = MagicMock()
            mock_conn_ok.run_sync = AsyncMock(return_value=None)

            class _MockConnectOk:
                async def __aenter__(self) -> Any:
                    return mock_conn_ok

                async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                    return None

            mock_engine_ok.connect.return_value = _MockConnectOk()

            with patch.object(
                alembic_env,
                "async_engine_from_config",
                return_value=mock_engine_ok,
            ):
                alembic_env.run_migrations_online(test_cfg)
                mock_engine_ok.dispose.assert_awaited_once()

        asyncio.run(_inside_loop_caller())
