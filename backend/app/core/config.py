import asyncio
import logging
import socket
from typing import List, Optional, Union
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("investai.config")


def check_postgres_connection(
    user: str, password: str, server: str, port: int, db_name: str
) -> bool:
    """Probes if the configured PostgreSQL database is live and accessible."""
    try:
        with socket.create_connection((server, port), timeout=0.3):
            pass
    except (socket.timeout, OSError):
        return False

    try:
        import asyncpg

        async def _probe():
            conn = await asyncpg.connect(
                user=user,
                password=password,
                host=server,
                port=port,
                database=db_name,
                timeout=0.6,
            )
            await conn.close()
            return True

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(_probe())).result(timeout=1.0)
        else:
            return asyncio.run(_probe())
    except Exception:
        return False


class Settings(BaseSettings):
    """
    Application Settings loaded from environment variables (.env).
    Strictly validated using Pydantic v2 Settings.
    Features automatic fallback to local SQLite for zero-config local development.
    """
    # Environment & Project Details
    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "InvestAI Portfolio & Risk Platform"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change_this_to_a_secure_random_secret_in_production_32_chars_min"
    JWT_SECRET_KEY: SecretStr = SecretStr("investai-insecure-dev-secret-key-change-in-production-min-32-bytes-length-xyz")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Defensive Rate Limiting for Authentication Endpoints (Módulo 5.4 - Fase 2)
    RATE_LIMITING_ENABLED: bool = True
    AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX: int = 5
    AUTH_RATE_LIMIT_LOGIN_IP_MAX: int = 20
    AUTH_RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 60
    AUTH_RATE_LIMIT_REGISTER_MAX: int = 3
    AUTH_RATE_LIMIT_REGISTER_WINDOW_SECONDS: int = 300

    @field_validator("JWT_SECRET_KEY", mode="after")
    @classmethod
    def validate_jwt_secret_key(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if len(raw.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 bytes (256 bits)")
        return v

    @field_validator("REFRESH_TOKEN_EXPIRE_DAYS", mode="after")
    @classmethod
    def validate_refresh_token_expire_days(cls, v: int) -> int:
        if not (1 <= v <= 90):
            raise ValueError("REFRESH_TOKEN_EXPIRE_DAYS must be between 1 and 90")
        return v


    # PostgreSQL Database Connection
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "investai_db"

    # SQLite fallback for local development without Docker
    USE_SQLITE_FALLBACK: bool = True
    SQLITE_DB_PATH: str = "investai_dev.db"

    # Explicit override if desired
    DATABASE_URL: Optional[str] = None

    # CORS Origins
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "*",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Risk Engine Default Parameters (Deterministic Constraints)
    DEFAULT_MAX_ASSET_CONCENTRATION_PCT: float = 15.0
    DEFAULT_MAX_SECTOR_CONCENTRATION_PCT: float = 30.0
    DEFAULT_MIN_FIXED_INCOME_PCT: float = 20.0
    DEFAULT_REBALANCE_TOLERANCE_BAND_PCT: float = 5.0
    DEFAULT_MAX_ACCEPTABLE_DRAWDOWN_PCT: float = 15.0

    # Market Data Caching TTL in seconds
    MARKET_DATA_CACHE_TTL_SECONDS: int = 60
    MARKET_DATA_BASE_URL: str = "https://api.investai.market"

    @property
    def is_postgres_available(self) -> bool:
        if self.ENVIRONMENT == "production":
            return True
        return check_postgres_connection(
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
            self.POSTGRES_SERVER,
            self.POSTGRES_PORT,
            self.POSTGRES_DB,
        )

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        """
        Asynchronous database connection URI.
        Falls back automatically to local SQLite in development if PostgreSQL is unreachable.
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        if self.ENVIRONMENT == "production":
            return (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        if self.USE_SQLITE_FALLBACK and not self.is_postgres_available:
            return f"sqlite+aiosqlite:///./{self.SQLITE_DB_PATH}"
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URI(self) -> str:
        """
        Synchronous database connection URI for migrations and inspections.
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("+asyncpg", "").replace("+aiosqlite", "")
        if self.ENVIRONMENT == "production":
            return (
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        if self.USE_SQLITE_FALLBACK and not self.is_postgres_available:
            return f"sqlite:///./{self.SQLITE_DB_PATH}"
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
