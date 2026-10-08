"""
Caché en memoria para cotizaciones de mercado en tiempo real (Módulo 6 - Fase 3).
Utiliza time.monotonic() para evitar anomalías ante saltos del reloj del sistema y soporta TTL configurable.
"""
import time
from typing import Dict, Optional, Tuple

from app.schemas.market_data import MarketQuoteDTO


class InMemoryQuoteCache:
    """
    Caché en memoria asíncrono y liviano para MarketQuoteDTO con expiración por TTL.
    """

    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl_seconds = float(ttl_seconds)
        self._cache: Dict[str, Tuple[MarketQuoteDTO, float]] = {}

    def _normalize_key(self, ticker: str) -> str:
        return ticker.strip().upper()

    async def get(self, ticker: str) -> Optional[MarketQuoteDTO]:
        """
        Recupera la cotización si existe y aún no ha expirado su TTL.
        Retorna None si la clave no existe o si ya expiró.
        """
        key = self._normalize_key(ticker)
        entry = self._cache.get(key)
        if entry is None:
            return None

        quote, expires_at = entry
        if time.monotonic() > expires_at:
            # Entrada expirada: remoción perezosa
            self._cache.pop(key, None)
            return None

        return quote

    async def set(self, ticker: str, quote: MarketQuoteDTO) -> None:
        """
        Almacena la cotización con su tiempo límite de validez monótono.
        """
        key = self._normalize_key(ticker)
        expires_at = time.monotonic() + self.ttl_seconds
        self._cache[key] = (quote, expires_at)

    async def clear(self) -> None:
        """
        Limpia todas las entradas almacenadas en el caché.
        """
        self._cache.clear()

