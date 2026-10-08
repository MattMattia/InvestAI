"""
Pruebas unitarias exhaustivas para contratos canónicos de mercado y calculadora FX (Módulo 6 - Fase 1).
Verifica inmutabilidad, sanitización de frontera (extra='forbid'), integridad geométrica OHLCV,
hardening de zona horaria UTC (offset 0), redondeo ROUND_HALF_UP (4 decimales rate, 2 decimales spread_pct)
y robustez adversarial frente a cotizaciones cero, negativas o corruptas.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from pydantic import ValidationError

from app.domain.services.fx_calculator import (
    FXCalculatorError,
    InvalidMarketPriceError,
    ZeroPriceDivisionError,
    calculate_ccl_rate,
    calculate_mep_rate,
)
from app.schemas.market_data import (
    FXRateDTO,
    FXType,
    MarketBarDTO,
    MarketQuoteDTO,
    Timeframe,
)


class TestMarketDataSchemas(unittest.TestCase):
    """Pruebas de invariantes para los DTOs de mercado y series temporales."""

    def setUp(self):
        self.now_utc = datetime(2026, 10, 8, 15, 30, 0, tzinfo=timezone.utc)

    def test_market_quote_immutability_and_extra_forbid(self):
        """Valida que MarketQuoteDTO sea inmutable (frozen) y rechace campos extra."""
        quote = MarketQuoteDTO(
            ticker="al30",
            price=Decimal("128500.00"),
            timestamp=self.now_utc,
        )

        # Inmutabilidad
        with self.assertRaises(ValidationError):
            quote.price = Decimal("130000.00")

        # Rechazo de campos extra
        with self.assertRaises(ValidationError):
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("128500.00"),
                timestamp=self.now_utc,
                unauthorized_extra_field="malicious",
            )

    def test_market_quote_ticker_normalization(self):
        """Valida que el ticker se normalice a mayúsculas y sin espacios residuales."""
        quote = MarketQuoteDTO(
            ticker="   ggal   ",
            price=Decimal("5400.0"),
            timestamp=self.now_utc,
        )
        self.assertEqual(quote.ticker, "GGAL")

        # Ticker vacío debe fallar
        with self.assertRaises(ValidationError):
            MarketQuoteDTO(
                ticker="   ",
                price=Decimal("5400.0"),
                timestamp=self.now_utc,
            )

    def test_market_quote_price_and_timestamp_validation(self):
        """Valida que los precios sean estrictamente positivos y el timestamp sea UTC estricto."""
        # Precio <= 0 debe ser rechazado
        with self.assertRaises(ValidationError):
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("0.0"),
                timestamp=self.now_utc,
            )

        with self.assertRaises(ValidationError):
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("-10.0"),
                timestamp=self.now_utc,
            )

        # Puntas bid/ask negativas o cero deben fallar
        with self.assertRaises(ValidationError):
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("100.0"),
                bid=Decimal("0.0"),
                timestamp=self.now_utc,
            )

        # Timestamp naive (sin tz) debe fallar
        naive_dt = datetime(2026, 10, 8, 15, 30, 0)
        with self.assertRaises(ValidationError) as ctx:
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("100.0"),
                timestamp=naive_dt,
            )
        self.assertIn("Timestamp must include UTC timezone information (offset 0)", str(ctx.exception))

        # Timestamp con timezone no UTC (offset != 0) debe fallar
        non_utc_dt = datetime(2026, 10, 8, 15, 30, 0, tzinfo=timezone(timedelta(hours=-3)))
        with self.assertRaises(ValidationError) as ctx:
            MarketQuoteDTO(
                ticker="AL30",
                price=Decimal("100.0"),
                timestamp=non_utc_dt,
            )
        self.assertIn("Timestamp must include UTC timezone information (offset 0)", str(ctx.exception))

        # MarketBarDTO con timezone no UTC también debe fallar
        with self.assertRaises(ValidationError) as ctx:
            MarketBarDTO(
                timestamp=non_utc_dt,
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("95.0"),
                close=Decimal("105.0"),
                volume=Decimal("1000"),
            )
        self.assertIn("Timestamp must include UTC timezone information (offset 0)", str(ctx.exception))

    def test_market_bar_immutability_and_extra_forbid(self):
        """Valida inmutabilidad y extra='forbid' en MarketBarDTO."""
        bar = MarketBarDTO(
            timestamp=self.now_utc,
            open=Decimal("100.0"),
            high=Decimal("110.0"),
            low=Decimal("95.0"),
            close=Decimal("105.0"),
            volume=Decimal("5000"),
        )
        with self.assertRaises(ValidationError):
            bar.close = Decimal("108.0")

        with self.assertRaises(ValidationError):
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("95.0"),
                close=Decimal("105.0"),
                volume=Decimal("5000"),
                hacker_field="injection",
            )

    def test_market_bar_geometric_integrity(self):
        """Valida que una barra corrupta (violación de límites OHLC) sea rechazada con error descriptivo."""
        # Caso 1: high < low
        with self.assertRaises(ValidationError) as ctx:
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("100.0"),
                high=Decimal("90.0"),
                low=Decimal("95.0"),
                close=Decimal("98.0"),
                volume=Decimal("1000"),
            )
        self.assertIn("Barra corrupta", str(ctx.exception))

        # Caso 2: low > min(open, close)
        with self.assertRaises(ValidationError) as ctx:
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("102.0"),  # low mayor que open
                close=Decimal("105.0"),
                volume=Decimal("1000"),
            )
        self.assertIn("low (102.0) no puede ser mayor que min(open, close)", str(ctx.exception))

        # Caso 3: high < max(open, close)
        with self.assertRaises(ValidationError) as ctx:
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("100.0"),
                high=Decimal("103.0"),  # high menor que close
                low=Decimal("95.0"),
                close=Decimal("105.0"),
                volume=Decimal("1000"),
            )
        self.assertIn("high (103.0) no puede ser menor que max(open, close)", str(ctx.exception))

        # Caso 4: Precios negativos o cero
        with self.assertRaises(ValidationError):
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("-10.0"),
                high=Decimal("10.0"),
                low=Decimal("-15.0"),
                close=Decimal("5.0"),
                volume=Decimal("1000"),
            )

        # Caso 5: VWAP superior a high
        with self.assertRaises(ValidationError) as ctx:
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("95.0"),
                close=Decimal("105.0"),
                volume=Decimal("1000"),
                vwap=Decimal("115.0"),
            )
        self.assertIn("vwap must be between low and high prices", str(ctx.exception))

        # Caso 6: VWAP inferior a low
        with self.assertRaises(ValidationError) as ctx:
            MarketBarDTO(
                timestamp=self.now_utc,
                open=Decimal("100.0"),
                high=Decimal("110.0"),
                low=Decimal("95.0"),
                close=Decimal("105.0"),
                volume=Decimal("1000"),
                vwap=Decimal("90.0"),
            )
        self.assertIn("vwap must be between low and high prices", str(ctx.exception))

    def test_market_bar_valid_candle_and_vwap(self):
        """Valida una vela válida con VWAP dentro del rango."""
        bar = MarketBarDTO(
            timestamp=self.now_utc,
            open=Decimal("100.0"),
            high=Decimal("112.5"),
            low=Decimal("98.0"),
            close=Decimal("110.0"),
            volume=Decimal("15000"),
            vwap=Decimal("106.25"),
        )
        self.assertEqual(bar.open, Decimal("100.0"))
        self.assertEqual(bar.high, Decimal("112.5"))
        self.assertEqual(bar.vwap, Decimal("106.25"))


class TestFXCalculatorService(unittest.TestCase):
    """Pruebas unitarias para el servicio cuantitativo fx_calculator."""

    def setUp(self):
        self.now_utc = datetime(2026, 10, 8, 16, 0, 0, tzinfo=timezone.utc)

    def test_calculate_mep_rate_normal_scenario(self):
        """Valida el cálculo de Dólar MEP con AL30 en ARS vs AL30D en USD con escala estricta."""
        local_quote = MarketQuoteDTO(
            ticker="AL30",
            price=Decimal("128000.00"),
            bid=Decimal("127500.00"),
            ask=Decimal("128500.00"),
            timestamp=self.now_utc,
        )
        usd_quote = MarketQuoteDTO(
            ticker="AL30D",
            price=Decimal("100.00"),
            bid=Decimal("99.50"),
            ask=Decimal("100.50"),
            timestamp=self.now_utc,
        )

        res = calculate_mep_rate(local_quote, usd_quote)

        self.assertIsInstance(res, FXRateDTO)
        self.assertEqual(res.fx_type, FXType.MEP)
        self.assertEqual(res.base_ticker, "AL30")
        self.assertEqual(res.quote_ticker, "AL30D")
        self.assertEqual(res.rate, Decimal("1280.0000"))
        self.assertEqual(res.rate.as_tuple().exponent, -4)

        # Verificación del spread bid-ask implícito
        # mep_bid = 127500 / 100.50 = 1268.656716...
        # mep_ask = 128500 / 99.50 = 1291.457286...
        # raw_spread = ((mep_ask - mep_bid) / 1280.0000) * 100 = 1.78129... -> 1.78
        self.assertIsNotNone(res.spread_pct)
        self.assertEqual(res.spread_pct, Decimal("1.78"))
        self.assertEqual(res.spread_pct.as_tuple().exponent, -2)

    def test_calculate_mep_without_spread_info(self):
        """Valida que si alguna cotización carece de puntas bid/ask, spread_pct sea None."""
        local_quote = MarketQuoteDTO(
            ticker="GD30",
            price=Decimal("130000.00"),
            timestamp=self.now_utc,
        )
        usd_quote = MarketQuoteDTO(
            ticker="GD30D",
            price=Decimal("100.00"),
            timestamp=self.now_utc,
        )

        res = calculate_mep_rate(local_quote, usd_quote)
        self.assertEqual(res.rate, Decimal("1300.0000"))
        self.assertEqual(res.rate.as_tuple().exponent, -4)
        self.assertIsNone(res.spread_pct)

    def test_calculate_mep_with_incomplete_or_invalid_bids_asks(self):
        """Valida que puntas en None o <= 0 anulen defensivamente spread_pct conservando rate cuantizado."""
        # Caso 1: local_quote sin ask
        local_partial = MarketQuoteDTO(
            ticker="AL30",
            price=Decimal("128000.00"),
            bid=Decimal("127500.00"),
            ask=None,
            timestamp=self.now_utc,
        )
        usd_full = MarketQuoteDTO(
            ticker="AL30D",
            price=Decimal("100.00"),
            bid=Decimal("99.50"),
            ask=Decimal("100.50"),
            timestamp=self.now_utc,
        )
        res1 = calculate_mep_rate(local_partial, usd_full)
        self.assertEqual(res1.rate, Decimal("1280.0000"))
        self.assertEqual(res1.rate.as_tuple().exponent, -4)
        self.assertIsNone(res1.spread_pct)

        # Caso 2: usd_quote sin bid
        local_full = MarketQuoteDTO(
            ticker="AL30",
            price=Decimal("128000.00"),
            bid=Decimal("127500.00"),
            ask=Decimal("128500.00"),
            timestamp=self.now_utc,
        )
        usd_partial = MarketQuoteDTO(
            ticker="AL30D",
            price=Decimal("100.00"),
            bid=None,
            ask=Decimal("100.50"),
            timestamp=self.now_utc,
        )
        res2 = calculate_mep_rate(local_full, usd_partial)
        self.assertEqual(res2.rate, Decimal("1280.0000"))
        self.assertEqual(res2.rate.as_tuple().exponent, -4)
        self.assertIsNone(res2.spread_pct)

        # Caso 3: cotización con punta bid <= 0 (vía mock)
        class MockZeroBidQuote:
            ticker = "AL30"
            price = Decimal("128000.00")
            bid = Decimal("0.0")
            ask = Decimal("128500.00")
            timestamp = datetime(2026, 10, 8, 16, 0, 0, tzinfo=timezone.utc)

        res3 = calculate_mep_rate(MockZeroBidQuote(), usd_full)
        self.assertEqual(res3.rate, Decimal("1280.0000"))
        self.assertEqual(res3.rate.as_tuple().exponent, -4)
        self.assertIsNone(res3.spread_pct)

    def test_calculate_ccl_rate_normal_scenario(self):
        """Valida el cálculo de Dólar CCL con acción local de GGAL y ADR en NY (ratio 10:1)."""
        local_quote = MarketQuoteDTO(
            ticker="GGAL",
            price=Decimal("5500.00"),
            bid=Decimal("5480.00"),
            ask=Decimal("5520.00"),
            timestamp=self.now_utc,
        )
        adr_quote = MarketQuoteDTO(
            ticker="GGAL.US",
            price=Decimal("44.00"),
            bid=Decimal("43.80"),
            ask=Decimal("44.20"),
            timestamp=self.now_utc,
        )
        conversion_ratio = Decimal("10")  # 1 ADR = 10 acciones locales

        res = calculate_ccl_rate(local_quote, adr_quote, conversion_ratio)

        self.assertIsInstance(res, FXRateDTO)
        self.assertEqual(res.fx_type, FXType.CCL)
        self.assertEqual(res.base_ticker, "GGAL")
        self.assertEqual(res.quote_ticker, "GGAL.US")
        # (5500 * 10) / 44 = 55000 / 44 = 1250.0000
        self.assertEqual(res.rate, Decimal("1250.0000"))
        self.assertEqual(res.rate.as_tuple().exponent, -4)
        self.assertIsNotNone(res.spread_pct)
        # ccl_bid = (5480 * 10) / 44.20 = 54800 / 44.20 = 1239.8190...
        # ccl_ask = (5520 * 10) / 43.80 = 55200 / 43.80 = 1260.2739...
        # raw_spread = ((1260.2739... - 1239.8190...) / 1250) * 100 = 1.6363... -> 1.64
        self.assertEqual(res.spread_pct, Decimal("1.64"))
        self.assertEqual(res.spread_pct.as_tuple().exponent, -2)

    def test_calculate_ccl_conversion_ratio_formats(self):
        """Valida que conversion_ratio acepte int, float, str o Decimal de forma transparente."""
        local = MarketQuoteDTO(ticker="AAPL", price=Decimal("12500.00"), timestamp=self.now_utc)
        adr = MarketQuoteDTO(ticker="AAPL.US", price=Decimal("100.00"), timestamp=self.now_utc)

        # Ratio 10 en distintos formatos
        r_dec = calculate_ccl_rate(local, adr, Decimal("10"))
        r_int = calculate_ccl_rate(local, adr, 10)
        r_flt = calculate_ccl_rate(local, adr, 10.0)
        r_str = calculate_ccl_rate(local, adr, "10")

        self.assertEqual(r_dec.rate, Decimal("1250.0000"))
        self.assertEqual(r_dec.rate.as_tuple().exponent, -4)
        self.assertEqual(r_int.rate, r_dec.rate)
        self.assertEqual(r_flt.rate, r_dec.rate)
        self.assertEqual(r_str.rate, r_dec.rate)

    def test_adversarial_zero_and_negative_prices(self):
        """Somete a estrés adversarial frente a cotizaciones nulas, cero o corruptas."""
        valid_local = MarketQuoteDTO(ticker="AL30", price=Decimal("1000.0"), timestamp=self.now_utc)
        valid_usd = MarketQuoteDTO(ticker="AL30D", price=Decimal("1.0"), timestamp=self.now_utc)

        # Mock de cotización cero usando object/dict bypass o simulación directa
        class CorruptQuote:
            ticker = "CORRUPT"
            price = Decimal("0.0")
            bid = None
            ask = None
            timestamp = datetime(2026, 10, 8, 16, 0, 0, tzinfo=timezone.utc)

        corrupt_zero = CorruptQuote()

        # División por cero en MEP
        with self.assertRaises(ZeroPriceDivisionError):
            calculate_mep_rate(valid_local, corrupt_zero)

        # Precio local cero en MEP
        with self.assertRaises(InvalidMarketPriceError):
            calculate_mep_rate(corrupt_zero, valid_usd)

        # División por cero en CCL
        with self.assertRaises(ZeroPriceDivisionError):
            calculate_ccl_rate(valid_local, corrupt_zero, Decimal("10"))

        # Ratio de conversión cero o negativo
        with self.assertRaises(InvalidMarketPriceError):
            calculate_ccl_rate(valid_local, valid_usd, Decimal("0"))

        with self.assertRaises(InvalidMarketPriceError):
            calculate_ccl_rate(valid_local, valid_usd, Decimal("-5"))

    def test_decimal_precision_immunity_to_float_drift(self):
        """Valida que los cálculos mantengan precisión Decimal estricta sin deriva binaria de coma flotante."""
        local = MarketQuoteDTO(ticker="TEST", price=Decimal("335.1234"), timestamp=self.now_utc)
        usd = MarketQuoteDTO(ticker="TESTD", price=Decimal("0.3125"), timestamp=self.now_utc)

        res = calculate_mep_rate(local, usd)
        # 335.1234 / 0.3125 = 1072.39488 -> quantize(0.0001, ROUND_HALF_UP) = 1072.3949
        self.assertEqual(res.rate, Decimal("1072.3949"))
        self.assertEqual(res.rate.as_tuple().exponent, -4)
        self.assertIsInstance(res.rate, Decimal)


if __name__ == "__main__":
    unittest.main()
