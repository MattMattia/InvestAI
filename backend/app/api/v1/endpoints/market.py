"""
Controlador REST para Datos de Mercado e Ingesta en Vivo (Módulo 6 - Fase 4).
Implementa contratos estrictos con el Universal Envelope (APIResponse / APIErrorResponse),
validaciones defensivas de entrada (regex de tickers, consistencia cronológica, ratios positivos)
y endpoints de cotizaciones, series OHLCV históricas y tipos de cambio implícitos (MEP / CCL).
"""
from datetime import date
from decimal import Decimal
import re
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import get_market_service
from app.api.middleware.trace import get_current_request_id
from app.domain.services.fx_calculator import (
    FXCalculatorError,
    calculate_ccl_rate,
    calculate_mep_rate,
)
from app.domain.services.market_connector import (
    RateLimitExceededError,
    SecuritySSRFViolationError,
    TickerNotFoundError,
)
from app.domain.services.market_history_service import MarketHistoryService
from app.schemas.envelope import (
    APIErrorResponse,
    APIResponse,
    ErrorDetail,
    ResponseMeta,
    SubErrorDetail,
)
from app.schemas.market_data import (
    FXRateDTO,
    MarketBarDTO,
    MarketQuoteDTO,
    Timeframe,
)

router = APIRouter()

# Patrón regex canónico para símbolos / tickers financieros institucionales
TICKER_REGEX = re.compile(r"^[A-Z0-9.\-]+$")


def _build_meta() -> ResponseMeta:
    """Genera ResponseMeta con correlación de solicitud HTTP actual."""
    req_id = get_current_request_id() or str(uuid.uuid4())
    return ResponseMeta(request_id=req_id)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[List[SubErrorDetail]] = None,
) -> JSONResponse:
    """Construye una respuesta JSON estandarizada con APIErrorResponse."""
    payload = APIErrorResponse(
        success=False,
        error=ErrorDetail(
            code=code,
            message=message,
            details=details or [],
        ),
        meta=_build_meta(),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


@router.get(
    "/quote/{ticker}",
    response_model=APIResponse[MarketQuoteDTO],
    status_code=status.HTTP_200_OK,
    summary="Obtener cotización en tiempo real",
    description="Recupera la cotización atómica en vivo para el ticker especificado, utilizando caché en memoria.",
    responses={
        404: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
        429: {"model": APIErrorResponse},
    },
)
async def get_market_quote(
    ticker: str,
    market_service: MarketHistoryService = Depends(get_market_service),
):
    """
    Endpoint de cotización instantánea en vivo con validación estricta de ticker.
    """
    if not TICKER_REGEX.match(ticker):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_TICKER_FORMAT",
            message="Formato de ticker inválido. Solo se admiten caracteres alfanuméricos en mayúsculas, puntos y guiones.",
            details=[SubErrorDetail(field="ticker", issue=f"El valor '{ticker}' no cumple con el patrón ^[A-Z0-9.-]+$")],
        )

    try:
        quote = await market_service.get_quote_with_cache(ticker)
        return APIResponse[MarketQuoteDTO](data=quote, meta=_build_meta())
    except TickerNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TICKER_NOT_FOUND",
            message=f"El ticker '{ticker}' no fue encontrado en el proveedor de mercado.",
        )
    except RateLimitExceededError:
        return _error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMIT_EXCEEDED",
            message="Se ha superado el límite de tasa de solicitudes con el proveedor de mercado.",
        )
    except SecuritySSRFViolationError as exc:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            code="SECURITY_SSRF_VIOLATION",
            message=f"Acceso bloqueado por controles de seguridad anti-SSRF: {exc}",
        )


@router.get(
    "/history/{ticker}",
    response_model=APIResponse[List[MarketBarDTO]],
    status_code=status.HTTP_200_OK,
    summary="Consultar serie temporal histórica OHLCV",
    description="Retorna barras históricas con persistencia relacional, deduplicación e ingesta incremental delta.",
    responses={
        404: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
        429: {"model": APIErrorResponse},
    },
)
async def get_market_history(
    ticker: str,
    start_date: date = Query(..., description="Fecha inicial inclusiva (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Fecha final inclusiva (YYYY-MM-DD)"),
    timeframe: Timeframe = Query(default=Timeframe.D1, description="Granularidad temporal de las barras"),
    market_service: MarketHistoryService = Depends(get_market_service),
):
    """
    Endpoint para consulta e ingesta incremental de series temporales OHLCV.
    """
    if not TICKER_REGEX.match(ticker):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_TICKER_FORMAT",
            message="Formato de ticker inválido. Solo se admiten caracteres alfanuméricos en mayúsculas, puntos y guiones.",
            details=[SubErrorDetail(field="ticker", issue=f"El valor '{ticker}' no cumple con el patrón ^[A-Z0-9.-]+$")],
        )

    if start_date > end_date:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_DATE_RANGE",
            message=f"La fecha de inicio ({start_date}) debe ser anterior o igual a la fecha de fin ({end_date}).",
            details=[SubErrorDetail(field="start_date", issue=f"start_date ({start_date}) > end_date ({end_date})")],
        )

    try:
        bars = await market_service.get_or_fetch_bars(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
        )
        return APIResponse[List[MarketBarDTO]](data=bars, meta=_build_meta())
    except TickerNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TICKER_NOT_FOUND",
            message=f"El ticker '{ticker}' no fue encontrado en el proveedor de mercado.",
        )
    except RateLimitExceededError:
        return _error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMIT_EXCEEDED",
            message="Se ha superado el límite de tasa de solicitudes con el proveedor de mercado.",
        )
    except SecuritySSRFViolationError as exc:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            code="SECURITY_SSRF_VIOLATION",
            message=f"Acceso bloqueado por controles de seguridad anti-SSRF: {exc}",
        )


@router.get(
    "/fx/mep",
    response_model=APIResponse[FXRateDTO],
    status_code=status.HTTP_200_OK,
    summary="Calcular tipo de cambio implícito Dólar MEP",
    description="Determina el tipo de cambio financiero MEP en tiempo real a partir de cotizaciones en ARS y USD.",
    responses={
        404: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
    },
)
async def get_fx_mep(
    local_ticker: str = Query(default="AL30", description="Ticker del activo en moneda local (ARS)"),
    usd_ticker: str = Query(default="AL30D", description="Ticker del activo en dólares (USD)"),
    market_service: MarketHistoryService = Depends(get_market_service),
):
    """
    Endpoint para cotización y cálculo analítico de tipo de cambio MEP implícito.
    """
    for field_name, t in [("local_ticker", local_ticker), ("usd_ticker", usd_ticker)]:
        if not TICKER_REGEX.match(t):
            return _error_response(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_TICKER_FORMAT",
                message=f"Formato de ticker inválido en '{field_name}'. Solo se admiten caracteres alfanuméricos en mayúsculas, puntos y guiones.",
                details=[SubErrorDetail(field=field_name, issue=f"El valor '{t}' no cumple con el patrón ^[A-Z0-9.-]+$")],
            )

    try:
        local_quote = await market_service.get_quote_with_cache(local_ticker)
    except TickerNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TICKER_NOT_FOUND",
            message=f"El ticker local '{local_ticker}' no fue encontrado en el proveedor de mercado.",
        )

    try:
        usd_quote = await market_service.get_quote_with_cache(usd_ticker)
    except TickerNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TICKER_NOT_FOUND",
            message=f"El ticker en USD '{usd_ticker}' no fue encontrado en el proveedor de mercado.",
        )

    try:
        fx_dto = calculate_mep_rate(local_quote=local_quote, usd_quote=usd_quote)
        return APIResponse[FXRateDTO](data=fx_dto, meta=_build_meta())
    except FXCalculatorError as exc:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="FX_CALCULATION_ERROR",
            message=f"Error en el cómputo del tipo de cambio MEP: {exc}",
        )


@router.get(
    "/fx/ccl",
    response_model=APIResponse[FXRateDTO],
    status_code=status.HTTP_200_OK,
    summary="Calcular tipo de cambio implícito Dólar CCL",
    description="Determina el tipo de cambio financiero Contado con Liquidación en tiempo real a partir de activo local y ADR.",
    responses={
        404: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
    },
)
async def get_fx_ccl(
    local_ticker: str = Query(default="GGAL", description="Ticker del activo local (ej. GGAL)"),
    adr_ticker: str = Query(default="GGAL", description="Ticker del ADR de referencia exterior (ej. GGAL)"),
    conversion_ratio: Decimal = Query(default=Decimal("10"), description="Ratio de conversión ADR (estrictamente > 0)"),
    market_service: MarketHistoryService = Depends(get_market_service),
):
    """
    Endpoint para cotización y cálculo analítico de tipo de cambio CCL implícito.
    """
    for field_name, t in [("local_ticker", local_ticker), ("adr_ticker", adr_ticker)]:
        if not TICKER_REGEX.match(t):
            return _error_response(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_TICKER_FORMAT",
                message=f"Formato de ticker inválido en '{field_name}'. Solo se admiten caracteres alfanuméricos en mayúsculas, puntos y guiones.",
                details=[SubErrorDetail(field=field_name, issue=f"El valor '{t}' no cumple con el patrón ^[A-Z0-9.-]+$")],
            )

    if conversion_ratio <= Decimal("0"):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_CONVERSION_RATIO",
            message="El ratio de conversión debe ser estrictamente positivo (> 0).",
            details=[SubErrorDetail(field="conversion_ratio", issue="conversion_ratio must be > 0")],
        )

    try:
        local_quote = await market_service.get_quote_with_cache(local_ticker)
    except TickerNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TICKER_NOT_FOUND",
            message=f"El ticker local '{local_ticker}' no fue encontrado en el proveedor de mercado.",
        )

    try:
        adr_quote = await market_service.get_quote_with_cache(adr_ticker)
    except TickerNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TICKER_NOT_FOUND",
            message=f"El ticker del ADR '{adr_ticker}' no fue encontrado en el proveedor de mercado.",
        )

    try:
        fx_dto = calculate_ccl_rate(
            local_quote=local_quote,
            adr_quote=adr_quote,
            conversion_ratio=conversion_ratio,
        )
        return APIResponse[FXRateDTO](data=fx_dto, meta=_build_meta())
    except FXCalculatorError as exc:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="FX_CALCULATION_ERROR",
            message=f"Error en el cómputo del tipo de cambio CCL: {exc}",
        )

