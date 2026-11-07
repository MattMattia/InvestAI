from datetime import date, datetime, timedelta
from typing import Any

from app.domain.models.calendar import (
    MarketExchange,
    QuoteState,
    SynchronizedPriceQuote,
)
from app.domain.services.fx_service import FXService


class MarketCalendarService:
    """
    Service for financial market calendar verification and cross-exchange price synchronization.
    Supports BYMA (Argentina) and NYSE/NASDAQ (US), applying deterministic forward-fill
    and stale-state tagging during cross-market holiday divergences.
    """

    def __init__(self, fx_service: FXService | None = None) -> None:
        self.fx_service = fx_service or FXService()
        self._byma_holidays = self._initialize_byma_holidays()
        self._nyse_holidays = self._initialize_nyse_holidays()

    @staticmethod
    def _initialize_byma_holidays() -> set[date]:
        """
        Populates key historical and upcoming Argentine market holidays (BYMA).
        Includes national holidays, bank holidays, and floating holidays (2024-2027).
        """
        holidays: set[date] = set()

        # Fixed holidays across years (2024 to 2027)
        for year in range(2024, 2028):
            holidays.add(date(year, 1, 1))  # Año Nuevo
            holidays.add(date(year, 3, 24))  # Día de la Memoria
            holidays.add(date(year, 4, 2))  # Veterano y Caídos en Malvinas
            holidays.add(date(year, 5, 1))  # Día del Trabajador
            holidays.add(date(year, 5, 25))  # Revolución de Mayo
            holidays.add(date(year, 6, 20))  # Paso a la Inmortalidad de Belgrano
            holidays.add(date(year, 7, 9))  # Día de la Independencia
            holidays.add(date(year, 12, 8))  # Inmaculada Concepción
            holidays.add(date(year, 12, 25))  # Navidad
            holidays.add(date(year, 12, 31))  # Feriado Bancario / Fin de Año

        # Floating / Carnival / Easter / Bridge holidays
        # 2024
        holidays.update(
            {
                date(2024, 2, 12),
                date(2024, 2, 13),  # Carnaval
                date(2024, 3, 28),
                date(2024, 3, 29),  # Jueves y Viernes Santo
                date(2024, 4, 1),  # Feriado Puente
                date(2024, 6, 17),  # Güemes
                date(2024, 6, 21),  # Feriado Puente
                date(2024, 10, 11),  # Feriado Puente
                date(2024, 11, 18),  # Soberanía Nacional
            }
        )

        # 2025
        holidays.update(
            {
                date(2025, 3, 3),
                date(2025, 3, 4),  # Carnaval
                date(2025, 4, 17),
                date(2025, 4, 18),  # Jueves y Viernes Santo
                date(2025, 5, 2),  # Feriado Puente
                date(2025, 6, 16),  # Güemes
                date(2025, 8, 18),  # San Martín
                date(2025, 10, 13),  # Diversidad Cultural
                date(2025, 11, 24),  # Soberanía Nacional
            }
        )

        # 2026
        holidays.update(
            {
                date(2026, 2, 16),
                date(2026, 2, 17),  # Carnaval
                date(2026, 4, 2),
                date(2026, 4, 3),  # Jueves y Viernes Santo
                date(2026, 6, 15),  # Güemes
                date(2026, 8, 17),  # San Martín
                date(2026, 10, 12),  # Diversidad Cultural
                date(2026, 11, 23),  # Soberanía Nacional
            }
        )

        # 2027
        holidays.update(
            {
                date(2027, 2, 8),
                date(2027, 2, 9),  # Carnaval
                date(2027, 3, 25),
                date(2027, 3, 26),  # Jueves y Viernes Santo
                date(2027, 6, 21),  # Güemes
                date(2027, 8, 16),  # San Martín
                date(2027, 10, 11),  # Diversidad Cultural
                date(2027, 11, 22),  # Soberanía Nacional
            }
        )

        return holidays

    @staticmethod
    def _initialize_nyse_holidays() -> set[date]:
        """
        Populates key historical and upcoming US market holidays (NYSE & NASDAQ).
        Includes MLK Day, Washington's Birthday, Good Friday, Memorial Day, Juneteenth,
        Independence Day, Labor Day, Thanksgiving, and Christmas.
        """
        holidays: set[date] = set()

        for year in range(2024, 2028):
            holidays.add(date(year, 1, 1))  # New Year's Day
            holidays.add(date(year, 6, 19))  # Juneteenth
            holidays.add(date(year, 7, 4))  # Independence Day
            holidays.add(date(year, 12, 25))  # Christmas Day

        # 2024
        holidays.update(
            {
                date(2024, 1, 15),  # Martin Luther King Jr. Day
                date(2024, 2, 19),  # Washington's Birthday (Presidents' Day)
                date(2024, 3, 29),  # Good Friday
                date(2024, 5, 27),  # Memorial Day
                date(2024, 9, 2),  # Labor Day
                date(2024, 11, 28),  # Thanksgiving Day
            }
        )

        # 2025
        holidays.update(
            {
                date(2025, 1, 20),  # MLK Day
                date(2025, 2, 17),  # Presidents' Day
                date(2025, 4, 18),  # Good Friday
                date(2025, 5, 26),  # Memorial Day
                date(2025, 9, 1),  # Labor Day
                date(2025, 11, 27),  # Thanksgiving Day
            }
        )

        # 2026
        holidays.update(
            {
                date(2026, 1, 19),  # MLK Day
                date(2026, 2, 16),  # Presidents' Day
                date(2026, 4, 3),  # Good Friday
                date(2026, 5, 25),  # Memorial Day
                date(2026, 9, 7),  # Labor Day
                date(2026, 11, 26),  # Thanksgiving Day
            }
        )

        # 2027
        holidays.update(
            {
                date(2027, 1, 18),  # MLK Day
                date(2027, 2, 15),  # Presidents' Day
                date(2027, 3, 26),  # Good Friday
                date(2027, 5, 31),  # Memorial Day
                date(2027, 9, 6),  # Labor Day
                date(2027, 11, 25),  # Thanksgiving Day
            }
        )

        return holidays

    def is_market_open(
        self,
        exchange: MarketExchange | str,
        dt: datetime | date,
    ) -> bool:
        """
        Determines if a given exchange is open for trading on a specified date/datetime.
        Returns False for weekends and recognized market holidays.
        """
        d = dt.date() if isinstance(dt, datetime) else dt
        # 0 = Monday, 6 = Sunday
        if d.weekday() >= 5:
            return False

        ex_str = exchange.value if isinstance(exchange, MarketExchange) else str(exchange).upper()
        if ex_str == "BYMA":
            return d not in self._byma_holidays
        elif ex_str in {"NYSE", "NASDAQ"}:
            return d not in self._nyse_holidays
        else:
            raise ValueError(f"Exchange no soportado: {exchange}")

    def get_last_trading_day(
        self,
        exchange: MarketExchange | str,
        from_date: datetime | date,
    ) -> date:
        """
        Returns the most recent active trading day strictly on or before from_date.
        """
        current = from_date.date() if isinstance(from_date, datetime) else from_date
        while not self.is_market_open(exchange, current):
            current -= timedelta(days=1)
        return current

    def synchronize_asset_prices(
        self,
        ticker: str,
        byma_quote: float | int | dict[str, Any],
        nyse_quote: float | int | dict[str, Any],
        target_date: date | datetime,
        conversion_ratio: float | int | str = 1.0,
    ) -> SynchronizedPriceQuote:
        """
        Cross-market synchronization of dual-listed asset prices (BYMA CEDEAR vs US Underlying).
        Applies deterministic Forward-Fill when one exchange is closed on local holiday,
        marking quotes as ACTIVE or STALE_MARKET_CLOSED and calculating the effective CCL.
        """
        d = target_date.date() if isinstance(target_date, datetime) else target_date

        # Extract numeric prices
        byma_px = float(byma_quote["price"] if isinstance(byma_quote, dict) else byma_quote)
        nyse_px = float(nyse_quote["price"] if isinstance(nyse_quote, dict) else nyse_quote)

        byma_open = self.is_market_open(MarketExchange.BYMA, d)
        nyse_open = self.is_market_open(MarketExchange.NYSE, d)

        byma_status = QuoteState.ACTIVE if byma_open else QuoteState.STALE_MARKET_CLOSED
        nyse_status = QuoteState.ACTIVE if nyse_open else QuoteState.STALE_MARKET_CLOSED

        is_stale = (byma_status == QuoteState.STALE_MARKET_CLOSED) or (
            nyse_status == QuoteState.STALE_MARKET_CLOSED
        )
        stale_reasons = []

        if not byma_open and nyse_open:
            stale_reasons.append(
                "Plaza BYMA cerrada por feriado local; precio en ARS forward-filled."
            )
        elif byma_open and not nyse_open:
            stale_reasons.append(
                "Plaza NYSE/NASDAQ cerrada por feriado en EE.UU.; precio en USD forward-filled."
            )
        elif not byma_open and not nyse_open:
            stale_reasons.append("Ambas plazas cerradas por feriado o fin de semana.")

        stale_reason = " ".join(stale_reasons) if stale_reasons else None

        # Compute implicit CCL if both prices are valid
        implicit_ccl = None
        if byma_px > 0 and nyse_px > 0:
            implicit_ccl = self.fx_service.calculate_implicit_ccl(
                cedear_price_ars=byma_px,
                underlying_price_usd=nyse_px,
                conversion_ratio=conversion_ratio,
            )

        return SynchronizedPriceQuote(
            ticker=ticker.upper().strip(),
            target_date=d,
            byma_price=round(byma_px, 2),
            nyse_price=round(nyse_px, 2),
            byma_status=byma_status,
            nyse_status=nyse_status,
            is_stale=is_stale,
            implicit_ccl=implicit_ccl,
            stale_reason=stale_reason,
        )
