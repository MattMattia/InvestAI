import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

is_sqlite = settings.ASYNC_DATABASE_URI.startswith("sqlite")

engine_kwargs = {
    "echo": False,
    "future": True,
}

if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

# Configure asynchronous SQLAlchemy 2.0 Engine
async_engine = create_async_engine(
    settings.ASYNC_DATABASE_URI,
    **engine_kwargs,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


POSTGRES_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
    Base Declarative class for all SQLAlchemy 2.0 ORM models in InvestAI.
    """

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


_db_initialized = False
_init_lock = asyncio.Lock()


async def init_db() -> None:
    """
    Initializes the database schema by ensuring all tables exist.
    Essential for local SQLite zero-config development.
    """
    global _db_initialized
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if is_sqlite:

            def _check_and_migrate_sqlite(sync_conn):
                res = sync_conn.exec_driver_sql("PRAGMA table_info(portfolios)").fetchall()
                col_names = [r[1] for r in res]
                if col_names and "investor_profile" not in col_names:
                    sync_conn.exec_driver_sql(
                        "ALTER TABLE portfolios ADD COLUMN investor_profile VARCHAR(50) DEFAULT 'MODERATE' NOT NULL"
                    )

                asset_res = sync_conn.exec_driver_sql("PRAGMA table_info(assets)").fetchall()
                asset_cols = {r[1] for r in asset_res}
                if asset_cols:
                    asset_migrations = [
                        ("history_start_date", "VARCHAR(20) DEFAULT '2016-11-01'"),
                        ("history_years_available", "FLOAT DEFAULT 10.0 NOT NULL"),
                        ("data_points_count", "INTEGER DEFAULT 2520 NOT NULL"),
                        ("cagr_annualized", "FLOAT DEFAULT 0.12 NOT NULL"),
                        ("volatility_annualized", "FLOAT DEFAULT 0.25 NOT NULL"),
                        ("sharpe_ratio", "FLOAT DEFAULT 0.48 NOT NULL"),
                        ("sortino_ratio", "FLOAT DEFAULT 0.68 NOT NULL"),
                        ("max_drawdown", "FLOAT DEFAULT 0.28 NOT NULL"),
                        ("beta_market", "FLOAT DEFAULT 1.0 NOT NULL"),
                        ("var_95_daily", "FLOAT DEFAULT 0.026 NOT NULL"),
                        ("pe_ratio", "FLOAT"),
                        ("pb_ratio", "FLOAT"),
                        ("roe_pct", "FLOAT"),
                        ("debt_to_equity", "FLOAT"),
                        ("dividend_yield_pct", "FLOAT"),
                        ("market_cap_usd", "FLOAT"),
                        ("ytm_tir_pct", "FLOAT"),
                        ("modified_duration", "FLOAT"),
                        ("parity_pct", "FLOAT"),
                        ("metrics_payload", "JSON"),
                        ("metrics_updated_at", "DATETIME"),
                    ]
                    for col_name, col_def in asset_migrations:
                        if col_name not in asset_cols:
                            sync_conn.exec_driver_sql(
                                f"ALTER TABLE assets ADD COLUMN {col_name} {col_def}"
                            )

            await conn.run_sync(_check_and_migrate_sqlite)
    _db_initialized = True


async def ensure_db_ready() -> None:
    """Lazily ensures database tables exist even outside of lifespan hooks."""
    global _db_initialized
    if not _db_initialized:
        async with _init_lock:
            if not _db_initialized:
                await init_db()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an asynchronous database session
    and guarantees its clean closure after request completion.
    """
    await ensure_db_ready()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
