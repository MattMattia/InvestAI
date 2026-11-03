from typing import Annotated, List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_trader_or_admin
from app.domain.rules.rebalancing import (
    RebalancePlan,
    TargetAllocation,
    ToleranceBandRebalancer,
)
from app.models.rebalance_order import RebalanceOrderModel
from app.models.user import UserModel
from app.schemas.risk import (
    RebalanceOrderResponse,
    RebalancePlanResponse,
    RebalanceRequest,
)
from app.services.portfolio_service import (
    get_user_portfolio_or_404,
    orm_to_domain_portfolio,
)

router = APIRouter()


@router.post("/{id}/rebalance", response_model=RebalancePlanResponse, status_code=status.HTTP_200_OK)
async def generate_portfolio_rebalance(
    id: str,
    payload: RebalanceRequest,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    dry_run: bool = Query(
        default=False,
        description="Si es True, simula el plan de rebalanceo sin persistir órdenes pendientes en la base de datos.",
    ),
) -> RebalancePlanResponse:
    """
    Executes the deterministic Tolerance-Band Rebalancer against target allocations.
    Generates actionable integer BUY/SELL orders only when asset weights breach
    the allowed tolerance band, ensuring cash liquidity conservation.
    Persists pending execution orders in the database unless dry_run=True.
    Enforces RBAC (TRADER or ADMIN) and anti-IDOR/BOLA tenant isolation.
    """
    portfolio_model = await get_user_portfolio_or_404(id, current_user, db)
    domain_portfolio = orm_to_domain_portfolio(portfolio_model, fx_ccl=payload.fx_ccl)

    domain_targets: List[TargetAllocation] = [
        TargetAllocation(
            ticker=t.ticker,
            target_weight=t.target_weight,
            tolerance_band=t.tolerance_band,
        )
        for t in payload.targets
    ]

    plan: RebalancePlan = ToleranceBandRebalancer.generate_plan(
        portfolio=domain_portfolio,
        targets=domain_targets,
        prices=payload.custom_prices,
        fx_ccl=payload.fx_ccl,
        include_hold=payload.include_hold,
    )

    if not dry_run:
        # Persist pending orders
        for order in plan.orders:
            order_model = RebalanceOrderModel(
                portfolio_id=portfolio_model.id,
                ticker=order.ticker,
                side=order.side.value,
                current_weight=order.current_weight,
                target_weight=order.target_weight,
                delta_amount=order.delta_amount,
                estimated_shares=order.estimated_shares,
                price_used=order.price_used,
                status="PENDING",
                justification=order.justification,
            )
            db.add(order_model)

        await db.flush()

    return RebalancePlanResponse(
        portfolio_id=portfolio_model.id,
        orders=[
            RebalanceOrderResponse(
                ticker=o.ticker,
                side=o.side.value,
                current_weight=o.current_weight,
                target_weight=o.target_weight,
                delta_weight=o.delta_weight,
                delta_amount=o.delta_amount,
                estimated_shares=o.estimated_shares,
                price_used=o.price_used,
                justification=o.justification,
            )
            for o in plan.orders
        ],
        total_buy_amount=plan.total_buy_amount,
        total_sell_amount=plan.total_sell_amount,
        net_cash_flow=plan.net_cash_flow,
        available_cash=plan.available_cash,
        is_liquidity_sufficient=plan.is_liquidity_sufficient,
        liquidity_warning=plan.liquidity_warning,
    )
