from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    get_current_active_user,
    get_db_session,
    require_trader_or_admin,
)
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.portfolio import (
    PortfolioCreate,
    PortfolioListItemResponse,
    PortfolioResponse,
    PortfolioUpdate,
)
from app.schemas.user import UserRole
from app.services.portfolio_service import (
    build_portfolio_response,
    ensure_asset,
    get_user_portfolio_or_404,
)

router = APIRouter()


@router.get("", response_model=list[PortfolioListItemResponse])
async def list_portfolios(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[PortfolioListItemResponse]:
    """
    Retrieves investment portfolios belonging to the current authenticated user.
    Users with UserRole.ADMIN have cross-tenant visibility across all portfolios.
    """
    role_val = (
        current_user.role.value
        if isinstance(current_user.role, UserRole)
        else str(current_user.role)
    )
    stmt = select(PortfolioModel).options(
        selectinload(PortfolioModel.holdings).selectinload(HoldingModel.asset)
    )
    if role_val != UserRole.ADMIN.value:
        stmt = stmt.where(PortfolioModel.user_id == str(current_user.id))

    stmt = stmt.order_by(PortfolioModel.updated_at.desc())
    result = await db.execute(stmt)
    portfolios = result.scalars().all()

    items = []
    for p in portfolios:
        total_ars = p.cash_balance_ars + (p.cash_balance_usd * 1300.0)
        for h in p.holdings:
            mult = 1300.0 if (h.asset and h.asset.currency == "USD") else 1.0
            total_ars += h.quantity * h.current_price * mult

        items.append(
            PortfolioListItemResponse(
                id=str(p.id),
                user_id=str(p.user_id),
                name=p.name,
                investor_profile=getattr(p, "investor_profile", "MODERATE"),
                cash_balance_ars=p.cash_balance_ars,
                cash_balance_usd=p.cash_balance_usd,
                total_market_value_ars=round(total_ars, 2),
                holdings_count=len(p.holdings),
                updated_at=p.updated_at,
            )
        )
    return items


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    payload: PortfolioCreate,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PortfolioResponse:
    """
    Creates a new investment portfolio with optional initial holdings.
    Enforces RBAC (TRADER or ADMIN) and strictly binds user_id from the authenticated token.
    """
    new_portfolio = PortfolioModel(
        user_id=str(current_user.id),
        name=payload.name,
        investor_profile=payload.investor_profile.upper()
        if payload.investor_profile
        else "MODERATE",
        cash_balance_ars=payload.cash_balance_ars,
        cash_balance_usd=payload.cash_balance_usd,
    )
    db.add(new_portfolio)
    await db.flush()

    if payload.holdings:
        for item in payload.holdings:
            asset = await ensure_asset(
                db=db,
                ticker=item.ticker,
                asset_type=item.asset_type,
                currency=item.currency,
                market=item.market or "BYMA",
                sector=item.sector or "OTHER",
            )
            holding = HoldingModel(
                portfolio_id=new_portfolio.id,
                asset_ticker=asset.ticker,
                quantity=item.quantity,
                average_buy_price=item.average_buy_price,
                current_price=item.current_price,
            )
            db.add(holding)

        await db.flush()

    # Re-fetch with eager loaded relationships
    portfolio = await get_user_portfolio_or_404(new_portfolio.id, current_user, db)
    return build_portfolio_response(portfolio)


@router.get("/{id}", response_model=PortfolioResponse)
async def get_portfolio(
    id: str,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PortfolioResponse:
    """
    Retrieves full details, positions and market valuations of a specific portfolio.
    Enforces anti-IDOR/BOLA tenant isolation (returns 404 if owned by another user, unless ADMIN).
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    return build_portfolio_response(portfolio)


@router.patch("/{id}", response_model=PortfolioResponse)
@router.put("/{id}", response_model=PortfolioResponse)
async def update_portfolio(
    id: str,
    payload: PortfolioUpdate,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PortfolioResponse:
    """
    Updates portfolio metadata, investor profile or cash balances.
    Enforces RBAC (TRADER or ADMIN) and tenant ownership isolation.
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    if payload.name is not None:
        portfolio.name = payload.name
    if payload.investor_profile is not None:
        portfolio.investor_profile = payload.investor_profile.upper()
    if payload.cash_balance_ars is not None:
        portfolio.cash_balance_ars = payload.cash_balance_ars
    if payload.cash_balance_usd is not None:
        portfolio.cash_balance_usd = payload.cash_balance_usd

    await db.flush()
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    return build_portfolio_response(portfolio)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_portfolio(
    id: str,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """
    Deletes an investment portfolio and all associated holdings and audit snapshots.
    Enforces RBAC (TRADER or ADMIN) and tenant ownership isolation.
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    await db.delete(portfolio)
    return {
        "status": "deleted",
        "portfolio_id": id,
        "message": f"Portafolio '{portfolio.name}' eliminado exitosamente.",
    }
