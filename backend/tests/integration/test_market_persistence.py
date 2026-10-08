"""
Pruebas de integración para la persistencia de series temporales, deduplicación e InMemoryQuoteCache (Módulo 6 - Fase 3).
Utiliza SQLite en memoria (aiosqlite) y verifica la integridad relacional de MarketBarModel,
el servicio MarketHistoryService y el ciclo de vida del caché.
"""
import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from typing import List
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # Asegura registro de modelos relacionales
from app.core.database import Base
from app.domain.services.market_connector import BaseMarketConnector
from app.domain.services.market_history_service import MarketHistoryService
from app.infrastructure.db.models.market_data import MarketBarModel
from app.infrastructure.market_data.quote_cache import InMemoryQuoteCache
from app.schemas.market_data import MarketBarDTO, MarketQuoteDTO, Timeframe


class MockMarketConnector(BaseMarketConnector):
    """Conector simulado para pruebas de integración con conteo de llamadas."""

    def __init__(self):
        self.quote_calls = 0
        self.bars_calls = 0

    async def get_quote(self, ticker: str) -> MarketQuoteDTO:
        self.quote_calls += 1
        return MarketQuoteDTO(
            ticker=ticker,
            price=Decimal("1500.00"),
            bid=Decimal("1490.00"),
            ask=Decimal("1510.00"),
            volume=Decimal("10000"),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_historical_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        timeframe: Timeframe = Timeframe.D1,
    ) -> List[MarketBarDTO]:
        self.bars_calls += 1
        # Generar una barra por día en el intervalo
        bars = []
        curr = start_date
        while curr <= end_date:
            ts = datetime(curr.year, curr.month, curr.day, 18, 0, 0, tzinfo=timezone.utc)
            bars.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=Decimal("100.0"),
                    high=Decimal("110.0"),
                    low=Decimal("95.0"),
                    close=Decimal("105.0"),
                    volume=Decimal("1000"),
                    vwap=Decimal("102.5"),
                )
            )
            curr = date.fromordinal(curr.toordinal() + 1)
        return bars


class TestMarketPersistenceIntegration(unittest.IsolatedAsyncioTestCase):
    """Suite de integración con base de datos en memoria para el subsistema de datos de mercado."""

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

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_direct_market_bar_model_crud_and_unique_constraint(self) -> None:
        """Valida inserción, consulta y enforcement de la constraint única en MarketBarModel."""
        ts = datetime(2026, 10, 8, 15, 0, 0, tzinfo=timezone.utc)

        # 1. Inserción exitosa
        async with self.SessionLocal() as session:
            bar = MarketBarModel(
                ticker="AL30",
                timeframe="1d",
                timestamp=ts,
                open_price=Decimal("120000.00"),
                high_price=Decimal("125000.00"),
                low_price=Decimal("119000.00"),
                close_price=Decimal("124000.00"),
                volume=Decimal("500000"),
                vwap=Decimal("122500.00"),
            )
            session.add(bar)
            await session.commit()

        # 2. Lectura en nueva sesión
        async with self.SessionLocal() as session:
            stmt = select(MarketBarModel).where(MarketBarModel.ticker == "AL30")
            result = await session.execute(stmt)
            persisted = result.scalar_one_or_none()
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.ticker, "AL30")
            self.assertEqual(persisted.close_price, Decimal("124000.00"))
            self.assertEqual(persisted.timeframe, "1d")

        # 3. Violación de UniqueConstraint (mismo ticker, timeframe y timestamp)
        async with self.SessionLocal() as session:
            duplicate_bar = MarketBarModel(
                ticker="AL30",
                timeframe="1d",
                timestamp=ts,
                open_price=Decimal("120000.00"),
                high_price=Decimal("125000.00"),
                low_price=Decimal("119000.00"),
                close_price=Decimal("124000.00"),
                volume=Decimal("500000"),
            )
            session.add(duplicate_bar)
            with self.assertRaises(IntegrityError):
                await session.commit()

    async def test_market_history_service_first_fetch_and_second_cached_read(self) -> None:
        """Valida que la primera consulta invoque al conector y la segunda idéntica use la base de datos."""
        mock_connector = MockMarketConnector()

        start = date(2026, 10, 1)
        end = date(2026, 10, 3)  # 3 días: 1, 2, 3

        async with self.SessionLocal() as session:
            service = MarketHistoryService(connector=mock_connector, session=session)

            # Primera consulta: base vacía -> debe consultar conector
            bars_first = await service.get_or_fetch_bars(
                ticker="GGAL",
                start_date=start,
                end_date=end,
                timeframe=Timeframe.D1,
            )
            await session.commit()

            self.assertEqual(len(bars_first), 3)
            self.assertEqual(mock_connector.bars_calls, 1)
            for b in bars_first:
                self.assertIsInstance(b, MarketBarDTO)
                self.assertEqual(b.timestamp.tzinfo, timezone.utc)

            # Verificar que se hayan persistido en base de datos
            stmt = select(MarketBarModel).where(MarketBarModel.ticker == "GGAL")
            res_db = await session.execute(stmt)
            self.assertEqual(len(list(res_db.scalars().all())), 3)

            # Segunda consulta: idéntica -> debe resolver desde base de datos sin llamar al conector
            bars_second = await service.get_or_fetch_bars(
                ticker="GGAL",
                start_date=start,
                end_date=end,
                timeframe=Timeframe.D1,
            )
            self.assertEqual(len(bars_second), 3)
            self.assertEqual(mock_connector.bars_calls, 1)  # No incrementó

    async def test_market_history_service_partial_overlap_delta_ingestion(self) -> None:
        """Valida que una consulta con solapamiento parcial solo inserte las barras delta nuevas."""
        mock_connector = MockMarketConnector()

        # Ingesta inicial: días 1 a 3
        start_1 = date(2026, 10, 1)
        end_1 = date(2026, 10, 3)

        async with self.SessionLocal() as session:
            service = MarketHistoryService(connector=mock_connector, session=session)
            await service.get_or_fetch_bars("AAPL", start_1, end_1)
            await session.commit()
            self.assertEqual(mock_connector.bars_calls, 1)

            # Segunda consulta con rango extendido: días 1 a 5 (días 4 y 5 son nuevos)
            start_2 = date(2026, 10, 1)
            end_2 = date(2026, 10, 5)

            bars_extended = await service.get_or_fetch_bars("AAPL", start_2, end_2)
            await session.commit()

            # Debe haber llamado al conector por segunda vez para traer el rango solicitado
            self.assertEqual(mock_connector.bars_calls, 2)
            # Pero en base de datos debe haber exactamente 5 barras sin duplicados
            self.assertEqual(len(bars_extended), 5)

            stmt = select(MarketBarModel).where(MarketBarModel.ticker == "AAPL")
            res_all = await session.execute(stmt)
            db_bars = list(res_all.scalars().all())
            self.assertEqual(len(db_bars), 5)

    async def test_in_memory_quote_cache_lifecycle(self) -> None:
        """Valida hit, expiración por TTL y limpieza en InMemoryQuoteCache."""
        cache = InMemoryQuoteCache(ttl_seconds=0.1)

        quote = MarketQuoteDTO(
            ticker="YPFD",
            price=Decimal("25000.00"),
            timestamp=datetime.now(timezone.utc),
        )

        # Set y Hit inmediato
        await cache.set("ypfd", quote)
        cached = await cache.get("YPFD")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.price, Decimal("25000.00"))

        # Esperar expiración
        await asyncio.sleep(0.12)
        expired = await cache.get("YPFD")
        self.assertIsNone(expired)

        # Clear
        await cache.set("YPFD", quote)
        await cache.clear()
        self.assertIsNone(await cache.get("YPFD"))

    async def test_market_history_service_quote_caching(self) -> None:
        """Valida que get_quote_with_cache sirva cotizaciones desde el caché tras la primera llamada."""
        mock_connector = MockMarketConnector()
        cache = InMemoryQuoteCache(ttl_seconds=60.0)

        async with self.SessionLocal() as session:
            service = MarketHistoryService(
                connector=mock_connector,
                session=session,
                cache=cache,
            )

            # Primer llamada: cache miss -> consulta al conector
            q1 = await service.get_quote_with_cache("GGAL")
            self.assertEqual(mock_connector.quote_calls, 1)
            self.assertEqual(q1.ticker, "GGAL")

            # Segunda llamada: cache hit -> sin nueva llamada al conector
            q2 = await service.get_quote_with_cache("GGAL")
            self.assertEqual(mock_connector.quote_calls, 1)
            self.assertEqual(q2.ticker, "GGAL")

            # Ticker distinto: cache miss -> nueva llamada
            q3 = await service.get_quote_with_cache("AL30")
            self.assertEqual(mock_connector.quote_calls, 2)
            self.assertEqual(q3.ticker, "AL30")


if __name__ == "__main__":
    unittest.main()

