"""
Controlador REST para Datos de Mercado e Ingesta en Vivo (Módulo 6 - Fase 4).
Implementa contratos estrictos con el Universal Envelope (APIResponse / APIErrorResponse),
validaciones defensivas de entrada (regex de tickers, consistencia cronológica, ratios positivos)
y endpoints de cotizaciones, series OHLCV históricas y tipos de cambio implícitos (MEP / CCL).
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_market_service
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
from app.domain.services.market_data_provider import (
    CALIBRATED_10Y_METRICS_CATALOG,
    PublicMarket10YProvider,
)
from app.domain.services.market_history_service import MarketHistoryService
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.schemas.envelope import (
    APIErrorResponse,
    APIResponse,
    ErrorDetail,
    ResponseMeta,
    SubErrorDetail,
)
from app.schemas.market_data import (
    AssetFundamentalQuantMetricsDTO,
    FXRateDTO,
    MarketBarDTO,
    MarketQuoteDTO,
    MarketSyncMetricsResponseDTO,
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
    "/live-quotes",
    response_model=APIResponse[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="Obtener cotizaciones en vivo del universo BYMA con sincronización MTM de portafolios",
    description="Descarga cotizaciones multi-fuente en tiempo real (Yahoo Finance .BA, Google Finance :BCBA y DolarApi) y actualiza automáticamente current_price en activos y tenencias de la BD.",
)
async def get_live_market_quotes(
    category: Optional[str] = Query(default=None, description="Filtro opcional: ALL | STOCK | CEDEAR | BOND"),
    refresh: bool = Query(default=False, description="Forzar actualización en vivo sin usar la caché TTL"),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para cotizaciones de mercado en tiempo real multi-fuente y sincronización MTM.
    """
    batch = await PublicMarket10YProvider.fetch_live_quotes_batch(force_refresh=refresh)
    quotes_list: List[Dict[str, Any]] = batch.get("quotes", [])

    # Sincronización Automática con Base de Datos (Mark-To-Market)
    for q in quotes_list:
        t = q["ticker"]
        p_dec = Decimal(str(q["last_price"]))
        # 1. Actualizar Holdings de todos los portafolios que posean este ticker
        await db.execute(
            update(HoldingModel)
            .where(HoldingModel.asset_ticker == t)
            .values(current_price=p_dec)
        )
        # 2. Actualizar AssetModel si existe en la base de datos
        res = await db.execute(select(AssetModel).where(AssetModel.ticker == t))
        asset = res.scalar_one_or_none()
        if asset:
            payload = dict(asset.metrics_payload or {})
            payload["reference_price"] = q["last_price"]
            payload["current_price"] = q["last_price"]
            payload["change_pct"] = q["change_pct"]
            payload["change_nominal"] = q["change_nominal"]
            payload["updated_at"] = q["updated_at"]
            payload["data_source"] = q["data_source"]
            asset.metrics_payload = payload
            asset.metrics_updated_at = datetime.now(timezone.utc)

    await db.commit()

    # Filtrar por categoría si se especifica
    filtered_quotes = quotes_list
    if category and category.strip().upper() not in ("ALL", ""):
        cat_upper = category.strip().upper()
        if cat_upper in ("STOCK", "ACCIONES"):
            filtered_quotes = [q for q in quotes_list if q.get("asset_type") == "STOCK"]
        elif cat_upper == "CEDEAR":
            filtered_quotes = [q for q in quotes_list if q.get("asset_type") == "CEDEAR"]
        elif cat_upper in ("BOND", "BONOS"):
            filtered_quotes = [q for q in quotes_list if q.get("asset_type") == "BOND"]

    response_data = {
        "quotes": filtered_quotes,
        "ccl_rate": batch.get("ccl_rate", 1668.0),
        "mep_rate": batch.get("mep_rate", 1581.0),
        "data_source": batch.get("data_source", "YAHOO_LIVE"),
        "updated_at": batch.get("updated_at"),
    }
    return APIResponse[Dict[str, Any]](data=response_data, meta=_build_meta())


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
    response_model=APIResponse[List[Any]],
    status_code=status.HTTP_200_OK,
    summary="Consultar serie temporal histórica OHLCV",
    description="Retorna barras históricas con persistencia relacional o descarga en vivo multi-timeframe de Yahoo Finance v8.",
    responses={
        404: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
        429: {"model": APIErrorResponse},
    },
)
async def get_market_history(
    ticker: str,
    timeframe: str = Query(default="1M", description="Granularidad temporal: 1D | 1W | 1M | 1Y o D1"),
    start_date: Optional[date] = Query(default=None, description="Fecha inicial inclusiva opcional (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(default=None, description="Fecha final inclusiva opcional (YYYY-MM-DD)"),
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

    if start_date is not None and end_date is not None:
        if start_date > end_date:
            return _error_response(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_DATE_RANGE",
                message=f"La fecha de inicio ({start_date}) debe ser anterior o igual a la fecha de fin ({end_date}).",
                details=[SubErrorDetail(field="start_date", issue=f"start_date ({start_date}) > end_date ({end_date})")],
            )

        try:
            tf_enum = Timeframe(timeframe) if timeframe in [t.value for t in Timeframe] else Timeframe.D1
            bars = await market_service.get_or_fetch_bars(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                timeframe=tf_enum,
            )
            return APIResponse[List[Any]](data=bars, meta=_build_meta())
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
    else:
        # Modo multi-timeframe en tiempo real para gráficos interactivos (1D, 1W, 1M, 1Y)
        tf_str = timeframe.upper() if isinstance(timeframe, str) else "1M"
        bars_raw = await PublicMarket10YProvider.fetch_live_historical_bars(ticker, timeframe=tf_str)
        return APIResponse[List[Any]](data=bars_raw, meta=_build_meta())


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


async def _upsert_asset_metrics_in_db(
    db: AsyncSession,
    meta: dict,
) -> AssetModel:
    """Persiste o actualiza un AssetModel con sus métricas cuantitativas de 10 años y fundamentales."""
    ticker = meta["ticker"]
    result = await db.execute(select(AssetModel).where(AssetModel.ticker == ticker))
    asset = result.scalar_one_or_none()
    now_utc = datetime.now(timezone.utc)

    if asset is None:
        asset = AssetModel(
            ticker=ticker,
            name=meta.get("name", ticker),
            asset_type=meta.get("asset_type", "STOCK"),
            currency=meta.get("currency", "ARS"),
            sector=meta.get("sector", "OTHER"),
            market="BYMA",
            cedear_ratio=meta.get("cedear_ratio"),
            underlying_ticker=meta.get("underlying_ticker"),
        )
        db.add(asset)

    asset.history_start_date = meta.get("history_start_date", "2016-11-01")
    asset.history_years_available = float(meta.get("history_years_available", 10.0))
    asset.data_points_count = int(meta.get("data_points_count", 2520))
    asset.cagr_annualized = float(meta.get("cagr_annualized", 0.12))
    asset.volatility_annualized = float(meta.get("volatility_annualized", 0.25))
    asset.sharpe_ratio = float(meta.get("sharpe_ratio", 0.48))
    asset.sortino_ratio = float(meta.get("sortino_ratio", 0.68))
    asset.max_drawdown = float(meta.get("max_drawdown", 0.28))
    asset.beta_market = float(meta.get("beta_market", 1.0))
    asset.var_95_daily = float(meta.get("var_95_daily", 0.026))
    asset.pe_ratio = meta.get("pe_ratio")
    asset.pb_ratio = meta.get("pb_ratio")
    asset.roe_pct = meta.get("roe_pct")
    asset.debt_to_equity = meta.get("debt_to_equity")
    asset.dividend_yield_pct = meta.get("dividend_yield_pct")
    asset.market_cap_usd = meta.get("market_cap_usd")
    asset.ytm_tir_pct = meta.get("ytm_tir_pct")
    asset.modified_duration = meta.get("modified_duration")
    asset.parity_pct = meta.get("parity_pct")
    asset.metrics_payload = meta
    asset.metrics_updated_at = now_utc
    return asset


@router.get(
    "/metrics/{ticker}",
    response_model=APIResponse[AssetFundamentalQuantMetricsDTO],
    status_code=status.HTTP_200_OK,
    summary="Obtener métricas cuantitativas de 10 años y fundamentales de un activo",
    description=(
        "Retorna y persiste las métricas históricas de hasta 10 años (o máxima antigüedad "
        "desde su emisión) e indicadores fundamentales / renta fija en tiempo real."
    ),
)
async def get_asset_10y_metrics(
    ticker: str,
    live: bool = Query(default=False, description="Intentar enriquecimiento desde Yahoo Finance v8 en vivo"),
    db: AsyncSession = Depends(get_db),
):
    normalized = ticker.strip().upper()
    if not TICKER_REGEX.match(normalized):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_TICKER_FORMAT",
            message="Formato de ticker inválido.",
            details=[SubErrorDetail(field="ticker", issue=f"Valor inválido: '{ticker}'")],
        )

    meta = await PublicMarket10YProvider.fetch_live_or_calibrated_metrics(
        normalized,
        attempt_network=live,
    )
    await _upsert_asset_metrics_in_db(db, meta)
    await db.commit()

    dto = AssetFundamentalQuantMetricsDTO(**meta)
    return APIResponse[AssetFundamentalQuantMetricsDTO](data=dto, meta=_build_meta())


@router.post(
    "/sync-metrics",
    response_model=APIResponse[MarketSyncMetricsResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="Sincronizar y persistir métricas cuantitativas 10Y y fundamentales en la Base de Datos",
    description="Actualiza todos los activos del catálogo institucional BYMA y la tabla assets con métricas de 10 años.",
)
async def sync_all_market_metrics(
    live: bool = Query(default=False, description="Intentar conexión a Yahoo Finance v8 en vivo"),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(AssetModel.ticker))
    existing_tickers = {row[0] for row in res.all() if row[0]}
    all_tickers = sorted(existing_tickers.union(set(CALIBRATED_10Y_METRICS_CATALOG.keys())))

    dtos: List[AssetFundamentalQuantMetricsDTO] = []
    for t in all_tickers:
        meta = await PublicMarket10YProvider.fetch_live_or_calibrated_metrics(t, attempt_network=live)
        await _upsert_asset_metrics_in_db(db, meta)
        dtos.append(AssetFundamentalQuantMetricsDTO(**meta))

    await db.commit()
    response_dto = MarketSyncMetricsResponseDTO(
        synced_count=len(dtos),
        tickers=all_tickers,
        metrics=dtos,
    )
    return APIResponse[MarketSyncMetricsResponseDTO](data=response_dto, meta=_build_meta())


