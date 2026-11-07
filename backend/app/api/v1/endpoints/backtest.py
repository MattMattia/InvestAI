import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.domain.services.backtest_engine import BacktestEngine
from app.domain.services.market_simulation import generate_gbm_market_prices
from app.models.user import UserModel
from app.schemas.backtest import BacktestConfig, BacktestResult, BacktestRunRequest
from app.services.portfolio_service import get_user_portfolio_or_404

router = APIRouter()


@router.post(
    "/run",
    response_model=BacktestResult,
    status_code=status.HTTP_200_OK,
    summary="Ejecutar motor de backtesting histórico",
    description="Simula la evolución de cartera con rebalanceo periódico, optimización cuantitativa, FSM y fricciones.",
)
async def run_backtest_simulation(
    request: BacktestRunRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BacktestResult:
    """
    Ejecuta una simulación completa de backtesting histórico sobre el universo y parámetros dados.
    Exige usuario autenticado activo y valida aislamiento tenant si se suministra portfolio_id.
    """
    try:
        if request.portfolio_id is not None:
            await get_user_portfolio_or_404(request.portfolio_id, current_user, db)

        start_d = (
            dt.datetime.strptime(str(request.start_date)[:10], "%Y-%m-%d").date()
            if isinstance(request.start_date, str)
            else request.start_date
        )
        end_d = (
            dt.datetime.strptime(str(request.end_date)[:10], "%Y-%m-%d").date()
            if isinstance(request.end_date, str)
            else request.end_date
        )

        if start_d >= end_d:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La fecha de inicio ({start_d}) debe ser estrictamente anterior a la fecha de fin ({end_d}).",
            )

        # Utilizar precios personalizados o sintetizar trayectorias con GBM
        if request.custom_prices:
            prices_data = request.custom_prices
        else:
            prices_data = generate_gbm_market_prices(
                tickers=request.tickers,
                start_date=start_d,
                end_date=end_d,
            )

        # Instanciar configuración canónica y motor
        base_config = BacktestConfig(
            initial_capital=request.initial_capital,
            tickers=request.tickers,
            start_date=start_d,
            end_date=end_d,
            rebalance_frequency=request.rebalance_frequency,
            risk_free_rate=request.risk_free_rate,
            friction_config=request.friction_config,
            optimization_method=request.optimization_method,
        )

        engine = BacktestEngine(config=base_config)
        result = engine.run(prices_data=prices_data)
        return result

    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve),
        ) from ve
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante la simulación de backtesting: {str(exc)}",
        ) from exc
