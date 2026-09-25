import unittest
from datetime import date, datetime

from app.domain.models.calendar import MarketExchange, QuoteState
from app.domain.services.calendar_service import MarketCalendarService
from app.domain.services.fx_service import FXService


class TestMarketCalendar(unittest.TestCase):
    def setUp(self) -> None:
        self.calendar = MarketCalendarService(fx_service=FXService())

    def test_weekend_closure(self) -> None:
        # Saturday Jan 24, 2026 & Sunday Jan 25, 2026
        sat = date(2026, 1, 24)
        sun = date(2026, 1, 25)

        self.assertFalse(self.calendar.is_market_open(MarketExchange.BYMA, sat))
        self.assertFalse(self.calendar.is_market_open(MarketExchange.BYMA, sun))
        self.assertFalse(self.calendar.is_market_open(MarketExchange.NYSE, sat))
        self.assertFalse(self.calendar.is_market_open(MarketExchange.NYSE, sun))

    def test_cross_holiday_divergences(self) -> None:
        # Case A: BYMA Holiday (Día de la Memoria - Tuesday Mar 24, 2026), but NYSE is OPEN
        byma_holiday = date(2026, 3, 24)
        self.assertFalse(self.calendar.is_market_open(MarketExchange.BYMA, byma_holiday))
        self.assertTrue(self.calendar.is_market_open(MarketExchange.NYSE, byma_holiday))

        # Case B: US Holiday (MLK Day - Monday Jan 19, 2026), but BYMA is OPEN
        nyse_holiday = date(2026, 1, 19)
        self.assertTrue(self.calendar.is_market_open(MarketExchange.BYMA, nyse_holiday))
        self.assertFalse(self.calendar.is_market_open(MarketExchange.NYSE, nyse_holiday))

        # Case C: Both markets OPEN on a standard Wednesday (Jan 21, 2026)
        normal_day = date(2026, 1, 21)
        self.assertTrue(self.calendar.is_market_open(MarketExchange.BYMA, normal_day))
        self.assertTrue(self.calendar.is_market_open(MarketExchange.NYSE, normal_day))

        # Case D: Both markets closed on New Year's Day (Jan 1, 2026)
        new_year = date(2026, 1, 1)
        self.assertFalse(self.calendar.is_market_open(MarketExchange.BYMA, new_year))
        self.assertFalse(self.calendar.is_market_open(MarketExchange.NYSE, new_year))

    def test_synchronize_asset_prices_byma_holiday(self) -> None:
        # Tuesday Mar 24, 2026: BYMA closed, NYSE active
        target_date = date(2026, 3, 24)

        # AAPL: Forward-filled BYMA price $29,900 ARS; Live NYSE quote $230.00 USD; Ratio 10:1
        synced = self.calendar.synchronize_asset_prices(
            ticker="AAPL",
            byma_quote=29900.0,
            nyse_quote=230.0,
            target_date=target_date,
            conversion_ratio=10.0,
        )

        self.assertEqual(synced.ticker, "AAPL")
        self.assertEqual(synced.byma_price, 29900.0)
        self.assertEqual(synced.nyse_price, 230.0)
        self.assertEqual(synced.byma_status, QuoteState.STALE_MARKET_CLOSED)
        self.assertEqual(synced.nyse_status, QuoteState.ACTIVE)
        self.assertTrue(synced.is_stale)
        self.assertIn("BYMA cerrada por feriado local", synced.stale_reason or "")
        self.assertEqual(synced.implicit_ccl, 1300.0)

    def test_synchronize_asset_prices_nyse_holiday(self) -> None:
        # Monday Jan 19, 2026: NYSE closed (MLK Day), BYMA active
        target_date = date(2026, 1, 19)

        # NVDA: Live BYMA price $87,750 ARS; Forward-filled NYSE price $135.00 USD; Ratio 2:1
        synced = self.calendar.synchronize_asset_prices(
            ticker="NVDA",
            byma_quote={"price": 87750.0, "date": target_date},
            nyse_quote={"price": 135.0, "date": date(2026, 1, 16)},
            target_date=target_date,
            conversion_ratio="2:1",
        )

        self.assertEqual(synced.ticker, "NVDA")
        self.assertEqual(synced.byma_status, QuoteState.ACTIVE)
        self.assertEqual(synced.nyse_status, QuoteState.STALE_MARKET_CLOSED)
        self.assertTrue(synced.is_stale)
        self.assertIn("NYSE/NASDAQ cerrada por feriado en EE.UU.", synced.stale_reason or "")
        self.assertEqual(synced.implicit_ccl, 1300.0)

    def test_synchronize_asset_prices_both_active(self) -> None:
        # Wednesday Jan 21, 2026: Both open
        target_date = date(2026, 1, 21)

        synced = self.calendar.synchronize_asset_prices(
            ticker="AAPL",
            byma_quote=29900.0,
            nyse_quote=230.0,
            target_date=target_date,
            conversion_ratio=10.0,
        )

        self.assertEqual(synced.byma_status, QuoteState.ACTIVE)
        self.assertEqual(synced.nyse_status, QuoteState.ACTIVE)
        self.assertFalse(synced.is_stale)
        self.assertIsNone(synced.stale_reason)
        self.assertEqual(synced.implicit_ccl, 1300.0)

    def test_get_last_trading_day(self) -> None:
        # Sunday Jan 25, 2026 -> should return Friday Jan 23, 2026
        sun = date(2026, 1, 25)
        last_byma = self.calendar.get_last_trading_day(MarketExchange.BYMA, sun)
        last_nyse = self.calendar.get_last_trading_day(MarketExchange.NYSE, sun)

        self.assertEqual(last_byma, date(2026, 1, 23))
        self.assertEqual(last_nyse, date(2026, 1, 23))


if __name__ == "__main__":
    unittest.main()
