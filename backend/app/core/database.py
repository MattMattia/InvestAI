import asyncio
from typing import AsyncGenerator
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


class Base(DeclarativeBase):
    """
    Base Declarative class for all SQLAlchemy 2.0 ORM models in InvestAI.
    """
    pass


_db_initialized = False
_init_lock = asyncio.Lock()


async def init_db() -> None:
    """
    Initializes the database schema by ensuring all tables exist.
    Essential for local SQLite zero-config development.
    """
    global _db_initialized
    import app.models  # ensure models are discovered
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
