"""
Controlador REST para gestión de órdenes de negociación y su ciclo de vida FSM (Módulo 5.3 - Fase 2).
Implementa autorización RBAC estricta (require_trader_or_admin para mutaciones,
get_current_active_user para consultas) y aislamiento anti-IDOR/BOLA sobre la cartera asociada.
"""
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    get_current_active_user,
    get_db_session,
    require_trader_or_admin,
)
from app.domain.models.fx import Currency
from app.domain.models.order import (
    InvalidOrderStateTransitionError,
    Order,
    OrderSide,
    OrderState,
    OrderType,
)
from app.models.portfolio import PortfolioModel
from app.models.rebalance_order import RebalanceOrderModel
from app.models.user import UserModel
from app.schemas.user import UserRole
from app.services.portfolio_service import get_user_portfolio_or_404

router = APIRouter()


class OrderCreateRequest(BaseModel):
    """Esquema de entrada para creación de una orden de compra/venta sobre una cartera."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    portfolio_id: str = Field(..., min_length=1, description="ID de la cartera propietaria")
    ticker: str = Field(..., min_length=1, max_length=30, description="Símbolo del activo")
    side: OrderSide = Field(..., description="Dirección de la orden: BUY o SELL")
    order_type: OrderType = Field(default=OrderType.MARKET, description="Tipo de orden: MARKET o LIMIT")
    quantity: float = Field(..., gt=0.0, description="Cantidad nominal a operar (> 0)")
    price: Optional[float] = Field(default=None, gt=0.0, description="Precio límite o estimado de ejecución")
    currency: Currency = Field(default=Currency.ARS, description="Moneda de liquidación")
    justification: Optional[str] = Field(default="Manual trade order", description="Motivo o justificación de la orden")


class OrderTransitionRequest(BaseModel):
    """Esquema de entrada para transición de estado en la FSM de una orden."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    new_state: OrderState = Field(..., description="Nuevo estado objetivo en la FSM")
    reason: Optional[str] = Field(default=None, description="Motivo de cancelación o rechazo")


class OrderResponseDTO(BaseModel):
    """Respuesta serializada de una orden persistida."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    portfolio_id: str
    ticker: str
    side: str
    estimated_shares: int
    price_used: float
    delta_amount: float
    status: str
    justification: str
    created_at: datetime


def _is_admin_user(user: UserModel) -> bool:
    role_val = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return role_val == UserRole.ADMIN.value


@router.get("", response_model=List[OrderResponseDTO], status_code=status.HTTP_200_OK)
async def list_orders(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    portfolio_id: Optional[str] = Query(default=None, description="Filtrar órdenes por ID de cartera"),
) -> List[OrderResponseDTO]:
    """
    Lista las órdenes asociadas a las carteras del usuario autenticado (o todas si es ADMIN).
    Si se especifica portfolio_id, verifica que la cartera pertenezca al usuario o que sea ADMIN.
    """
    if portfolio_id is not None:
        portfolio = await get_user_portfolio_or_404(portfolio_id, current_user, db)
        stmt = (
            select(RebalanceOrderModel)
            .where(RebalanceOrderModel.portfolio_id == portfolio.id)
            .order_by(RebalanceOrderModel.created_at.desc())
        )
    else:
        stmt = select(RebalanceOrderModel).join(
            PortfolioModel, RebalanceOrderModel.portfolio_id == PortfolioModel.id
        )
        if not _is_admin_user(current_user):
            stmt = stmt.where(PortfolioModel.user_id == str(current_user.id))
        stmt = stmt.order_by(RebalanceOrderModel.created_at.desc())

    result = await db.execute(stmt)
    orders = result.scalars().all()
    return [OrderResponseDTO.model_validate(o) for o in orders]


@router.post("", response_model=OrderResponseDTO, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreateRequest,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrderResponseDTO:
    """
    Crea y registra una nueva orden de mercado sobre una cartera existente.
    Exige rol TRADER o ADMIN y verifica propiedad estricta sobre portfolio_id (anti-IDOR/BOLA).
    """
    portfolio = await get_user_portfolio_or_404(payload.portfolio_id, current_user, db)

    try:
        domain_order = Order(
            portfolio_id=str(portfolio.id),
            ticker=payload.ticker,
            side=payload.side,
            order_type=payload.order_type,
            quantity=payload.quantity,
            price=payload.price,
            currency=payload.currency,
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        )

    exec_price = domain_order.price if domain_order.price is not None else 1.0
    shares = max(1, int(round(domain_order.quantity)))
    delta_amt = float(domain_order.quantity * exec_price)
    if domain_order.side == OrderSide.SELL:
        delta_amt = -abs(delta_amt)

    order_model = RebalanceOrderModel(
        id=domain_order.id,
        portfolio_id=str(portfolio.id),
        ticker=domain_order.ticker,
        side=domain_order.side.value,
        current_weight=0.0,
        target_weight=0.0,
        delta_amount=delta_amt,
        estimated_shares=shares,
        price_used=exec_price,
        status=domain_order.state.value,
        justification=payload.justification or "Manual trade order",
    )
    db.add(order_model)
    await db.flush()
    await db.refresh(order_model)

    return OrderResponseDTO.model_validate(order_model)


@router.get("/{order_id}", response_model=OrderResponseDTO, status_code=status.HTTP_200_OK)
async def get_order(
    order_id: str,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrderResponseDTO:
    """
    Recupera el detalle de una orden específica verificando que la cartera asociada
    pertenezca al usuario autenticado (o que sea ADMIN).
    """
    stmt = (
        select(RebalanceOrderModel)
        .where(RebalanceOrderModel.id == str(order_id))
        .options(selectinload(RebalanceOrderModel.portfolio))
    )
    result = await db.execute(stmt)
    order_model = result.scalar_one_or_none()

    if order_model is None or order_model.portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    if not _is_admin_user(current_user) and str(order_model.portfolio.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    return OrderResponseDTO.model_validate(order_model)


@router.patch("/{order_id}", response_model=OrderResponseDTO, status_code=status.HTTP_200_OK)
async def transition_order_state(
    order_id: str,
    payload: OrderTransitionRequest,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrderResponseDTO:
    """
    Ejecuta una transición de estado gobernada por la FSM de órdenes.
    Exige rol TRADER o ADMIN y valida propiedad de la cartera asociada.
    """
    stmt = (
        select(RebalanceOrderModel)
        .where(RebalanceOrderModel.id == str(order_id))
        .options(selectinload(RebalanceOrderModel.portfolio))
    )
    result = await db.execute(stmt)
    order_model = result.scalar_one_or_none()

    if order_model is None or order_model.portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    if not _is_admin_user(current_user) and str(order_model.portfolio.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    try:
        current_state = OrderState(order_model.status)
    except ValueError:
        current_state = OrderState.CREATED

    domain_order = Order(
        id=order_model.id,
        portfolio_id=order_model.portfolio_id,
        ticker=order_model.ticker,
        side=OrderSide(order_model.side),
        order_type=OrderType.MARKET,
        quantity=float(max(1, order_model.estimated_shares)),
        price=max(0.01, float(order_model.price_used)),
        state=current_state,
    )

    try:
        domain_order.transition_to(payload.new_state, reason=payload.reason)
    except InvalidOrderStateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    order_model.status = domain_order.state.value
    await db.flush()
    await db.refresh(order_model)

    return OrderResponseDTO.model_validate(order_model)

