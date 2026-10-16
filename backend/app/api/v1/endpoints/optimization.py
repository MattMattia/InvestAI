import math
from typing import Annotated, List, Optional, Tuple
import numpy as np
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
from app.domain.services.portfolio_optimizer import (
    calculate_diversification_ratio,
    calculate_portfolio_volatility,
    calculate_risk_contributions,
    minimum_variance_portfolio,
    risk_parity_portfolio,
)
from app.domain.services.quantitative_risk import (
    calculate_cvar,
    calculate_kurtosis,
    calculate_skewness,
    calculate_var,
    ledoit_wolf_covariance,
)
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.optimization import (
    OptimizationMethod,
    OptimizationRequest,
    OptimizationResult,
    TailRiskMetrics,
)
from app.services.portfolio_service import get_user_portfolio_or_404

router = APIRouter()


def _generate_synthetic_returns(
    tickers: List[str],
    asset_types: List[str],
    t_obs: int = 60,
    seed: int = 42,
) -> np.ndarray:
    """
    Generates realistic historical returns for assets when explicit market
    time-series are not provided. Incorporates realistic daily volatilities,
    market correlation factor, and moderate tail events.
    """
    n_assets = len(tickers)
    if n_assets == 0:
        return np.empty((t_obs, 0))

    rng = np.random.default_rng(seed=seed)

    # Daily volatilities based on asset class
    daily_vols = []
    for at in asset_types:
        at_upper = (at or "").upper()
        if at_upper in ["BONO", "ON", "LETRA", "FIXED_INCOME", "SOVEREIGN_BOND", "CORPORATE_BOND"]:
            annual_vol = 0.12
        elif at_upper in ["CEDEAR", "ACCION", "EQUITY"]:
            annual_vol = 0.28
        else:
            annual_vol = 0.22
        daily_vols.append(annual_vol / math.sqrt(252.0))

    daily_vols = np.array(daily_vols, dtype=np.float64)

    # Common systemic market factor (annual vol ~18%, daily ~1.13%)
    market_factor = rng.normal(0.0003, 0.0113, size=t_obs)

    # Introduce realistic financial tail shocks in 5% of periods
    shock_indices = rng.choice(t_obs, size=max(1, int(t_obs * 0.05)), replace=False)
    market_factor[shock_indices] -= rng.uniform(0.015, 0.035, size=len(shock_indices))

    # Idiosyncratic component
    idiosyncratic = rng.normal(0.0, 1.0, size=(t_obs, n_assets))

    returns = np.zeros((t_obs, n_assets), dtype=np.float64)
    for i in range(n_assets):
        v = daily_vols[i]
        # 50% systemic correlation + 50% asset-specific risk
        returns[:, i] = 0.5 * (v / 0.0113) * market_factor + 0.866 * v * idiosyncratic[:, i]

    return returns


def _prepare_quantitative_inputs(
    portfolio: PortfolioModel,
    request: Optional[OptimizationRequest],
) -> Tuple[List[str], np.ndarray, np.ndarray, np.ndarray]:
    """
    Prepares tickers, current portfolio weights, return series, and covariance matrix.
    Returns:
        (tickers, current_weights, returns_matrix, cov_matrix)
    """
    req = request or OptimizationRequest()

    # Collect valid holdings with positive quantities
    holdings = [h for h in portfolio.holdings if h.quantity > 0]

    # Filter by user-requested tickers if specified
    if req.tickers:
        requested_set = {t.strip().upper() for t in req.tickers}
        holdings = [h for h in holdings if h.asset_ticker.strip().upper() in requested_set]

    tickers = [h.asset_ticker.strip().upper() for h in holdings]
    n_assets = len(tickers)

    if n_assets == 0:
        return [], np.array([]), np.empty((0, 0)), np.empty((0, 0))

    # Current holding weights based on market value
    values = np.array([float(h.quantity * h.current_price) for h in holdings], dtype=np.float64)
    total_val = float(np.sum(values))
    if total_val > 0:
        current_weights = values / total_val
    else:
        current_weights = np.full(n_assets, 1.0 / n_assets, dtype=np.float64)

    # 1. Covariance matrix provided directly
    if req.covariance_matrix is not None:
        cov = np.asarray(req.covariance_matrix, dtype=np.float64)
        if cov.shape != (n_assets, n_assets):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Dimensiones de covariance_matrix {cov.shape} no coinciden con N={n_assets} activos.",
            )
        # Symmetrize
        cov = 0.5 * (cov + cov.T)
        if req.returns is not None:
            returns = np.asarray(req.returns, dtype=np.float64)
        else:
            returns = _generate_synthetic_returns(
                tickers=tickers,
                asset_types=[h.asset.asset_type if h.asset else "" for h in holdings],
            )
        return tickers, current_weights, returns, cov

    # 2. Returns matrix provided
    if req.returns is not None:
        returns = np.asarray(req.returns, dtype=np.float64)
        if returns.ndim != 2 or returns.shape[1] != n_assets:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Matriz de retornos debe tener forma (T, {n_assets}). Forma dada: {returns.shape}",
            )
        if req.use_ledoit_wolf:
            cov = ledoit_wolf_covariance(returns)
        else:
            cov = np.cov(returns, rowvar=False)
            cov = np.asarray(cov, dtype=np.float64)
            if cov.ndim == 0:
                cov = cov.reshape((1, 1))
        return tickers, current_weights, returns, cov

    # 3. Generate synthetic returns and compute covariance
    asset_types = [h.asset.asset_type if h.asset else "" for h in holdings]
    returns = _generate_synthetic_returns(tickers=tickers, asset_types=asset_types)

    if req.use_ledoit_wolf:
        cov = ledoit_wolf_covariance(returns)
    else:
        cov = np.cov(returns, rowvar=False)
        cov = np.asarray(cov, dtype=np.float64)
        if cov.ndim == 0:
            cov = cov.reshape((1, 1))

    return tickers, current_weights, returns, cov


def _compute_tail_metrics(
    portfolio_returns: np.ndarray,
    confidence_level: float = 0.95,
) -> TailRiskMetrics:
    """Calculates standardized tail risk metrics for a 1D portfolio return series."""
    return TailRiskMetrics(
        skewness=calculate_skewness(portfolio_returns),
        kurtosis=calculate_kurtosis(portfolio_returns),
        var_historical=calculate_var(portfolio_returns, alpha=confidence_level, method="historical"),
        var_parametric=calculate_var(portfolio_returns, alpha=confidence_level, method="parametric"),
        cvar_historical=calculate_cvar(portfolio_returns, alpha=confidence_level),
        confidence_level=confidence_level,
    )


@router.post(
    "/{id}/optimize/minimum-variance",
    response_model=OptimizationResult,
    status_code=status.HTTP_200_OK,
)
async def optimize_minimum_variance(
    id: str,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    request: Optional[OptimizationRequest] = Body(default=None),
) -> OptimizationResult:
    """
    Computes optimal asset allocation using the Global Minimum Variance (GMV) algorithm.
    Solves: min (1/2) * w^T * Sigma * w  subject to sum(w) = 1, w >= 0 (long-only).
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    req = request or OptimizationRequest()

    tickers, _, returns, cov = _prepare_quantitative_inputs(portfolio, req)

    # Edge cases: 0 or 1 holding
    if len(tickers) == 0:
        return OptimizationResult(
            portfolio_id=id,
            method=OptimizationMethod.MINIMUM_VARIANCE.value,
            weights={},
            expected_annual_volatility=0.0,
            risk_contributions={},
            diversification_ratio=1.0,
            tail_metrics=_compute_tail_metrics(np.array([0.0]), req.confidence_level),
        )

    if len(tickers) == 1:
        single_ticker = tickers[0]
        vol = float(math.sqrt(cov[0, 0]) * math.sqrt(252.0)) if cov.size > 0 else 0.0
        port_returns = returns[:, 0] if returns.shape[1] > 0 else np.array([0.0])
        return OptimizationResult(
            portfolio_id=id,
            method=OptimizationMethod.MINIMUM_VARIANCE.value,
            weights={single_ticker: 1.0},
            expected_annual_volatility=round(vol, 6),
            risk_contributions={single_ticker: 1.0},
            diversification_ratio=1.0,
            tail_metrics=_compute_tail_metrics(port_returns, req.confidence_level),
        )

    # Optimize Long-Only Minimum Variance
    opt_weights = minimum_variance_portfolio(cov)
    weights_dict = {ticker: float(opt_weights[i]) for i, ticker in enumerate(tickers)}

    exp_vol = calculate_portfolio_volatility(opt_weights, cov, annualized=True)
    risk_contribs = calculate_risk_contributions(opt_weights, cov)
    risk_contrib_dict = {ticker: float(risk_contribs[i]) for i, ticker in enumerate(tickers)}
    div_ratio = calculate_diversification_ratio(opt_weights, cov)

    port_returns = returns @ opt_weights
    tail_metrics = _compute_tail_metrics(port_returns, req.confidence_level)

    return OptimizationResult(
        portfolio_id=id,
        method=OptimizationMethod.MINIMUM_VARIANCE.value,
        weights=weights_dict,
        expected_annual_volatility=exp_vol,
        risk_contributions=risk_contrib_dict,
        diversification_ratio=div_ratio,
        tail_metrics=tail_metrics,
    )


@router.post(
    "/{id}/optimize/risk-parity",
    response_model=OptimizationResult,
    status_code=status.HTTP_200_OK,
)
async def optimize_risk_parity(
    id: str,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    request: Optional[OptimizationRequest] = Body(default=None),
) -> OptimizationResult:
    """
    Computes Equal Risk Contribution (Risk Parity) optimal portfolio weights.
    Equalizes marginal risk contribution across all assets: RC_i = sigma_p / N.
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    req = request or OptimizationRequest()

    tickers, _, returns, cov = _prepare_quantitative_inputs(portfolio, req)

    # Edge cases: 0 or 1 holding
    if len(tickers) == 0:
        return OptimizationResult(
            portfolio_id=id,
            method=OptimizationMethod.RISK_PARITY.value,
            weights={},
            expected_annual_volatility=0.0,
            risk_contributions={},
            diversification_ratio=1.0,
            tail_metrics=_compute_tail_metrics(np.array([0.0]), req.confidence_level),
        )

    if len(tickers) == 1:
        single_ticker = tickers[0]
        vol = float(math.sqrt(cov[0, 0]) * math.sqrt(252.0)) if cov.size > 0 else 0.0
        port_returns = returns[:, 0] if returns.shape[1] > 0 else np.array([0.0])
        return OptimizationResult(
            portfolio_id=id,
            method=OptimizationMethod.RISK_PARITY.value,
            weights={single_ticker: 1.0},
            expected_annual_volatility=round(vol, 6),
            risk_contributions={single_ticker: 1.0},
            diversification_ratio=1.0,
            tail_metrics=_compute_tail_metrics(port_returns, req.confidence_level),
        )

    # Optimize Risk Parity (Equal Risk Contribution)
    opt_weights = risk_parity_portfolio(cov)
    weights_dict = {ticker: float(opt_weights[i]) for i, ticker in enumerate(tickers)}

    exp_vol = calculate_portfolio_volatility(opt_weights, cov, annualized=True)
    risk_contribs = calculate_risk_contributions(opt_weights, cov)
    risk_contrib_dict = {ticker: float(risk_contribs[i]) for i, ticker in enumerate(tickers)}
    div_ratio = calculate_diversification_ratio(opt_weights, cov)

    port_returns = returns @ opt_weights
    tail_metrics = _compute_tail_metrics(port_returns, req.confidence_level)

    return OptimizationResult(
        portfolio_id=id,
        method=OptimizationMethod.RISK_PARITY.value,
        weights=weights_dict,
        expected_annual_volatility=exp_vol,
        risk_contributions=risk_contrib_dict,
        diversification_ratio=div_ratio,
        tail_metrics=tail_metrics,
    )


@router.post(
    "/{id}/tail-risk",
    response_model=TailRiskMetrics,
    status_code=status.HTTP_200_OK,
)
async def evaluate_tail_risk(
    id: str,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    request: Optional[OptimizationRequest] = Body(default=None),
) -> TailRiskMetrics:
    """
    Evaluates distribution moments (Skewness, Kurtosis) and tail losses
    (Historical VaR, Parametric VaR, CVaR / Expected Shortfall) for the
    current portfolio allocation.
    """
    portfolio = await get_user_portfolio_or_404(id, current_user, db)
    req = request or OptimizationRequest()

    tickers, current_weights, returns, _ = _prepare_quantitative_inputs(portfolio, req)

    if len(tickers) == 0:
        return _compute_tail_metrics(np.array([0.0]), req.confidence_level)

    port_returns = returns @ current_weights
    return _compute_tail_metrics(port_returns, req.confidence_level)
