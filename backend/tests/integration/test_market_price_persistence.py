"""
Mark-to-market price persistence: GET /market/live-quotes is a public read-only view, and
only the backend background sync writes holding prices, always with the last REAL price
downloaded from a provider (never the simulated micro-tick, never a static seed).
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import app.models  # noqa: F401 - register ORM metadata
import httpx
import pytest
from app.api.deps import get_db_session
from app.core.database import Base
from app.core.security import get_password_hash
from app.domain.services.market_data_provider import PublicMarket10YProvider as Provider
from app.main import app
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.user import UserRole
from app.services.market_price_sync import MarketPriceSync
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.integration

INITIAL_PRICE = 100.0


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Isolated in-memory database per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client over the ASGI app bound to the isolated test database."""

    async def _override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


async def _seed_holdings(
    session_factory: async_sessionmaker[AsyncSession], ticker: str, owners: int = 2
) -> list[int]:
    """One asset held by `owners` different users; returns the holding ids."""
    async with session_factory() as session:
        session.add(
            AssetModel(
                ticker=ticker,
                name=f"{ticker} Test Asset",
                asset_type="STOCK",
                currency="ARS",
                metrics_payload={"current_price": INITIAL_PRICE},
            )
        )
        holdings: list[HoldingModel] = []
        for i in range(owners):
            user = UserModel(
                email=f"mtm_{uuid.uuid4().hex[:10]}@investai.com",
                hashed_password=get_password_hash("StrongPassword123!"),
                full_name=f"MTM Owner {i}",
                role=UserRole.TRADER,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            portfolio = PortfolioModel(user_id=str(user.id), name=f"MTM Portfolio {i}")
            session.add(portfolio)
            await session.flush()
            holding = HoldingModel(
                portfolio_id=portfolio.id,
                asset_ticker=ticker,
                quantity=10.0,
                average_buy_price=90.0,
                current_price=INITIAL_PRICE,
            )
            session.add(holding)
            holdings.append(holding)
        await session.commit()
        return [h.id for h in holdings]


async def _holding_prices(
    session_factory: async_sessionmaker[AsyncSession], holding_ids: list[int]
) -> list[float]:
    async with session_factory() as session:
        rows = await session.execute(
            select(HoldingModel.current_price)
            .where(HoldingModel.id.in_(holding_ids))
            .order_by(HoldingModel.id)
        )
        return [float(p) for p in rows.scalars().all()]


async def _asset_payload(
    session_factory: async_sessionmaker[AsyncSession], ticker: str
) -> dict[str, Any]:
    async with session_factory() as session:
        asset = await session.get(AssetModel, ticker)
        assert asset is not None
        return dict(asset.metrics_payload or {})


def _unique_ticker() -> str:
    return f"MTM{uuid.uuid4().hex[:6].upper()}"


def _real_price(price: float, previous_close: float) -> dict[str, Any]:
    return {
        "price": price,
        "previous_close": previous_close,
        "source": "YAHOO_LIVE",
        "observed_at": "2026-11-12T15:00:00+00:00",
    }


async def test_live_quotes_is_public_and_never_writes_prices(
    api_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    ticker = _unique_ticker()
    holding_ids = await _seed_holdings(session_factory, ticker)
    simulated_quote = {
        "ticker": ticker,
        "name": ticker,
        "asset_type": "STOCK",
        "currency": "ARS",
        "last_price": 123.45,
        "change_pct": 1.5,
        "change_nominal": 1.8,
        "updated_at": "2026-11-12T15:00:00+00:00",
        "data_source": "YAHOO_BCBA_LIVE_5S",
    }

    async def fake_batch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"quotes": [simulated_quote], "ccl_rate": 1668.0, "mep_rate": 1581.0}

    monkeypatch.setattr(Provider, "fetch_live_quotes_batch", fake_batch)

    response = await api_client.get("/api/v1/market/live-quotes")  # no credentials

    assert response.status_code == 200
    assert response.json()["data"]["quotes"][0]["last_price"] == 123.45
    assert await _holding_prices(session_factory, holding_ids) == [INITIAL_PRICE] * 2
    assert (await _asset_payload(session_factory, ticker)) == {"current_price": INITIAL_PRICE}


async def test_sync_writes_real_price_to_every_holding_and_asset(
    session_factory: async_sessionmaker[AsyncSession],
):
    ticker = _unique_ticker()
    other_ticker = _unique_ticker()
    holding_ids = await _seed_holdings(session_factory, ticker)
    other_ids = await _seed_holdings(session_factory, other_ticker, owners=1)
    sync = MarketPriceSync(session_factory)

    written = await sync.persist({ticker: _real_price(110.0, previous_close=100.0)})

    assert written == 1
    assert await _holding_prices(session_factory, holding_ids) == [110.0, 110.0]
    assert await _holding_prices(session_factory, other_ids) == [INITIAL_PRICE]
    payload = await _asset_payload(session_factory, ticker)
    assert payload["current_price"] == 110.0
    assert payload["reference_price"] == 110.0
    assert payload["change_pct"] == 10.0
    assert payload["data_source"] == "YAHOO_LIVE"


async def test_sync_skips_unchanged_prices(session_factory: async_sessionmaker[AsyncSession]):
    ticker = _unique_ticker()
    holding_ids = await _seed_holdings(session_factory, ticker, owners=1)
    sync = MarketPriceSync(session_factory)
    await sync.persist({ticker: _real_price(110.0, previous_close=100.0)})

    assert await sync.persist({ticker: _real_price(110.0, previous_close=100.0)}) == 0
    assert await sync.persist({ticker: _real_price(111.0, previous_close=100.0)}) == 1
    assert await _holding_prices(session_factory, holding_ids) == [111.0]


async def test_sync_retries_prices_whose_commit_failed(
    session_factory: async_sessionmaker[AsyncSession],
):
    ticker = _unique_ticker()
    holding_ids = await _seed_holdings(session_factory, ticker, owners=1)
    failures = {"left": 1}

    class FailingOnceSession(AsyncSession):
        async def commit(self) -> None:
            if failures["left"]:
                failures["left"] -= 1
                raise RuntimeError("simulated database outage")
            await super().commit()

    flaky_factory = async_sessionmaker(
        bind=session_factory.kw["bind"], class_=FailingOnceSession, expire_on_commit=False
    )
    sync = MarketPriceSync(flaky_factory)

    with pytest.raises(RuntimeError):
        await sync.persist({ticker: _real_price(120.0, previous_close=100.0)})
    assert await _holding_prices(session_factory, holding_ids) == [INITIAL_PRICE]

    assert await sync.persist({ticker: _real_price(120.0, previous_close=100.0)}) == 1
    assert await _holding_prices(session_factory, holding_ids) == [120.0]


async def test_sync_ignores_invalid_prices(session_factory: async_sessionmaker[AsyncSession]):
    ticker = _unique_ticker()
    holding_ids = await _seed_holdings(session_factory, ticker, owners=1)
    sync = MarketPriceSync(session_factory)

    written = await sync.persist(
        {ticker: _real_price(0.0, previous_close=100.0), "NOPE": _real_price(-5.0, 1.0)}
    )

    assert written == 0
    assert await _holding_prices(session_factory, holding_ids) == [INITIAL_PRICE]


async def test_lifespan_wires_background_sync_to_price_persistence(
    monkeypatch: pytest.MonkeyPatch,
):
    from app import main as main_module

    received: dict[str, Any] = {}

    async def no_op_init_db() -> None:
        return None

    def fake_start(on_real_prices: Any = None) -> None:
        received["sink"] = on_real_prices

    async def fake_stop() -> None:
        received["stopped"] = True

    monkeypatch.setattr(main_module, "init_db", no_op_init_db)
    monkeypatch.setattr(main_module, "_market_prewarm_enabled", lambda: True)
    monkeypatch.setattr(Provider, "start_background_sync", fake_start)
    monkeypatch.setattr(Provider, "stop_background_sync", fake_stop)

    async with main_module.lifespan(app):
        pass

    sink = received["sink"]
    assert isinstance(getattr(sink, "__self__", None), MarketPriceSync)
    assert sink.__func__ is MarketPriceSync.persist
    assert received["stopped"] is True


async def test_sync_prices_holdings_added_after_an_unchanged_price(
    session_factory: async_sessionmaker[AsyncSession],
):
    ticker = _unique_ticker()
    await _seed_holdings(session_factory, ticker, owners=1)
    sync = MarketPriceSync(session_factory)
    await sync.persist({ticker: _real_price(110.0, previous_close=100.0)})

    async with session_factory() as session:  # new holding loaded at its purchase price
        portfolio_id = (
            await session.execute(
                select(HoldingModel.portfolio_id).where(HoldingModel.asset_ticker == ticker)
            )
        ).scalar_one()
        late = HoldingModel(
            portfolio_id=portfolio_id,
            asset_ticker=ticker,
            quantity=1.0,
            average_buy_price=95.0,
            current_price=95.0,
        )
        session.add(late)
        await session.commit()
        late_id = late.id

    written = await sync.persist({ticker: _real_price(110.0, previous_close=100.0)})

    assert written == 1
    assert await _holding_prices(session_factory, [late_id]) == [110.0]


async def test_sync_restores_real_price_after_an_external_overwrite(
    session_factory: async_sessionmaker[AsyncSession],
):
    ticker = _unique_ticker()
    holding_ids = await _seed_holdings(session_factory, ticker, owners=1)
    sync = MarketPriceSync(session_factory)
    await sync.persist({ticker: _real_price(110.0, previous_close=100.0)})

    async with session_factory() as session:  # e.g. a broker statement import
        await session.execute(
            update(HoldingModel).where(HoldingModel.id == holding_ids[0]).values(current_price=42.0)
        )
        await session.commit()

    assert await sync.persist({ticker: _real_price(110.0, previous_close=100.0)}) == 1
    assert await _holding_prices(session_factory, holding_ids) == [110.0]
