"""
Pruebas de integración para los Controladores REST de Mercado y Backtesting (Módulo 6 - Fase 4).
Verifica conformidad con Universal Envelope (APIResponse / APIErrorResponse),
validaciones defensivas (regex de tickers, consistencia de fechas, ratios),
resolución de dependencias vía app.dependency_overrides,
cálculo de MEP/CCL y adaptación canónica para BacktestEngine.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List
import unittest

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # Asegura registro de modelos relacionales
from app.api.deps import get_db_session, get_market_service
from app.core.database import Base
from app.domain.services.backtest_engine import BacktestEngine, bars_to_price_history
from app.domain.services.market_connector import (
    BaseMarketConnector,
    RateLimitExceededError,
    TickerNotFoundError,
)
from app.domain.services.market_history_service import MarketHistoryService
from app.infrastructure.market_data.quote_cache import InMemoryQuoteCache
from app.main import app as fastapi_app
from app.schemas.backtest import BacktestConfig, RebalanceFrequency
from app.schemas.market_data import (
    MarketBarDTO,
    MarketQuoteDTO,
    Timeframe,
)


class MockMarketDataConnector(BaseMarketConnector):
    """Conector de mercado simulado para pruebas de integración de endpoints."""

    def __init__(self):
        self.quote_calls = {}
        self.bars_calls = {}
        self.quotes_db = {}
        self.bars_db = {}

    def add_quote(self, quote: MarketQuoteDTO):
        self.quotes_db[quote.ticker.upper()] = quote

    def add_bars(self, ticker: str, bars: List[MarketBarDTO]):
        self.bars_db[ticker.upper()] = bars

    async def get_quote(self, ticker: str) -> MarketQuoteDTO:
        norm = ticker.strip().upper()
        self.quote_calls[norm] = self.quote_calls.get(norm, 0) + 1
        if norm == "RATELIMIT":
            raise RateLimitExceededError("Rate limit excedido por el proveedor")
        if norm not in self.quotes_db:
            raise TickerNotFoundError(f"Ticker '{norm}' no encontrado")
        return self.quotes_db[norm]

    async def get_historical_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        timeframe: Timeframe = Timeframe.D1,
    ) -> List[MarketBarDTO]:
        norm = ticker.strip().upper()
        self.bars_calls[norm] = self.bars_calls.get(norm, 0) + 1
        if norm == "RATELIMIT":
            raise RateLimitExceededError("Rate limit excedido por el proveedor")
        if norm not in self.bars_db:
            raise TickerNotFoundError(f"Ticker '{norm}' no encontrado")
        return [
            b for b in self.bars_db[norm]
            if start_date <= b.timestamp.date() <= end_date
        ]


class TestApiMarketIntegration(unittest.IsolatedAsyncioTestCase):
    """Suite de integración para endpoints REST de mercado y adaptador de backtesting."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self.mock_connector = MockMarketDataConnector()
        self.test_cache = InMemoryQuoteCache(ttl_seconds=30.0)

        # Poblar cotizaciones base
        now = datetime.now(timezone.utc)
        self.mock_connector.add_quote(
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("120000.00"),
                bid=Decimal("119500.00"),
                ask=Decimal("120500.00"),
                volume=Decimal("50000"),
                timestamp=now,
            )
        )
        self.mock_connector.add_quote(
            MarketQuoteDTO(
                ticker="AL30D",
                price=Decimal("100.00"),
                bid=Decimal("99.50"),
                ask=Decimal("100.50"),
                volume=Decimal("15000"),
                timestamp=now,
            )
        )
        self.mock_connector.add_quote(
            MarketQuoteDTO(
                ticker="GGAL",
                price=Decimal("4500.00"),
                bid=Decimal("4480.00"),
                ask=Decimal("4520.00"),
                volume=Decimal("30000"),
                timestamp=now,
            )
        )
        self.mock_connector.add_quote(
            MarketQuoteDTO(
                ticker="GGAL-US",
                price=Decimal("45.00"),
                bid=Decimal("44.80"),
                ask=Decimal("45.20"),
                volume=Decimal("8000"),
                timestamp=now,
            )
        )

        # Poblar serie histórica de barras para GGAL y AAPL
        start_d = date(2024, 1, 1)
        ggal_bars = []
        aapl_bars = []
        for i in range(15):
            d = start_d + timedelta(days=i)
            ts = datetime(d.year, d.month, d.day, 17, 0, 0, tzinfo=timezone.utc)
            ggal_bars.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=Decimal(str(100.0 + i * 1.5)),
                    high=Decimal(str(105.0 + i * 1.5)),
                    low=Decimal(str(99.0 + i * 1.5)),
                    close=Decimal(str(102.0 + i * 1.5)),
                    volume=Decimal("1000"),
                )
            )
            aapl_bars.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=Decimal(str(180.0 + i * 0.8)),
                    high=Decimal(str(185.0 + i * 0.8)),
                    low=Decimal(str(178.0 + i * 0.8)),
                    close=Decimal(str(182.0 + i * 0.8)),
                    volume=Decimal("5000"),
                )
            )
        self.mock_connector.add_bars("GGAL", ggal_bars)
        self.mock_connector.add_bars("AAPL", aapl_bars)

        async def _override_get_db():
            async with self.SessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()

        def _override_get_market_service():
            # Crear sesión directa para el servicio
            session = self.SessionLocal()
            return MarketHistoryService(
                connector=self.mock_connector,
                session=session,
                cache=self.test_cache,
            )

        fastapi_app.dependency_overrides[get_db_session] = _override_get_db
        fastapi_app.dependency_overrides[get_market_service] = _override_get_market_service

        self.transport = httpx.ASGITransport(app=fastapi_app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            await self.client.aclose()
        fastapi_app.dependency_overrides.clear()
        if hasattr(self, "engine") and self.engine is not None:
            await self.engine.dispose()

    async def test_get_quote_success_and_envelope(self) -> None:
        """Verifica 200 OK, envelope canónico, campos tipados y header X-Request-ID."""
        response = await self.client.get("/api/v1/market/quote/AL30")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("meta", data)
        self.assertIn("request_id", data["meta"])
        self.assertIn("X-Request-ID", response.headers)

        quote = data["data"]
        self.assertEqual(quote["ticker"], "AL30")
        self.assertEqual(quote["price"], "120000.00")
        self.assertEqual(quote["bid"], "119500.00")
        self.assertEqual(quote["ask"], "120500.00")

    async def test_get_quote_caching_hit(self) -> None:
        """Verifica que solicitudes sucesivas se resuelvan desde InMemoryQuoteCache."""
        self.assertEqual(self.mock_connector.quote_calls.get("AL30", 0), 0)

        # Primera llamada: cache miss -> consulta al conector
        res1 = await self.client.get("/api/v1/market/quote/AL30")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(self.mock_connector.quote_calls.get("AL30"), 1)

        # Segunda llamada: cache hit -> no incrementa llamadas al conector
        res2 = await self.client.get("/api/v1/market/quote/AL30")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(self.mock_connector.quote_calls.get("AL30"), 1)

    async def test_get_quote_invalid_ticker_regex(self) -> None:
        """Verifica 422 con código INVALID_TICKER_FORMAT ante tickers inválidos."""
        response = await self.client.get("/api/v1/market/quote/invalid@ticker")
        self.assertEqual(response.status_code, 422)

        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_TICKER_FORMAT")
        self.assertTrue(any(d["field"] == "ticker" for d in data["error"]["details"]))

    async def test_get_quote_not_found(self) -> None:
        """Verifica 404 con código TICKER_NOT_FOUND para instrumentos inexistentes."""
        response = await self.client.get("/api/v1/market/quote/NOTFOUND")
        self.assertEqual(response.status_code, 404)

        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TICKER_NOT_FOUND")

    async def test_get_quote_rate_limit(self) -> None:
        """Verifica 429 con código RATE_LIMIT_EXCEEDED cuando el conector reporta exceso de tasa."""
        response = await self.client.get("/api/v1/market/quote/RATELIMIT")
        self.assertEqual(response.status_code, 429)

        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "RATE_LIMIT_EXCEEDED")

    async def test_get_history_success(self) -> None:
        """Verifica 200 OK y retorno ordenado de barras OHLCV."""
        response = await self.client.get(
            "/api/v1/market/history/GGAL?start_date=2024-01-01&end_date=2024-01-05&timeframe=1d"
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        bars = data["data"]
        self.assertEqual(len(bars), 5)
        self.assertEqual(Decimal(str(bars[0]["close"])), Decimal("102.0"))
        self.assertEqual(Decimal(str(bars[-1]["close"])), Decimal("108.0"))

    async def test_get_history_invalid_date_range(self) -> None:
        """Verifica 422 con código INVALID_DATE_RANGE cuando start_date > end_date."""
        response = await self.client.get(
            "/api/v1/market/history/GGAL?start_date=2024-01-10&end_date=2024-01-05"
        )
        self.assertEqual(response.status_code, 422)

        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_DATE_RANGE")

    async def test_get_history_invalid_ticker_regex(self) -> None:
        """Verifica 422 con código INVALID_TICKER_FORMAT en /history."""
        response = await self.client.get(
            "/api/v1/market/history/bad$ticker?start_date=2024-01-01&end_date=2024-01-05"
        )
        self.assertEqual(response.status_code, 422)

        data = response.json()
        self.assertEqual(data["error"]["code"], "INVALID_TICKER_FORMAT")

    async def test_get_history_not_found(self) -> None:
        """Verifica 404 con TICKER_NOT_FOUND en /history."""
        response = await self.client.get(
            "/api/v1/market/history/DESCONOCIDO?start_date=2024-01-01&end_date=2024-01-05"
        )
        self.assertEqual(response.status_code, 404)

        data = response.json()
        self.assertEqual(data["error"]["code"], "TICKER_NOT_FOUND")

    async def test_get_fx_mep_success(self) -> None:
        """Verifica cálculo determinista de tipo de cambio implícito Dólar MEP."""
        response = await self.client.get("/api/v1/market/fx/mep?local_ticker=AL30&usd_ticker=AL30D")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        fx = data["data"]
        self.assertEqual(fx["fx_type"], "MEP")
        self.assertEqual(fx["base_ticker"], "AL30")
        self.assertEqual(fx["quote_ticker"], "AL30D")
        # 120000.00 / 100.00 = 1200.0000
        self.assertEqual(Decimal(fx["rate"]), Decimal("1200.0000"))
        self.assertIsNotNone(fx["spread_pct"])

    async def test_get_fx_mep_ticker_not_found(self) -> None:
        """Verifica 404 si alguno de los activos no existe para MEP."""
        response = await self.client.get("/api/v1/market/fx/mep?local_ticker=INVENTADO&usd_ticker=AL30D")
        self.assertEqual(response.status_code, 404)

        data = response.json()
        self.assertEqual(data["error"]["code"], "TICKER_NOT_FOUND")

    async def test_get_fx_ccl_success(self) -> None:
        """Verifica cálculo determinista de tipo de cambio implícito Dólar CCL con ratio."""
        response = await self.client.get(
            "/api/v1/market/fx/ccl?local_ticker=GGAL&adr_ticker=GGAL-US&conversion_ratio=10"
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        fx = data["data"]
        self.assertEqual(fx["fx_type"], "CCL")
        self.assertEqual(fx["base_ticker"], "GGAL")
        self.assertEqual(fx["quote_ticker"], "GGAL-US")
        # (4500.00 * 10) / 45.00 = 1000.0000
        self.assertEqual(Decimal(fx["rate"]), Decimal("1000.0000"))
        self.assertIsNotNone(fx["spread_pct"])

    async def test_get_fx_ccl_invalid_conversion_ratio(self) -> None:
        """Verifica 422 con INVALID_CONVERSION_RATIO ante ratio no positivo."""
        response = await self.client.get(
            "/api/v1/market/fx/ccl?local_ticker=GGAL&adr_ticker=GGAL-US&conversion_ratio=-2"
        )
        self.assertEqual(response.status_code, 422)

        data = response.json()
        self.assertEqual(data["error"]["code"], "INVALID_CONVERSION_RATIO")

    async def test_bars_to_price_history_and_backtest_run(self) -> None:
        """
        Valida que el adaptador bars_to_price_history transforme fielmente las barras
        y que BacktestEngine.run simule la cartera sobre los precios adaptados.
        """
        # 1. Recuperar barras de los instrumentos
        res_ggal = await self.client.get("/api/v1/market/history/GGAL?start_date=2024-01-01&end_date=2024-01-15")
        res_aapl = await self.client.get("/api/v1/market/history/AAPL?start_date=2024-01-01&end_date=2024-01-15")
        self.assertEqual(res_ggal.status_code, 200)
        self.assertEqual(res_aapl.status_code, 200)

        bars_dict = {
            "GGAL": [MarketBarDTO.model_validate(b) for b in res_ggal.json()["data"]],
            "AAPL": [MarketBarDTO.model_validate(b) for b in res_aapl.json()["data"]],
        }

        # 2. Aplicar el adaptador de integración
        price_history = bars_to_price_history(bars_dict)
        self.assertIn("GGAL", price_history)
        self.assertIn("AAPL", price_history)
        self.assertEqual(len(price_history["GGAL"]), 15)
        self.assertEqual(len(price_history["AAPL"]), 15)

        # 3. Ejecutar BacktestEngine
        config = BacktestConfig(
            initial_capital=500_000.0,
            tickers=["AAPL", "GGAL"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 15),
            rebalance_frequency=RebalanceFrequency.WEEKLY,
            risk_free_rate=0.05,
        )
        engine = BacktestEngine(config=config)
        result = engine.run(prices_data=price_history)

        # 4. Validar resultado de simulación
        self.assertIsNotNone(result)
        self.assertEqual(result.config.tickers, ["AAPL", "GGAL"])
        self.assertGreater(len(result.snapshots), 0)
        self.assertIn("cagr", result.metrics.model_dump())
        self.assertIn("sharpe_ratio", result.metrics.model_dump())
        self.assertIn("total_return", result.metrics.model_dump())


if __name__ == "__main__":
    unittest.main()
