from typing import AsyncGenerator, Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, ensure_db_ready
from app.models.user import UserModel
from app.domain.models.portfolio import InvestorProfile


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
