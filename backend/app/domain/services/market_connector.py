"""
Interfaz canónica y excepciones de dominio para conectores de datos de mercado (Módulo 6 - Fase 2).
Define la abstracción desacoplada para proveedores de cotizaciones en tiempo real y series históricas.
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import List

from app.schemas.market_data import MarketBarDTO, MarketQuoteDTO, Timeframe


class MarketDataConnectorError(Exception):
    """Excepción base para anomalías y fallos en conectores de datos de mercado."""
    pass


class TickerNotFoundError(MarketDataConnectorError):
    """Lanzada cuando un activo o ticker no existe o no fue hallado en el proveedor (HTTP 404)."""
    pass


class RateLimitExceededError(MarketDataConnectorError):
    """Lanzada cuando se agotan los reintentos tras alcanzar el límite de tasa del proveedor (HTTP 429)."""
    pass


class SecuritySSRFViolationError(MarketDataConnectorError):
    """Lanzada cuando una dirección o URL de destino viola las restricciones defensivas anti-SSRF."""
    pass


class BaseMarketConnector(ABC):
    """
    Contrato abstracto canónico para proveedores de datos de mercado.
    Permite desacoplar el dominio financiero de la infraestructura de red subyacente.
    """

    @abstractmethod
    async def get_quote(self, ticker: str) -> MarketQuoteDTO:
        """
        Obtiene la última cotización operada en tiempo real para el ticker indicado.

        Parámetros:
        -----------
        ticker: Símbolo o especie del activo (ej. 'GGAL', 'AAPL', 'AL30').

        Retorna:
        --------
        MarketQuoteDTO: Cotización atómica inmutable y validada.
        """
        pass

    @abstractmethod
    async def get_historical_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        timeframe: Timeframe = Timeframe.D1,
    ) -> List[MarketBarDTO]:
        """
        Obtiene el histórico de barras OHLCV para el rango temporal e intervalo solicitado.

        Parámetros:
        -----------
        ticker: Símbolo o especie del activo.
        start_date: Fecha inicial inclusiva.
        end_date: Fecha final inclusiva.
        timeframe: Granularidad temporal de las velas (ej. '1d', '1h', '5m').

        Retorna:
        --------
        List[MarketBarDTO]: Lista de barras OHLCV ordenadas cronológicamente.
        """
        pass

