"""Pydantic Schemas / DTOs Package"""

from typing import TYPE_CHECKING

from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
)
from app.schemas.envelope import (
    APIErrorResponse,
    APIResponse,
    BaseSchema,
    ErrorDetail,
    ResponseMeta,
    SubErrorDetail,
)
from app.schemas.market_data import (
    FXRateDTO,
    FXType,
    MarketBarDTO,
    MarketQuoteDTO,
    Timeframe,
)
from app.schemas.token import (
    RefreshTokenRequest,
    TokenPayload,
    TokenResponse,
    TokenType,
)
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserResponse,
    UserRole,
)

if TYPE_CHECKING:
    from app.schemas.ingestion import IngestionReportSummary

__all__ = [
    "BaseSchema",
    "ResponseMeta",
    "APIResponse",
    "SubErrorDetail",
    "ErrorDetail",
    "APIErrorResponse",
    "IngestionReportSummary",
    "Timeframe",
    "FXType",
    "MarketQuoteDTO",
    "MarketBarDTO",
    "FXRateDTO",
    "UserRole",
    "UserBase",
    "UserCreate",
    "UserResponse",
    "TokenType",
    "TokenPayload",
    "TokenResponse",
    "RefreshTokenRequest",
    "RegisterRequest",
    "LoginRequest",
]


def __getattr__(name: str):
    if name == "IngestionReportSummary":
        from app.schemas.ingestion import IngestionReportSummary

        return IngestionReportSummary
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
