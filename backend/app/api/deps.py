"""
Módulo central de inyección de dependencias para la API de InvestAI.
Garantiza gestión de sesiones asíncronas de base de datos, extracción y validación
estricta de tokens OAuth2 Bearer, resolución de identidad de usuario y control de acceso RBAC.
"""

import uuid
from collections.abc import AsyncGenerator, Sequence
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, ensure_db_ready
from app.core.rate_limit import auth_rate_limiter
from app.core.security import (
    ExpiredTokenError,
    InvalidTokenError,
    decode_token,
)
from app.domain.services.market_history_service import MarketHistoryService
from app.infrastructure.market_data.http_connector import HttpMarketConnector
from app.infrastructure.market_data.quote_cache import InMemoryQuoteCache
from app.models.user import UserModel
from app.schemas.auth import LoginRequest
from app.schemas.token import TokenPayload, TokenType
from app.schemas.user import UserRole

# Instancia global en memoria con TTL de 30 segundos para cotizaciones en tiempo real
global_quote_cache = InMemoryQuoteCache(ttl_seconds=30.0)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an asynchronous database session."""
    await ensure_db_ready()
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Alias canónico de sesión de base de datos según contratos de seguridad y FastAPI
get_db = get_db_session


# Esquema OAuth2 oficial estricto para extracción de Bearer Tokens (RFC 6750)
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=True,
)


async def get_current_token_payload(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> TokenPayload:
    """
    Extrae, valida y decodifica criptográficamente el Access Token JWT de la cabecera Authorization.
    Mapea excepciones de seguridad a códigos HTTP 401 estructurados con cabeceras WWW-Authenticate.
    """
    try:
        return decode_token(token, expected_type=TokenType.ACCESS)
    except ExpiredTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={
                "WWW-Authenticate": (
                    'Bearer error="invalid_token", error_description="The token has expired"'
                )
            },
        ) from None
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None


async def get_current_user(
    payload: Annotated[TokenPayload, Depends(get_current_token_payload)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserModel:
    """
    Resuelve la entidad UserModel en la base de datos a partir del payload del Access Token verificado.
    Soporta coerción defensiva de ID tanto para UUID nativo como strings legados.
    Arroja estrictamente HTTP 401 si el usuario no existe en la tabla users.
    """
    try:
        user_id = uuid.UUID(payload.sub)
    except (ValueError, AttributeError):
        user_id = payload.sub

    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_active_user(
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> UserModel:
    """
    Verifica que la cuenta del usuario autenticado se encuentre activa.
    Deniega el acceso con HTTP 403 Forbidden si is_active es False.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user


class RoleChecker:
    """
    Verificador de control de acceso basado en roles (RBAC).
    Ejecución asíncrona dentro del event loop sin delegación a threadpool.
    """

    def __init__(self, allowed_roles: Sequence[UserRole] | set[UserRole]) -> None:
        self.allowed_roles = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    async def __call__(
        self,
        current_user: Annotated[UserModel, Depends(get_current_active_user)],
    ) -> UserModel:
        user_role_val = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role_val not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted. Insufficient permissions",
            )
        return current_user


# Alias declarativos de seguridad para control de acceso jerárquico
require_trader_or_admin = RoleChecker([UserRole.TRADER, UserRole.ADMIN])
require_admin = RoleChecker([UserRole.ADMIN])


def get_client_ip(request: Request) -> str:
    """Extrae de forma segura la dirección IP del cliente desde el objeto Request."""
    return request.client.host if request.client and request.client.host else "127.0.0.1"


async def check_login_rate_limit(request: Request, payload: LoginRequest) -> None:
    """
    Dependencia declarativa de Rate Limiting para el endpoint POST /api/v1/auth/login.
    Aplica doble cota en ventana deslizante:
    1. Cota global por IP (anti password-spraying).
    2. Cota específica por tupla IP+email (anti fuerza bruta dirigida).
    """
    if not settings.RATE_LIMITING_ENABLED:
        return

    client_ip = get_client_ip(request)

    # 1. Verificar cota global de IP (anti password-spraying)
    is_limited_ip, retry_after_ip, _ = auth_rate_limiter.is_rate_limited(
        f"login:ip:{client_ip}",
        settings.AUTH_RATE_LIMIT_LOGIN_IP_MAX,
        settings.AUTH_RATE_LIMIT_LOGIN_WINDOW_SECONDS,
    )
    if is_limited_ip:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts from this IP. Please try again later.",
            headers={
                "Retry-After": str(retry_after_ip),
                "X-RateLimit-Limit": str(settings.AUTH_RATE_LIMIT_LOGIN_IP_MAX),
                "X-RateLimit-Remaining": "0",
            },
        )

    # 2. Verificar cota de cuenta (anti fuerza bruta dirigida)
    is_limited_acc, retry_after_acc, _ = auth_rate_limiter.is_rate_limited(
        f"login:account:{client_ip}:{payload.email}",
        settings.AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX,
        settings.AUTH_RATE_LIMIT_LOGIN_WINDOW_SECONDS,
    )
    if is_limited_acc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts for this account. Please try again later.",
            headers={
                "Retry-After": str(retry_after_acc),
                "X-RateLimit-Limit": str(settings.AUTH_RATE_LIMIT_LOGIN_ACCOUNT_MAX),
                "X-RateLimit-Remaining": "0",
            },
        )


async def check_register_rate_limit(request: Request) -> None:
    """
    Dependencia declarativa de Rate Limiting para el endpoint POST /api/v1/auth/register.
    Previene creación masiva automatizada de cuentas desde una misma IP.
    """
    if not settings.RATE_LIMITING_ENABLED:
        return

    client_ip = get_client_ip(request)
    is_limited, retry_after, _ = auth_rate_limiter.is_rate_limited(
        f"register:ip:{client_ip}",
        settings.AUTH_RATE_LIMIT_REGISTER_MAX,
        settings.AUTH_RATE_LIMIT_REGISTER_WINDOW_SECONDS,
    )
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts from this IP. Please try again later.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(settings.AUTH_RATE_LIMIT_REGISTER_MAX),
                "X-RateLimit-Remaining": "0",
            },
        )


def get_market_service(
    db: AsyncSession = Depends(get_db_session),
) -> MarketHistoryService:
    """
    Proveedor de dependencias para el servicio unificado de datos de mercado.
    Instancia HttpMarketConnector con protección SSRF y el caché global en memoria.
    Permite sobreescritura limpia vía app.dependency_overrides durante testing.
    """
    base_url = getattr(settings, "MARKET_DATA_BASE_URL", "https://api.investai.market")
    dns_resolver = (lambda h: ["93.184.216.34"]) if "investai.market" in base_url else None
    connector = HttpMarketConnector(
        base_url=base_url,
        dns_resolver=dns_resolver,
    )
    return MarketHistoryService(
        connector=connector,
        session=db,
        cache=global_quote_cache,
    )


__all__ = [
    "global_quote_cache",
    "get_db_session",
    "get_db",
    "oauth2_scheme",
    "get_current_token_payload",
    "get_current_user",
    "get_current_active_user",
    "RoleChecker",
    "require_trader_or_admin",
    "require_admin",
    "get_client_ip",
    "check_login_rate_limit",
    "check_register_rate_limit",
    "get_market_service",
]
