import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, MetaData, inspect
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


ALEMBIC_INI_PATH: Path = Path(__file__).resolve().parents[2] / "alembic.ini"
BASELINE_REVISION: str = "001_initial_schema"

_db_initialized = False
_init_lock = asyncio.Lock()


class SchemaDriftError(RuntimeError):
    """Raised when an unversioned legacy database does not match the ORM schema."""


def build_alembic_config() -> Config:
    """Build the Alembic config from backend/alembic.ini, independent of the current cwd."""
    if not ALEMBIC_INI_PATH.is_file():
        raise RuntimeError(f"Alembic configuration not found at {ALEMBIC_INI_PATH}")
    return Config(str(ALEMBIC_INI_PATH))


def _legacy_schema_drift(sync_conn: Connection) -> list[str] | None:
    """
    Detect databases created by the former ``create_all`` bootstrap (no ``alembic_version``).

    Returns ``None`` when the database is versioned or empty (normal upgrade path), otherwise
    the list of structural differences against the ORM metadata (empty list = in sync).
    """
    tables = set(inspect(sync_conn).get_table_names())
    if "alembic_version" in tables or not tables & set(Base.metadata.tables):
        return None

    structural_ops = {"add_table", "remove_table", "add_column", "remove_column"}
    drift: list[str] = []
    for diff in compare_metadata(MigrationContext.configure(sync_conn), Base.metadata):
        if isinstance(diff, tuple) and diff[0] in structural_ops:
            if diff[0] in ("add_table", "remove_table"):
                drift.append(f"{diff[0]} {diff[1].name}")
            else:
                drift.append(f"{diff[0]} {diff[2]}.{diff[3].name}")
    return drift


def _run_migrations(legacy_in_sync: bool) -> None:
    """Run Alembic synchronously (called from a worker thread, outside the event loop)."""
    cfg = build_alembic_config()
    if legacy_in_sync:
        command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """
    Bring the database schema to the latest Alembic revision (ARQ: migrations-only schema).

    Unversioned databases created by the former ``create_all`` bootstrap are stamped at the
    baseline revision when their structure already matches the models; otherwise startup
    fails fast with the list of differences instead of patching tables in place.
    """
    global _db_initialized
    import app.models  # noqa: F401 - registers every ORM table on Base.metadata

    async with async_engine.connect() as conn:
        drift = await conn.run_sync(_legacy_schema_drift)

    if drift:
        raise SchemaDriftError(
            "Database was created outside Alembic and differs from the ORM schema: "
            + ", ".join(drift)
            + ". Back it up and recreate it (local SQLite: delete the file and re-run the seed)."
        )

    await asyncio.to_thread(_run_migrations, drift is not None)
    _db_initialized = True


async def ensure_db_ready() -> None:
    """Lazily applies pending migrations even outside of lifespan hooks."""
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
