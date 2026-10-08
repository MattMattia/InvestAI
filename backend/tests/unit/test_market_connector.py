"""
Pruebas unitarias para el conector HTTP de mercado y el guardián anti-SSRF (Módulo 6 - Fase 2).
Valida defensas perimetrales contra SSRF, reintentos asíncronos ante 429/503 y mapeo estricto
hacia DTOs de dominio, garantizando aislamiento total (0 llamadas reales a internet).
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
import httpx

from app.domain.services.market_connector import (
    MarketDataConnectorError,
    RateLimitExceededError,
    SecuritySSRFViolationError,
    TickerNotFoundError,
)
from app.infrastructure.market_data.http_connector import HttpMarketConnector
from app.infrastructure.market_data.ssrf_guard import (
    validate_ip_address,
    validate_url_against_ssrf,
)
from app.schemas.market_data import MarketBarDTO, MarketQuoteDTO, Timeframe


class TestSSRFGuard(unittest.TestCase):
    """Pruebas exhaustivas para el validador anti-SSRF contra vectores de ataque conocidos."""

    def test_ssrf_blocks_loopback_ipv4(self):
        """Valida el bloqueo estricto de direcciones loopback (127.0.0.0/8)."""
        vectors = [
            "http://127.0.0.1:8000/api",
            "http://127.0.0.2:9000",
            "http://127.255.255.254",
        ]
        for url in vectors:
            with self.assertRaises(SecuritySSRFViolationError):
                validate_url_against_ssrf(url)

    def test_ssrf_blocks_localhost_and_internal_domains(self):
        """Valida el bloqueo de localhost y nombres de dominio locales o internos."""
        hostnames = [
            "http://localhost:8080/quote",
            "http://localhost.localdomain/data",
            "http://database.local:5432",
            "http://service.internal/metrics",
        ]
        for url in hostnames:
            with self.assertRaises(SecuritySSRFViolationError):
                validate_url_against_ssrf(url)

    def test_ssrf_blocks_cloud_metadata_endpoints(self):
        """Valida el bloqueo de direcciones link-local y metadatos de nube (169.254.169.254)."""
        cloud_vectors = [
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.1.1/credentials",
        ]
        for url in cloud_vectors:
            with self.assertRaises(SecuritySSRFViolationError):
                validate_url_against_ssrf(url)

    def test_ssrf_blocks_rfc1918_private_ranges(self):
        """Valida el bloqueo de rangos IPv4 privados (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)."""
        private_ips = [
            "http://10.0.0.1/api",
            "http://10.254.254.254/secret",
            "http://172.16.0.1:8080",
            "http://172.31.255.255",
            "http://192.168.1.1/admin",
            "http://192.168.0.254",
            "http://0.0.0.0:80",
            "http://100.64.0.1",  # CGNAT
        ]
        for url in private_ips:
            with self.assertRaises(SecuritySSRFViolationError):
                validate_url_against_ssrf(url)

    def test_ssrf_blocks_ipv6_private_and_loopback(self):
        """Valida el bloqueo de direcciones IPv6 loopback (::1) y privadas (fc00::/7, fe80::/10)."""
        ipv6_vectors = [
            "http://[::1]:8000/quote",
            "http://[fe80::1]/link-local",
            "http://[fc00::1]/unique-local",
        ]
        for url in ipv6_vectors:
            with self.assertRaises(SecuritySSRFViolationError):
                validate_url_against_ssrf(url)

    def test_ssrf_blocks_invalid_schemes(self):
        """Valida el rechazo de esquemas distintos de http o https."""
        forbidden_schemes = [
            "file:///etc/passwd",
            "ftp://ftp.market.com/data",
            "gopher://127.0.0.1:70",
            "ldap://corp.internal",
        ]
        for url in forbidden_schemes:
            with self.assertRaises(SecuritySSRFViolationError):
                validate_url_against_ssrf(url)

    def test_ssrf_detects_malicious_resolved_dns(self):
        """Valida que un hostname público cuya resolución apunte a una IP privada sea interceptado."""
        mock_resolver_evil = lambda h: ["10.50.1.20"]
        with self.assertRaises(SecuritySSRFViolationError):
            validate_url_against_ssrf("https://evil-market-broker.com", dns_resolver=mock_resolver_evil)

    def test_ssrf_allows_public_ip_and_dns(self):
        """Valida que URLs con IPs públicas o DNS públicos válidos sean autorizadas."""
        # IP pública directa (ej. Quad9 9.9.9.9)
        valid_ip_url = "https://9.9.9.9/quotes"
        res = validate_url_against_ssrf(valid_ip_url)
        self.assertEqual(res, valid_ip_url)

        # Hostname con resolución pública inyectada
        mock_resolver_clean = lambda h: ["93.184.216.34"]
        res_dns = validate_url_against_ssrf("https://api.marketdata.com", dns_resolver=mock_resolver_clean)
        self.assertEqual(res_dns, "https://api.marketdata.com")


class TestHttpMarketConnector(unittest.IsolatedAsyncioTestCase):
    """Pruebas asíncronas para HttpMarketConnector utilizando transportes simulados (MockTransport)."""

    def setUp(self):
        # Resolver que simula IP pública para pruebas sin salida de red
        self.public_dns_resolver = lambda h: ["93.184.216.34"]
        self.base_url = "https://api.marketprovider.com"

    async def asyncTearDown(self):
        if hasattr(self, "connector") and self.connector:
            await self.connector.aclose()

    async def test_get_quote_success(self):
        """Valida la consulta exitosa y deserialización estricta hacia MarketQuoteDTO."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/quote/GGAL")
            payload = {
                "ticker": "GGAL",
                "price": "5500.50",
                "bid": "5495.00",
                "ask": "5505.00",
                "volume": "1200000",
                "timestamp": "2026-10-08T15:30:00Z",
            }
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(mock_handler)
        self.connector = HttpMarketConnector(
            base_url=self.base_url,
            transport=transport,
            dns_resolver=self.public_dns_resolver,
        )

        quote = await self.connector.get_quote("ggal")
        self.assertIsInstance(quote, MarketQuoteDTO)
        self.assertEqual(quote.ticker, "GGAL")
        self.assertEqual(quote.price, Decimal("5500.50"))
        self.assertEqual(quote.bid, Decimal("5495.00"))
        self.assertEqual(quote.ask, Decimal("5505.00"))
        self.assertEqual(quote.volume, Decimal("1200000"))
        self.assertEqual(quote.timestamp.tzinfo, timezone.utc)

    async def test_get_historical_bars_success(self):
        """Valida la consulta de barras históricas y mapeo a List[MarketBarDTO]."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/historical/AL30")
            bars_payload = [
                {
                    "timestamp": "2026-10-07T18:00:00Z",
                    "open": "120000.0",
                    "high": "125000.0",
                    "low": "119000.0",
                    "close": "124500.0",
                    "volume": "500000",
                    "vwap": "122300.0",
                },
                {
                    "timestamp": "2026-10-08T18:00:00Z",
                    "open": "124500.0",
                    "high": "128000.0",
                    "low": "123000.0",
                    "close": "127500.0",
                    "volume": "650000",
                    "vwap": "126100.0",
                },
            ]
            return httpx.Response(200, json={"bars": bars_payload})

        transport = httpx.MockTransport(mock_handler)
        self.connector = HttpMarketConnector(
            base_url=self.base_url,
            transport=transport,
            dns_resolver=self.public_dns_resolver,
        )

        bars = await self.connector.get_historical_bars(
            ticker="AL30",
            start_date=date(2026, 10, 7),
            end_date=date(2026, 10, 8),
            timeframe=Timeframe.D1,
        )

        self.assertEqual(len(bars), 2)
        for b in bars:
            self.assertIsInstance(b, MarketBarDTO)
        self.assertEqual(bars[0].open, Decimal("120000.0"))
        self.assertEqual(bars[1].close, Decimal("127500.0"))

    async def test_ticker_not_found_404(self):
        """Valida que un error HTTP 404 sea mapeado a TickerNotFoundError."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Instrument not found"})

        transport = httpx.MockTransport(mock_handler)
        self.connector = HttpMarketConnector(
            base_url=self.base_url,
            transport=transport,
            dns_resolver=self.public_dns_resolver,
        )

        with self.assertRaises(TickerNotFoundError):
            await self.connector.get_quote("NONEXISTENT")

    async def test_rate_limit_exceeded_429_retries(self):
        """Valida que HTTP 429 persistente active reintentos y lance RateLimitExceededError."""
        attempts = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(429, json={"error": "Too Many Requests"})

        transport = httpx.MockTransport(mock_handler)
        self.connector = HttpMarketConnector(
            base_url=self.base_url,
            transport=transport,
            dns_resolver=self.public_dns_resolver,
            max_retries=3,
            backoff_factor=0.0,  # Sin retardo para tests veloces
        )

        with self.assertRaises(RateLimitExceededError):
            await self.connector.get_quote("AAPL")

        # 1 intento inicial + 3 reintentos = 4 llamadas
        self.assertEqual(attempts, 4)

    async def test_transient_error_retry_and_recovery(self):
        """Valida la resiliencia ante un fallo 503 transitorio que recupera en el reintento."""
        attempts = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, json={"error": "Service Temporarily Unavailable"})
            return httpx.Response(
                200,
                json={
                    "ticker": "MSFT",
                    "price": "430.0",
                    "timestamp": "2026-10-08T15:30:00Z",
                },
            )

        transport = httpx.MockTransport(mock_handler)
        self.connector = HttpMarketConnector(
            base_url=self.base_url,
            transport=transport,
            dns_resolver=self.public_dns_resolver,
            max_retries=3,
            backoff_factor=0.0,
        )

        quote = await self.connector.get_quote("MSFT")
        self.assertEqual(quote.ticker, "MSFT")
        self.assertEqual(quote.price, Decimal("430.0"))
        self.assertEqual(attempts, 2)

    async def test_ssrf_aborts_before_socket_dispatch(self):
        """Valida que una URL base prohibida aborte inmediatamente antes de cualquier petición."""
        with self.assertRaises(SecuritySSRFViolationError):
            HttpMarketConnector(base_url="http://127.0.0.1:8000")

        with self.assertRaises(SecuritySSRFViolationError):
            HttpMarketConnector(base_url="http://169.254.169.254")

        with self.assertRaises(SecuritySSRFViolationError):
            HttpMarketConnector(base_url="http://localhost:5000")


if __name__ == "__main__":
    unittest.main()

