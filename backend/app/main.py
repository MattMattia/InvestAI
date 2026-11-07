import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import get_db_session
from app.api.middleware.trace import RequestTraceMiddleware, get_current_request_id
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import async_engine, init_db
from app.core.metrics import MetricsMiddleware, default_metrics
from app.schemas.envelope import APIErrorResponse, ErrorDetail, ResponseMeta, SubErrorDetail

logger = logging.getLogger("investai.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    # Startup: ensure tables exist in target database (PostgreSQL or local SQLite)
    await init_db()
    yield
    # Shutdown: clean disposal of connection pool
    await async_engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description=(
        "InvestAI API — Plataforma de Gestión de Portafolios y Evaluación Determinista "
        "de Riesgo Financiero para Renta Fija y Renta Variable."
    ),
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Trace and latency measurement middleware (OBS-01)
app.add_middleware(RequestTraceMiddleware)

# Prometheus RED metrics middleware (Módulo 8.3)
app.add_middleware(MetricsMiddleware)

# Strict CORS configuration for authorized frontend origins (SEC-01)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Execution-Time-Ms"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Custom structured response conforming to APIErrorResponse for HTTP exceptions (ARQ-02, SEC-02, SEC-03)."""
    request_id = (
        get_current_request_id() or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    )
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error(
            f"HTTP {exc.status_code} internal error [req_id={request_id}] on {request.method} {request.url.path}: {exc.detail}"
        )
        error_code = "INTERNAL_SERVER_ERROR"
        safe_message = "An internal server error occurred."
    else:
        status_code_map = {
            status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_409_CONFLICT: "CONFLICT",
            status.HTTP_413_CONTENT_TOO_LARGE: "PAYLOAD_TOO_LARGE",
            status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMIT_EXCEEDED",
        }
        error_code = status_code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
        safe_message = str(exc.detail)

    error_payload = APIErrorResponse(
        success=False,
        error=ErrorDetail(
            code=error_code,
            message=safe_message,
            details=[],
        ),
        meta=ResponseMeta(request_id=request_id),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload.model_dump(mode="json"),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Custom structured response conforming to APIErrorResponse for Pydantic validation errors (ARQ-02)."""
    request_id = (
        get_current_request_id() or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    )
    sub_errors = [
        SubErrorDetail(
            field=".".join(str(loc) for loc in err.get("loc", [])) if err.get("loc") else None,
            issue=str(err.get("msg", "Validation error")),
        )
        for err in exc.errors()
    ]
    error_payload = APIErrorResponse(
        success=False,
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Error de validación en los datos de entrada.",
            details=sub_errors,
        ),
        meta=ResponseMeta(request_id=request_id),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_payload.model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Unhandled internal server errors with internal logging, sanitized client output and APIErrorResponse envelope (SEC-02, ARQ-02)."""
    request_id = (
        get_current_request_id() or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    )
    logger.exception(
        f"Unhandled server error [req_id={request_id}] on {request.method} {request.url.path}: {exc}"
    )
    error_payload = APIErrorResponse(
        success=False,
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An internal server error occurred.",
            details=[],
        ),
        meta=ResponseMeta(request_id=request_id),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_payload.model_dump(mode="json"),
    )


@app.get("/", tags=["Health"])
async def root() -> dict:
    """Root entrypoint providing sanitized service status and metadata (SEC-02)."""
    return {
        "app": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "online",
        "docs": "/docs",
        "api_v1": settings.API_V1_STR,
    }


@app.get("/health/liveness", tags=["Health"])
async def liveness_probe() -> dict:
    """Liveness probe to confirm that the event loop is active and responsive without I/O (OBS-02)."""
    return {"status": "alive"}


@app.get("/health/readiness", tags=["Health"])
async def readiness_probe(
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Readiness probe evaluating database dependency connectivity with strict timeout (OBS-02)."""
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=1.5)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ready",
                "database": {
                    "status": "up",
                    "latency_ms": latency_ms,
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "environment": settings.ENVIRONMENT,
            },
        )
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        logger.error(f"Readiness check failed after {latency_ms}ms: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": {
                    "status": "down",
                    "latency_ms": latency_ms,
                    "error": "Database connectivity check failed or timed out.",
                },
                "timestamp": datetime.now(UTC).isoformat(),
                "environment": settings.ENVIRONMENT,
            },
        )


@app.get("/health", tags=["Health"])
async def health_check(
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Health check endpoint preserving backward compatibility with readiness validation."""
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=1.5)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "healthy",
                "database": "connected",
                "latency_ms": latency_ms,
                "timestamp": datetime.now(UTC).isoformat(),
                "environment": settings.ENVIRONMENT,
            },
        )
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "timestamp": datetime.now(UTC).isoformat(),
                "environment": settings.ENVIRONMENT,
            },
        )


@app.get("/metrics", tags=["Observability"], include_in_schema=False)
async def prometheus_metrics(request: Request) -> Response:
    """
    Prometheus metrics endpoint exporting RED telemetry and scheduler counters.
    Protected by optional bearer scrape token if configured in settings (Módulo 8.3).
    """
    if settings.METRICS_SCRAPE_TOKEN:
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "X-Metrics-Token" in request.headers:
            token = request.headers["X-Metrics-Token"].strip()

        if token != settings.METRICS_SCRAPE_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing Prometheus scrape token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    payload, content_type = default_metrics.generate_metrics_payload()
    return Response(content=payload, media_type=content_type)


# Register Version 1 Routers
app.include_router(api_router, prefix=settings.API_V1_STR)
