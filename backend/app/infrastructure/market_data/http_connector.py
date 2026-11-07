"""
Conector HTTP asíncrono para ingesta de cotizaciones y series de mercado (Módulo 6 - Fase 2).
Implementa cliente httpx con blindaje anti-SSRF, reintentos con backoff exponencial,
desactivación de redirecciones y mapeo estricto a DTOs canónicos de dominio.
"""

import asyncio
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import httpx

from app.domain.services.market_connector import (
    BaseMarketConnector,
    MarketDataConnectorError,
    RateLimitExceededError,
    TickerNotFoundError,
)
from app.infrastructure.market_data.ssrf_guard import validate_url_against_ssrf
from app.schemas.market_data import MarketBarDTO, MarketQuoteDTO, Timeframe


class HttpMarketConnector(BaseMarketConnector):
    """
    Conector de red asíncrono para proveedores de datos de mercado RESTful.
    Protegido contra SSRF, con timeouts estrictos y política de reintentos configurable.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: httpx.Timeout | None = None,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        dns_resolver: Callable[[str], list[str]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        """
        Inicializa y valida el conector HTTP.

        Parámetros:
        -----------
        base_url: URL raíz del proveedor de mercado (debe pasar el guardián anti-SSRF).
        api_key: Clave de autenticación API opcional.
        timeout: Configuración granular de timeouts httpx (default: connect=3s, read=5s, write=3s).
        max_retries: Cantidad máxima de reintentos ante 429/503 o errores de red.
        backoff_factor: Factor multiplicador para el retroceso exponencial (usar 0.0 en tests).
        dns_resolver: Inyector opcional para resolución de nombres (utilizado en testing aislado).
        transport: Transporte personalizado de httpx (ej. MockTransport para tests).
        """
        # 1. Validación estricta anti-SSRF de la URL base
        self.dns_resolver = dns_resolver
        validate_url_against_ssrf(base_url, dns_resolver=self.dns_resolver)

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self.timeout = timeout or httpx.Timeout(
            timeout=10.0,
            connect=3.0,
            read=5.0,
            write=3.0,
        )

        headers = {
            "Accept": "application/json",
            "User-Agent": "InvestAI-MarketConnector/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # 2. Configurar cliente httpx con follow_redirects=False (prevención de DNS rebinding)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            follow_redirects=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Cierra el cliente HTTP y libera los sockets y conexiones activas."""
        await self._client.aclose()

    async def __aenter__(self) -> "HttpMarketConnector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def _execute_request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
    ) -> dict | list:
        """
        Ejecuta la solicitud HTTP con verificación SSRF previa y reintentos exponenciales.
        """
        clean_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        target_url = f"{self.base_url}{clean_endpoint}"

        # Validación previa antes de iniciar socket de red
        validate_url_against_ssrf(target_url, dns_resolver=self.dns_resolver)

        retries = 0
        while retries <= self.max_retries:
            try:
                response = await self._client.request(
                    method=method,
                    url=clean_endpoint,
                    params=params,
                )

                if response.status_code == 200:
                    try:
                        return response.json()
                    except Exception as json_err:
                        raise MarketDataConnectorError(
                            f"Respuesta con formato JSON inválido desde {target_url}: {json_err}"
                        ) from json_err

                if response.status_code == 404:
                    raise TickerNotFoundError(
                        f"Activo no encontrado en el proveedor (HTTP 404): {clean_endpoint}"
                    )

                # Reintentos ante 429 (Rate Limit) o 503 (Service Unavailable)
                if response.status_code in (429, 503):
                    if retries < self.max_retries:
                        retries += 1
                        if self.backoff_factor > 0:
                            delay = self.backoff_factor * (2 ** (retries - 1))
                            await asyncio.sleep(delay)
                        continue
                    else:
                        if response.status_code == 429:
                            raise RateLimitExceededError(
                                f"Tasa de peticiones excedida (HTTP 429) tras {retries} reintentos en {target_url}."
                            )
                        raise MarketDataConnectorError(
                            f"Servicio no disponible (HTTP 503) tras {retries} reintentos en {target_url}."
                        )

                # Cualquier otro código de error HTTP
                raise MarketDataConnectorError(
                    f"Error HTTP {response.status_code} desde {target_url}: {response.text}"
                )

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if retries < self.max_retries:
                    retries += 1
                    if self.backoff_factor > 0:
                        delay = self.backoff_factor * (2 ** (retries - 1))
                        await asyncio.sleep(delay)
                    continue
                raise MarketDataConnectorError(
                    f"Fallo de conectividad o timeout tras {retries} reintentos: {exc}"
                ) from exc

        raise MarketDataConnectorError(f"Agotados los reintentos para {target_url}.")

    async def get_quote(self, ticker: str) -> MarketQuoteDTO:
        """
        Consulta y deserializa la cotización en tiempo real para el ticker indicado.
        """
        normalized_ticker = ticker.strip().upper()
        raw_data = await self._execute_request(
            method="GET",
            endpoint=f"/quote/{normalized_ticker}",
        )

        data = raw_data.get("data", raw_data) if isinstance(raw_data, dict) else raw_data

        if not isinstance(data, dict):
            raise MarketDataConnectorError(
                f"Estructura inesperada para cotización de {ticker}: se esperaba dict."
            )

        # Mapeo y validación estricta hacia MarketQuoteDTO
        try:
            return MarketQuoteDTO(
                ticker=data.get("ticker", normalized_ticker),
                price=Decimal(str(data["price"])),
                bid=Decimal(str(data["bid"])) if data.get("bid") is not None else None,
                ask=Decimal(str(data["ask"])) if data.get("ask") is not None else None,
                volume=Decimal(str(data.get("volume", 0))),
                timestamp=data["timestamp"],
            )
        except (KeyError, ValueError) as err:
            raise MarketDataConnectorError(
                f"Error al deserializar cotización de '{ticker}': {err}"
            ) from err

    async def get_historical_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        timeframe: Timeframe = Timeframe.D1,
    ) -> list[MarketBarDTO]:
        """
        Consulta y deserializa la serie de velas OHLCV para el rango temporal solicitado.
        """
        normalized_ticker = ticker.strip().upper()
        params = {
            "ticker": normalized_ticker,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timeframe": timeframe.value,
        }

        raw_data = await self._execute_request(
            method="GET",
            endpoint=f"/historical/{normalized_ticker}",
            params=params,
        )

        if isinstance(raw_data, list):
            bars_list = raw_data
        elif isinstance(raw_data, dict):
            bars_list = raw_data.get("bars", raw_data.get("data", []))
        else:
            raise MarketDataConnectorError(
                f"Formato inesperado para barras históricas de {ticker}."
            )

        parsed_bars: list[MarketBarDTO] = []
        for idx, bar_item in enumerate(bars_list):
            try:
                parsed_bars.append(
                    MarketBarDTO(
                        timestamp=bar_item["timestamp"],
                        open=Decimal(str(bar_item["open"])),
                        high=Decimal(str(bar_item["high"])),
                        low=Decimal(str(bar_item["low"])),
                        close=Decimal(str(bar_item["close"])),
                        volume=Decimal(str(bar_item.get("volume", 0))),
                        vwap=Decimal(str(bar_item["vwap"]))
                        if bar_item.get("vwap") is not None
                        else None,
                    )
                )
            except (KeyError, ValueError) as err:
                raise MarketDataConnectorError(
                    f"Error al deserializar barra histórica #{idx} para '{ticker}': {err}"
                ) from err

        return parsed_bars
