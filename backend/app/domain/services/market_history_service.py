"""
Servicio de persistencia, sincronización incremental y caché de datos de mercado (Módulo 6 - Fase 3).
Orquesta la ingesta delta de series históricas OHLCV con deduplicación y caché en memoria para cotizaciones.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.market_connector import BaseMarketConnector
from app.infrastructure.db.models.market_data import MarketBarModel
from app.infrastructure.market_data.quote_cache import InMemoryQuoteCache
from app.schemas.market_data import MarketBarDTO, MarketQuoteDTO, Timeframe


class MarketHistoryService:
    """
    Servicio de dominio para consulta, persistencia e ingesta incremental (delta)
    de series temporales OHLCV y cotizaciones en tiempo real con caché en memoria.
    """

    def __init__(
        self,
        connector: BaseMarketConnector,
        session: AsyncSession,
        cache: InMemoryQuoteCache | None = None,
    ):
        """
        Inicializa el servicio de historial de mercado.

        Parámetros:
        -----------
        connector: Conector hacia el proveedor de mercado (ej. HttpMarketConnector).
        session: Sesión de base de datos asíncrona de SQLAlchemy.
        cache: Instancia opcional de InMemoryQuoteCache para cotizaciones en vivo.
        """
        self.connector = connector
        self.session = session
        self.cache = cache

    async def get_or_fetch_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        timeframe: Timeframe = Timeframe.D1,
    ) -> list[MarketBarDTO]:
        """
        Consulta barras históricas en la base de datos local y, si el rango solicitado
        no está cubierto, consulta al conector externo, deduplica e inserta las barras faltantes.

        Parámetros:
        -----------
        ticker: Símbolo o especie del activo (ej. 'GGAL', 'AAPL').
        start_date: Fecha inicial inclusiva.
        end_date: Fecha final inclusiva.
        timeframe: Granularidad temporal de las barras (por defecto '1d').

        Retorna:
        --------
        List[MarketBarDTO]: Lista consolidada ordenada cronológicamente por timestamp ascendente.
        """
        norm_ticker = ticker.strip().upper()
        tf_val = timeframe.value if isinstance(timeframe, Timeframe) else str(timeframe)

        if start_date > end_date:
            raise ValueError(
                f"La fecha inicial ({start_date}) debe ser menor o igual a la fecha final ({end_date})."
            )

        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=UTC)

        # 1. Consulta inicial en la base de datos local
        stmt = (
            select(MarketBarModel)
            .where(
                MarketBarModel.ticker == norm_ticker,
                MarketBarModel.timeframe == tf_val,
                MarketBarModel.timestamp >= start_dt,
                MarketBarModel.timestamp <= end_dt,
            )
            .order_by(MarketBarModel.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        existing_models = list(result.scalars().all())

        # 2. Evaluación de cobertura local
        needs_fetch = False
        if not existing_models:
            needs_fetch = True
        else:
            earliest_dt = existing_models[0].timestamp
            latest_dt = existing_models[-1].timestamp
            earliest_date = earliest_dt.date() if hasattr(earliest_dt, "date") else start_date
            latest_date = latest_dt.date() if hasattr(latest_dt, "date") else end_date

            if earliest_date > start_date or latest_date < end_date:
                needs_fetch = True

        # 3. Consulta externa e inserción delta si la cobertura es insuficiente
        if needs_fetch:
            fetched_bars = await self.connector.get_historical_bars(
                ticker=norm_ticker,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
            )

            def _normalize_ts(dt_val: datetime) -> datetime:
                if dt_val.tzinfo is None:
                    return dt_val.replace(tzinfo=UTC)
                return dt_val.astimezone(UTC)

            existing_ts_set: set[datetime] = {_normalize_ts(m.timestamp) for m in existing_models}

            new_models = []
            for bar in fetched_bars:
                norm_bar_ts = _normalize_ts(bar.timestamp)
                if norm_bar_ts not in existing_ts_set:
                    new_models.append(
                        MarketBarModel(
                            id=uuid.uuid4(),
                            ticker=norm_ticker,
                            timeframe=tf_val,
                            timestamp=norm_bar_ts,
                            open_price=bar.open,
                            high_price=bar.high,
                            low_price=bar.low,
                            close_price=bar.close,
                            volume=bar.volume,
                            vwap=bar.vwap,
                        )
                    )
                    existing_ts_set.add(norm_bar_ts)

            if new_models:
                self.session.add_all(new_models)
                await self.session.flush()

            # Re-consultar la base de datos para obtener la serie cronológica consolidada
            result = await self.session.execute(stmt)
            existing_models = list(result.scalars().all())

        # 4. Mapeo defensivo a MarketBarDTO garantizando zona horaria UTC
        bars_dto: list[MarketBarDTO] = []
        for m in existing_models:
            ts = m.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            else:
                ts = ts.astimezone(UTC)

            bars_dto.append(
                MarketBarDTO(
                    timestamp=ts,
                    open=Decimal(str(m.open_price)),
                    high=Decimal(str(m.high_price)),
                    low=Decimal(str(m.low_price)),
                    close=Decimal(str(m.close_price)),
                    volume=Decimal(str(m.volume)),
                    vwap=Decimal(str(m.vwap)) if m.vwap is not None else None,
                )
            )

        return bars_dto

    async def get_quote_with_cache(self, ticker: str) -> MarketQuoteDTO:
        """
        Obtiene la cotización en tiempo real utilizando la caché en memoria si está activa.
        En caso de caché miss o expiración, consulta al conector y actualiza la caché.
        """
        norm_ticker = ticker.strip().upper()
        if self.cache is not None:
            cached = await self.cache.get(norm_ticker)
            if cached is not None:
                return cached

        quote = await self.connector.get_quote(norm_ticker)
        if self.cache is not None:
            await self.cache.set(norm_ticker, quote)

        return quote
