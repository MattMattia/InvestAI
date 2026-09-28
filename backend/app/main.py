from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import async_engine, init_db


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

# CORS Middleware configuration - allows Vite frontend on port 5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Custom structured response for Pydantic validation errors."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error_type": "VALIDATION_ERROR",
            "message": "Error de validación en los datos de entrada.",
            "details": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Unhandled internal server errors."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_type": "INTERNAL_SERVER_ERROR",
            "message": "Se produjo un error interno en el servidor.",
            "detail": str(exc),
        },
    )


@app.get("/", tags=["Health"])
async def root() -> dict:
    """Root entrypoint providing service status and metadata."""
    return {
        "app": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "online",
        "database_uri": settings.ASYNC_DATABASE_URI.split("@")[-1] if "@" in settings.ASYNC_DATABASE_URI else settings.ASYNC_DATABASE_URI,
        "docs": "/docs",
        "api_v1": settings.API_V1_STR,
    }


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Health check endpoint for liveness and readiness probes."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENVIRONMENT,
    }


# Register Version 1 Routers
app.include_router(api_router, prefix=settings.API_V1_STR)
