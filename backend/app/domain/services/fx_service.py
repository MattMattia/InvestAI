import re
from datetime import datetime, timezone
from typing import Dict, Optional, Union

from app.domain.models.fx import Currency, FXQuote


class FXService:
    """
    Deterministic Foreign Exchange & Bimonetary Normalization Service.
    Implements institutional-grade currency conversion between ARS and USD variants (MEP, CCL)
    and deterministic computation of implicit Contado con Liquidación (CCL) for CEDEARs.
    """

    DEFAULT_FALLBACK_RATES: Dict[str, float] = {
        "USD/ARS": 1300.0,
        "USD_CCL/ARS": 1300.0,
        "USD_MEP/ARS": 1260.0,
        "USD_CCL/USD": 1.0,
        "USD_MEP/USD": 1.0,
    }

    def __init__(self, initial_quotes: Optional[Dict[str, FXQuote]] = None) -> None:
        self._quotes: Dict[str, FXQuote] = {}
        if initial_quotes:
            for pair, quote in initial_quotes.items():
                self.register_quote(quote)

    def register_quote(self, quote: FXQuote) -> None:
        """Stores or updates an FX quote in the local memory registry."""
        normalized_pair = quote.pair.strip().upper()
        self._quotes[normalized_pair] = quote

    def get_quote(self, pair: str) -> Optional[FXQuote]:
        """Retrieves a registered quote by canonical pair string (e.g. 'USD_CCL/ARS')."""
        return self._quotes.get(pair.strip().upper())

    def get_rate(self, pair: str, fallback_rate: Optional[float] = None) -> float:
        """
        Retrieves the rate for a given pair. If explicit fallback_rate is provided,
        uses it. Otherwise looks up registered quotes, and finally DEFAULT_FALLBACK_RATES.
        """
        if fallback_rate is not None and fallback_rate > 0:
            return fallback_rate
        norm_pair = pair.strip().upper()
        if norm_pair in self._quotes:
            return self._quotes[norm_pair].rate
        if norm_pair in self.DEFAULT_FALLBACK_RATES:
            return self.DEFAULT_FALLBACK_RATES[norm_pair]
        raise ValueError(
            f"Tipo de cambio no disponible para el par '{pair}' y sin tasa de fallback configurada."
        )

    @staticmethod
    def parse_conversion_ratio(conversion_ratio: Union[float, int, str]) -> float:
        """
        Parses and validates a CEDEAR conversion ratio.
        Accepts numeric values (e.g. 10.0, 2) or ratio notation strings (e.g. '10:1', '2:1', '1/2').
        Returns the effective numeric multiplier (number of CEDEARs per 1 underlying share).
        """
        if isinstance(conversion_ratio, (int, float)):
            ratio = float(conversion_ratio)
            if ratio <= 0:
                raise ValueError("El ratio de conversión de CEDEAR debe ser estrictamente positivo (> 0).")
            return ratio

        if isinstance(conversion_ratio, str):
            clean_str = conversion_ratio.strip().replace(" ", "")
            # Check notation like '10:1' or '10/1'
            match = re.match(r"^(\d+(?:\.\d+)?)(?:[:/](\d+(?:\.\d+)?))?$", clean_str)
            if not match:
                raise ValueError(
                    f"Formato de ratio de CEDEAR inválido '{conversion_ratio}'. Ejemplos válidos: '10:1', '2:1', 10.0."
                )
            num = float(match.group(1))
            den = float(match.group(2)) if match.group(2) else 1.0
            if den <= 0 or num <= 0:
                raise ValueError("Los componentes del ratio deben ser estrictamente positivos.")
            return num / den

        raise TypeError(f"Tipo no soportado para conversion_ratio: {type(conversion_ratio)}")

    def calculate_implicit_ccl(
        self,
        cedear_price_ars: float,
        underlying_price_usd: float,
        conversion_ratio: Union[float, int, str],
    ) -> float:
        """
        Calculates the implicit CCL (Contado con Liquidación) exchange rate for a CEDEAR.
        
        Formula:
            CCL_implicito = (precio_cedear_ars * conversion_ratio) / precio_subyacente_usd

        Example:
            - NVDA (ratio 2:1): CEDEAR = $125.000 ARS, Underlying = $192.30 USD
              CCL = (125.000 * 2) / 192.30 = 1300.05 ARS/USD
            - AAPL (ratio 10:1): CEDEAR = $30.000 ARS, Underlying = $230.77 USD
              CCL = (30.000 * 10) / 230.77 = 1300.00 ARS/USD
        """
        if cedear_price_ars <= 0:
            raise ValueError("El precio del CEDEAR en ARS debe ser estrictamente positivo (> 0).")
        if underlying_price_usd <= 0:
            raise ValueError("El precio del activo subyacente en USD debe ser estrictamente positivo (> 0).")

        ratio = self.parse_conversion_ratio(conversion_ratio)
        ccl = (cedear_price_ars * ratio) / underlying_price_usd
        return round(ccl, 4)

    def create_cedear_implicit_quote(
        self,
        ticker: str,
        cedear_price_ars: float,
        underlying_price_usd: float,
        conversion_ratio: Union[float, int, str],
        source: str = "IMPLICIT_CEDEAR",
    ) -> FXQuote:
        """
        Calculates implicit CCL and returns a validated, immutable FXQuote.
        """
        rate = self.calculate_implicit_ccl(cedear_price_ars, underlying_price_usd, conversion_ratio)
        quote = FXQuote(
            pair="USD_CCL/ARS",
            rate=rate,
            timestamp=datetime.now(timezone.utc),
            source=f"{source}:{ticker.upper()}",
        )
        self.register_quote(quote)
        return quote

    def convert(
        self,
        amount: float,
        from_currency: Union[Currency, str],
        to_currency: Union[Currency, str],
        fx_rate: Optional[float] = None,
    ) -> float:
        """
        Canonically converts an amount from one currency to another.
        Supports ARS, USD, USD_MEP, USD_CCL.
        """
        from_curr = Currency(from_currency) if isinstance(from_currency, str) else from_currency
        to_curr = Currency(to_currency) if isinstance(to_currency, str) else to_currency

        if from_curr == to_curr:
            return round(amount, 4)

        # 1. Converting from USD variants to ARS
        if from_curr in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP} and to_curr == Currency.ARS:
            pair = f"{from_curr.value}/ARS"
            rate = self.get_rate(pair, fallback_rate=fx_rate)
            return round(amount * rate, 4)

        # 2. Converting from ARS to USD variants
        if from_curr == Currency.ARS and to_curr in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP}:
            pair = f"{to_curr.value}/ARS"
            rate = self.get_rate(pair, fallback_rate=fx_rate)
            if rate <= 0:
                raise ValueError("El tipo de cambio de conversión debe ser mayor a cero.")
            return round(amount / rate, 4)

        # 3. Converting between USD variants (e.g. USD_MEP to USD_CCL)
        if from_curr in {Currency.USD, Currency.USD_CCL, Currency.USD_MEP} and to_curr in {
            Currency.USD,
            Currency.USD_CCL,
            Currency.USD_MEP,
        }:
            # Normalize via ARS
            rate_from = self.get_rate(f"{from_curr.value}/ARS")
            rate_to = self.get_rate(f"{to_curr.value}/ARS")
            amount_ars = amount * rate_from
            return round(amount_ars / rate_to, 4)

        raise ValueError(f"Conversión no soportada de {from_curr.value} a {to_curr.value}.")

    def convert_to_ars(
        self,
        amount: float,
        from_currency: Union[Currency, str],
        fx_rate: Optional[float] = None,
    ) -> float:
        """Convenience method to normalize an amount directly to ARS."""
        return self.convert(amount, from_currency=from_currency, to_currency=Currency.ARS, fx_rate=fx_rate)

    def convert_to_usd(
        self,
        amount: float,
        from_currency: Union[Currency, str],
        fx_rate: Optional[float] = None,
    ) -> float:
        """Convenience method to normalize an amount directly to USD."""
        return self.convert(amount, from_currency=from_currency, to_currency=Currency.USD, fx_rate=fx_rate)

    def convert_holding(
        self,
        quantity: float,
        price: float,
        from_currency: Union[Currency, str],
        to_currency: Union[Currency, str],
        fx_rate: Optional[float] = None,
    ) -> float:
        """
        Computes the market value of a holding (quantity * price) and converts it
        canonically to the target currency.
        """
        nominal_val = quantity * price
        return self.convert(nominal_val, from_currency=from_currency, to_currency=to_currency, fx_rate=fx_rate)
