"""
Global pytest fixtures and test harness for InvestAI backend test suite.
Provides asynchronous database engines, isolated sessions, and HTTP ASGI test clients.
"""
from typing import AsyncGenerator
import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # Registers all declarative tables first
from app.api.deps import get_db_session
from app.core.database import Base
from app.main import app

try:
    import pytest
    import pytest_asyncio
except ImportError:
    # Graceful fallback when running under pure unittest runner without pytest installed
    class _MockPytest:
        @staticmethod
        def fixture(*args, **kwargs):
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return args[0]
            def decorator(func):
                return func
            return decorator
    pytest = _MockPytest()


@pytest.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Session-level in-memory SQLite async engine.
    Initializes database schema and ensures explicit teardown disposal
    to eliminate ResourceWarning unclosed database descriptors.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Function-scoped isolated AsyncSession for database operations.
    Handles transaction commits and rollbacks cleanly.
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@pytest.fixture
async def async_client(test_engine: AsyncEngine) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Function-scoped AsyncClient mounted over FastAPI ASGITransport.
    Injects and cleans up app.dependency_overrides safely.
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db_session] = _override_get_db_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
