"""
Calculadora cuantitativa y determinista de tipos de cambio financieros implícitos (MEP y CCL).
Implementa precisión monetaria estricta vía Decimal y programación defensiva frente a anomalías de mercado.
"""
from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP
from typing import Union

from app.schemas.market_data import FXRateDTO, FXType, MarketQuoteDTO


class FXCalculatorError(ValueError):
    """Excepción base para fallos numéricos o de consistencia en el cálculo de FX implícito."""
    pass


class InvalidMarketPriceError(FXCalculatorError):
    """Lanzada cuando un precio de mercado o ratio es nulo, negativo o inconsistente."""
    pass


class ZeroPriceDivisionError(FXCalculatorError):
    """Lanzada ante un intento de división por cero en las cotizaciones divisorias."""
    pass


def calculate_mep_rate(
    local_quote: MarketQuoteDTO,
    usd_quote: MarketQuoteDTO,
) -> FXRateDTO:
    """
    Calcula el tipo de cambio implícito Dólar MEP (Bolsa) a partir de una cotización en ARS
    y su contraparte en USD (ej. AL30 en ARS vs AL30D en USD).

    Fórmula:
    --------
    rate = (local_quote.price / usd_quote.price).quantize(0.0001, ROUND_HALF_UP)

    Si ambas cotizaciones poseen puntas estrictamente positivas (bid > 0, ask > 0):
    mep_bid = local_quote.bid / usd_quote.ask (venta de dólares)
    mep_ask = local_quote.ask / usd_quote.bid (compra de dólares)
    spread_pct = (((mep_ask - mep_bid) / rate) * 100).quantize(0.01, ROUND_HALF_UP)
    """
    if local_quote.price <= Decimal("0"):
        raise InvalidMarketPriceError(
            f"El precio local ({local_quote.ticker}={local_quote.price}) debe ser estrictamente positivo."
        )

    if usd_quote.price == Decimal("0"):
        raise ZeroPriceDivisionError(
            f"La cotización en USD ({usd_quote.ticker}={usd_quote.price}) no puede ser cero."
        )

    if usd_quote.price < Decimal("0"):
        raise InvalidMarketPriceError(
            f"La cotización en USD ({usd_quote.ticker}={usd_quote.price}) no puede ser negativa."
        )

    try:
        raw_rate = local_quote.price / usd_quote.price
        rate = raw_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except DivisionByZero as e:
        raise ZeroPriceDivisionError("División por cero al calcular tipo de cambio MEP.") from e
    except (InvalidOperation, Exception) as e:
        raise InvalidMarketPriceError(f"Operación inválida al calcular MEP: {e}") from e

    # Microestructura del Spread Bid-Ask Cruzado
    spread_pct = None
    if (
        local_quote.bid is not None
        and local_quote.bid > Decimal("0")
        and local_quote.ask is not None
        and local_quote.ask > Decimal("0")
        and usd_quote.bid is not None
        and usd_quote.bid > Decimal("0")
        and usd_quote.ask is not None
        and usd_quote.ask > Decimal("0")
    ):
        try:
            mep_bid = local_quote.bid / usd_quote.ask
            mep_ask = local_quote.ask / usd_quote.bid
            if rate > Decimal("0"):
                raw_spread = ((mep_ask - mep_bid) / rate) * Decimal("100")
                spread_pct = raw_spread.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                spread_pct = None
        except Exception:
            spread_pct = None

    timestamp = max(local_quote.timestamp, usd_quote.timestamp)

    return FXRateDTO(
        fx_type=FXType.MEP,
        rate=rate,
        base_ticker=local_quote.ticker,
        quote_ticker=usd_quote.ticker,
        spread_pct=spread_pct,
        timestamp=timestamp,
    )


def calculate_ccl_rate(
    local_quote: MarketQuoteDTO,
    adr_quote: MarketQuoteDTO,
    conversion_ratio: Union[Decimal, float, int, str],
) -> FXRateDTO:
    """
    Calcula el tipo de cambio implícito Contado con Liquidación (CCL) a partir de un activo
    local (acción o CEDEAR) y su correspondiente ADR en moneda extranjera, considerando el ratio de conversión.

    Fórmula:
    --------
    rate = ((local_quote.price * conversion_ratio) / adr_quote.price).quantize(0.0001, ROUND_HALF_UP)

    Si ambas cotizaciones poseen puntas estrictamente positivas (bid > 0, ask > 0):
    ccl_bid = (local_quote.bid * conversion_ratio) / adr_quote.ask
    ccl_ask = (local_quote.ask * conversion_ratio) / adr_quote.bid
    spread_pct = (((ccl_ask - ccl_bid) / rate) * 100).quantize(0.01, ROUND_HALF_UP)
    """
    if not isinstance(conversion_ratio, Decimal):
        try:
            conversion_ratio = Decimal(str(conversion_ratio))
        except Exception as e:
            raise InvalidMarketPriceError(f"Ratio de conversión inválido: {e}") from e

    if conversion_ratio <= Decimal("0"):
        raise InvalidMarketPriceError(
            f"El ratio de conversión ({conversion_ratio}) debe ser estrictamente positivo (> 0)."
        )

    if local_quote.price <= Decimal("0"):
        raise InvalidMarketPriceError(
            f"El precio local ({local_quote.ticker}={local_quote.price}) debe ser estrictamente positivo."
        )

    if adr_quote.price == Decimal("0"):
        raise ZeroPriceDivisionError(
            f"La cotización del ADR ({adr_quote.ticker}={adr_quote.price}) no puede ser cero."
        )

    if adr_quote.price < Decimal("0"):
        raise InvalidMarketPriceError(
            f"La cotización del ADR ({adr_quote.ticker}={adr_quote.price}) no puede ser negativa."
        )

    try:
        raw_rate = (local_quote.price * conversion_ratio) / adr_quote.price
        rate = raw_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except DivisionByZero as e:
        raise ZeroPriceDivisionError("División por cero al calcular tipo de cambio CCL.") from e
    except (InvalidOperation, Exception) as e:
        raise InvalidMarketPriceError(f"Operación inválida al calcular CCL: {e}") from e

    # Microestructura del Spread Bid-Ask Cruzado
    spread_pct = None
    if (
        local_quote.bid is not None
        and local_quote.bid > Decimal("0")
        and local_quote.ask is not None
        and local_quote.ask > Decimal("0")
        and adr_quote.bid is not None
        and adr_quote.bid > Decimal("0")
        and adr_quote.ask is not None
        and adr_quote.ask > Decimal("0")
    ):
        try:
            ccl_bid = (local_quote.bid * conversion_ratio) / adr_quote.ask
            ccl_ask = (local_quote.ask * conversion_ratio) / adr_quote.bid
            if rate > Decimal("0"):
                raw_spread = ((ccl_ask - ccl_bid) / rate) * Decimal("100")
                spread_pct = raw_spread.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                spread_pct = None
        except Exception:
            spread_pct = None

    timestamp = max(local_quote.timestamp, adr_quote.timestamp)

    return FXRateDTO(
        fx_type=FXType.CCL,
        rate=rate,
        base_ticker=local_quote.ticker,
        quote_ticker=adr_quote.ticker,
        spread_pct=spread_pct,
        timestamp=timestamp,
    )
