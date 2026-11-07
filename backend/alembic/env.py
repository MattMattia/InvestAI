"""
Async Alembic migration environment for InvestAI (Module 8.1 - Phase 1).
Supports multi-dialect migrations (PostgreSQL + asyncpg / SQLite + aiosqlite),
declarative naming convention governance, and event-loop-safe execution.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from logging.config import fileConfig
from typing import Any

import app.models  # noqa: F401 - ensures all domain models register on Base.metadata
from alembic import context
from alembic.config import Config
from app.core.config import settings
from app.core.database import Base
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

PLACEHOLDER_DB_URL: str = "driver://user:pass@localhost/dbname"

# Target metadata for 'autogenerate' support bound to PostgreSQL naming conventions
target_metadata = Base.metadata


def normalize_async_database_url(url: str) -> str:
    """
    Validate and convert any database URL into its asynchronous driver equivalent:
    - postgres:// or postgresql:// -> postgresql+asyncpg://
    - sqlite:// -> sqlite+aiosqlite://
    - Preserves postgresql+asyncpg:// and sqlite+aiosqlite:// intact.
    Rejects empty strings and strings with ASCII control characters.
    """
    if not isinstance(url, str) or isinstance(url, bool):
        raise ValueError("Database URL must be a non-boolean string.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError("Database URL contains illegal control characters.")

    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Database URL cannot be empty.")

    if cleaned.startswith("postgres://"):
        return "postgresql+asyncpg://" + cleaned[len("postgres://") :]
    if cleaned.startswith("postgresql://"):
        return "postgresql+asyncpg://" + cleaned[len("postgresql://") :]
    if cleaned.startswith("sqlite://") and not cleaned.startswith("sqlite+aiosqlite://"):
        return "sqlite+aiosqlite://" + cleaned[len("sqlite://") :]

    return cleaned


def resolve_alembic_database_url(alembic_cfg: Config | None = None) -> str:
    """
    Resolve the active database URL for Alembic migrations, falling back to
    application settings if alembic.ini contains the default placeholder.
    Safely escapes '%' as '%%' in ConfigParser to avoid InterpolationSyntaxError
    with percent-encoded credentials.
    """
    raw_url: str | None = None
    if alembic_cfg is not None:
        try:
            raw_url = alembic_cfg.get_main_option("sqlalchemy.url")
        except Exception:
            raw_url = None

    if not raw_url or raw_url.strip() in ("", PLACEHOLDER_DB_URL):
        raw_url = settings.DATABASE_URL or settings.ASYNC_DATABASE_URI

    normalized = normalize_async_database_url(raw_url)

    if alembic_cfg is not None:
        escaped_url = normalized.replace("%", "%%")
        alembic_cfg.set_main_option("sqlalchemy.url", escaped_url)

    return normalized


def do_run_migrations(connection: Connection) -> None:
    """
    Configure migration context and execute pending revision steps inside a transaction.
    Enables render_as_batch=True for SQLite dialects to support table alterations.
    """
    is_sqlite = connection.dialect.name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline(alembic_cfg: Config | None = None) -> None:
    """
    Run migrations in 'offline' mode, generating SQL scripts directly
    without acquiring a live server connection.
    """
    cfg = alembic_cfg if alembic_cfg is not None else (getattr(context, "config", None))
    url = resolve_alembic_database_url(cfg)
    is_sqlite = url.startswith("sqlite")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=is_sqlite,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations(alembic_cfg: Config | None = None) -> None:
    """
    Asynchronously acquire an engine connection and run migrations.
    Reuses pre-injected connections without disposing them, or creates and
    disposes an ephemeral NullPool async engine.
    """
    cfg = alembic_cfg if alembic_cfg is not None else (getattr(context, "config", None))
    url = resolve_alembic_database_url(cfg)

    injected_conn: Any = None
    if cfg is not None and hasattr(cfg, "attributes"):
        injected_conn = cfg.attributes.get("connection")

    if injected_conn is not None:
        if hasattr(injected_conn, "run_sync"):
            await injected_conn.run_sync(do_run_migrations)
        else:
            do_run_migrations(injected_conn)
        return

    section_name = getattr(cfg, "config_ini_section", "alembic") if cfg is not None else "alembic"
    cfg_section = dict(cfg.get_section(section_name, {})) if cfg is not None else {}
    cfg_section["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online(alembic_cfg: Config | None = None) -> None:
    """
    Run migrations in 'online' mode. Safely handles running event loops
    via a separate thread executor to prevent 'asyncio.run() cannot be called
    from a running event loop' errors.
    """
    cfg = alembic_cfg if alembic_cfg is not None else (getattr(context, "config", None))

    injected_conn: Any = None
    if cfg is not None and hasattr(cfg, "attributes"):
        injected_conn = cfg.attributes.get("connection")

    if injected_conn is not None and not hasattr(injected_conn, "run_sync"):
        do_run_migrations(injected_conn)
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(run_async_migrations(cfg)))
            future.result()
    else:
        asyncio.run(run_async_migrations(cfg))


def _is_alembic_running() -> bool:
    """Detect whether this module was invoked directly by the Alembic CLI runner."""
    try:
        return hasattr(context, "config") and context.config is not None
    except Exception:
        return False


if _is_alembic_running():
    _cfg = context.config
    if _cfg.config_file_name is not None and os.path.exists(_cfg.config_file_name):
        fileConfig(_cfg.config_file_name, disable_existing_loggers=False)

    if context.is_offline_mode():
        run_migrations_offline(_cfg)
    else:
        run_migrations_online(_cfg)
