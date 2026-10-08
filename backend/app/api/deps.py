from typing import AsyncGenerator, Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, ensure_db_ready
from app.models.user import UserModel
from app.domain.models.portfolio import InvestorProfile
from app.domain.services.market_history_service import MarketHistoryService
from app.infrastructure.market_data.http_connector import HttpMarketConnector
from app.infrastructure.market_data.quote_cache import InMemoryQuoteCache


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


async def get_current_user(
    db: AsyncSession = Depends(get_db_session),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> UserModel:
    """
    Dependency providing the current authenticated user context.
    For Stage 1, provides seamless deterministic mock authentication.
    Guarantees user persistence for relational foreign-key integrity.
    """
    user_id = x_user_id or "default_user_001"

    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        user = UserModel(
            id=user_id,
            email=f"{user_id}@investai.internal",
            hashed_password="mock_stage1_hashed_password",
            investor_profile=InvestorProfile.MODERATE.value,
        )
        db.add(user)
        await db.flush()

    return user


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
