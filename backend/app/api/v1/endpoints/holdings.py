from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_trader_or_admin
from app.models.holding import HoldingModel
from app.models.user import UserModel
from app.schemas.portfolio import AssetResponse, HoldingCreate, HoldingResponse
from app.services.portfolio_service import ensure_asset, get_user_portfolio_or_404

router = APIRouter()


@router.post("/{id}/holdings", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
async def add_or_update_holding(
    id: str,
    payload: HoldingCreate,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> HoldingResponse:
    """
    Adds a new holding or updates an existing position within the specified portfolio.
    Enforces RBAC (TRADER or ADMIN) and anti-IDOR/BOLA tenant isolation.
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)

    asset = await ensure_asset(
        db=db,
        ticker=payload.ticker,
        asset_type=payload.asset_type,
        currency=payload.currency,
        market=payload.market or "BYMA",
        sector=payload.sector or "OTHER",
    )

    # Check if position already exists in this portfolio
    stmt = (
        select(HoldingModel)
        .where(HoldingModel.portfolio_id == portfolio.id, HoldingModel.asset_ticker == asset.ticker)
    )
    result = await db.execute(stmt)
    holding = result.scalar_one_or_none()

    if holding:
        holding.quantity = payload.quantity
        holding.average_buy_price = payload.average_buy_price
        holding.current_price = payload.current_price
    else:
        holding = HoldingModel(
            portfolio_id=portfolio.id,
            asset_ticker=asset.ticker,
            quantity=payload.quantity,
            average_buy_price=payload.average_buy_price,
            current_price=payload.current_price,
        )
        db.add(holding)

    await db.flush()
    await db.refresh(holding)

    cost = holding.quantity * holding.average_buy_price
    mkt_val = holding.quantity * holding.current_price
    pnl = mkt_val - cost
    pnl_pct = round((pnl / cost) * 100.0, 2) if cost > 0 else 0.0

    return HoldingResponse(
        id=holding.id,
        portfolio_id=holding.portfolio_id,
        asset_ticker=holding.asset_ticker,
        quantity=holding.quantity,
        average_buy_price=holding.average_buy_price,
        current_price=holding.current_price,
        total_cost=round(cost, 2),
        market_value=round(mkt_val, 2),
        unrealized_pnl=round(pnl, 2),
        unrealized_pnl_pct=pnl_pct,
        asset=AssetResponse(
            ticker=asset.ticker,
            name=asset.name,
            asset_type=asset.asset_type,
            currency=asset.currency,
            sector=asset.sector,
            market=asset.market,
            cedear_ratio=asset.cedear_ratio,
            underlying_ticker=asset.underlying_ticker,
        ),
    )


@router.delete("/{id}/holdings/{holding_id}", status_code=status.HTTP_200_OK)
async def delete_holding(
    id: str,
    holding_id: int,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """
    Removes a holding from the portfolio.
    Enforces RBAC (TRADER or ADMIN) and anti-IDOR/BOLA tenant isolation.
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)

    stmt = select(HoldingModel).where(
        HoldingModel.id == holding_id,
        HoldingModel.portfolio_id == portfolio.id,
    )
    result = await db.execute(stmt)
    holding = result.scalar_one_or_none()

    if not holding:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Posición con id {holding_id} no encontrada en este portafolio.",
        )

    await db.delete(holding)
    return {
        "status": "deleted",
        "holding_id": holding_id,
        "portfolio_id": id,
        "message": "Posición eliminada exitosamente.",
    }
