"""
Startup schema governance: init_db() must build the schema through Alembic only.

Covers fresh databases, idempotent re-runs, and unversioned databases created by the
former ``Base.metadata.create_all`` bootstrap (in sync -> stamped, drifted -> fail fast).
"""

import sqlite3
from pathlib import Path

import app.models  # noqa: F401 - registers every ORM table on Base.metadata
import pytest
from app.core import database
from app.core.config import settings
from app.core.database import BASELINE_REVISION, Base, SchemaDriftError, init_db
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


@pytest.fixture
def sqlite_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "startup.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(url)
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    monkeypatch.setattr(database, "async_engine", engine)
    monkeypatch.setattr(database, "_db_initialized", False)
    yield db_file
    engine.sync_engine.dispose()


def _tables(db_file: Path) -> set[str]:
    with sqlite3.connect(db_file) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _version(db_file: Path) -> list[str]:
    with sqlite3.connect(db_file) as conn:
        return [r[0] for r in conn.execute("SELECT version_num FROM alembic_version")]


def test_alembic_ini_resolves_from_module_location():
    cfg = database.build_alembic_config()
    assert Path(cfg.config_file_name).name == "alembic.ini"
    assert Path(cfg.config_file_name).is_file()


async def test_fresh_database_is_built_by_migrations(sqlite_target: Path):
    await init_db()

    assert set(Base.metadata.tables) <= _tables(sqlite_target)
    assert _version(sqlite_target) == [BASELINE_REVISION]
    assert database._db_initialized is True


async def test_init_db_is_idempotent_on_versioned_database(sqlite_target: Path):
    await init_db()
    await init_db()

    assert _version(sqlite_target) == [BASELINE_REVISION]


async def test_legacy_create_all_database_in_sync_is_stamped(sqlite_target: Path):
    sync_engine = create_engine(f"sqlite:///{sqlite_target.as_posix()}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    await init_db()

    assert _version(sqlite_target) == [BASELINE_REVISION]


async def test_legacy_database_with_drift_fails_fast_without_mutation(sqlite_target: Path):
    with sqlite3.connect(sqlite_target) as conn:
        conn.execute("CREATE TABLE portfolios (id INTEGER PRIMARY KEY)")
    before = _tables(sqlite_target)

    with pytest.raises(SchemaDriftError, match="add_table market_bars"):
        await init_db()

    assert _tables(sqlite_target) == before
    assert database._db_initialized is False
