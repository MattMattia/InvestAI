import math
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_trader_or_admin
from app.domain.models.asset import Currency
from app.domain.rules.rebalancing import (
    RebalancePlan,
    TargetAllocation,
    ToleranceBandRebalancer,
)
from app.domain.services.market_data_provider import (
    compute_10y_covariance_and_expected_returns,
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


def compute_10y_optimal_strategy_weights(
    tickers: list[str],
    strategy_code: str,
    investor_profile: str = "MODERATE",
) -> tuple[str, dict[str, float], list[dict[str, Any]]]:
    r"""
    Calcula las ponderaciones objetivo óptimas (W_target, suma = 100.0%) sobre la
    Matriz de Covarianza Empírica de 10 Años (\Sigma_{10Y}) y los indicadores
    fundamentales/renta fija de cada activo, diferenciando matemáticamente los perfiles:
    - CONSERVATIVE / MIN_VARIANCE: Minimización de Varianza Global + Calidad Defensiva / Renta Fija
    - MODERATE / RISK_PARITY: Paridad de Riesgo Convexa (Spinu) ponderada por Sharpe 10Y y ROE/TIR
    - AGGRESSIVE / MAX_SHARPE: Optimización Media-Varianza (Markowitz Max-Sharpe) + Crecimiento 10Y (CAGR + ROE)
    - EQUAL_WEIGHT: Equiponderación 1/N
    """
    n = len(tickers)
    if n == 0:
        return "EQUAL_WEIGHT", {}, []

    cov_10y, mu_vec, meta_list = compute_10y_covariance_and_expected_returns(tickers)
    if n == 1:
        return "SINGLE_ASSET", {tickers[0]: 100.0}, meta_list

    raw_strat = (strategy_code or "AUTO").strip().upper()
    if raw_strat == "AUTO":
        prof = (investor_profile or "MODERATE").strip().upper()
        if prof == "CONSERVATIVE":
            resolved = "CONSERVATIVE_MIN_VARIANCE"
        elif prof == "AGGRESSIVE":
            resolved = "AGGRESSIVE_MAX_SHARPE"
        else:
            resolved = "MODERATE_RISK_PARITY"
    elif raw_strat in ("CONSERVATIVE", "MIN_VARIANCE", "CONSERVATIVE_MIN_VARIANCE"):
        resolved = "CONSERVATIVE_MIN_VARIANCE"
    elif raw_strat in ("MODERATE", "RISK_PARITY", "MODERATE_RISK_PARITY"):
        resolved = "MODERATE_RISK_PARITY"
    elif raw_strat in ("AGGRESSIVE", "MAX_SHARPE", "AGGRESSIVE_MAX_SHARPE"):
        resolved = "AGGRESSIVE_MAX_SHARPE"
    else:
        resolved = "EQUAL_WEIGHT"

    if resolved == "EQUAL_WEIGHT":
        raw_w = np.ones(n, dtype=float) / float(n)

    elif resolved == "CONSERVATIVE_MIN_VARIANCE":
        inv_cov = np.linalg.pinv(cov_10y)
        ones = np.ones(n, dtype=float)
        mv_scores = inv_cov @ ones
        mv_scores = np.maximum(mv_scores, 0.05)

        defensive_scores = np.zeros(n, dtype=float)
        for i, m in enumerate(meta_list):
            sigma = max(0.10, float(m.get("volatility_annualized", 0.30)))
            mdd = max(0.10, float(m.get("max_drawdown", 0.35)))
            beta = max(0.30, float(m.get("beta_market", 1.0)))
            a_type = str(m.get("asset_type", "STOCK")).upper()
            type_bonus = 1.65 if a_type == "BOND" else (1.25 if beta < 0.95 else 0.75)
            defensive_scores[i] = (1.0 / (sigma * sigma)) * (1.0 / mdd) * (1.0 / beta) * type_bonus

        mv_norm = mv_scores / np.sum(mv_scores)
        def_norm = defensive_scores / np.sum(defensive_scores)
        raw_w = 0.55 * mv_norm + 0.45 * def_norm

    elif resolved == "MODERATE_RISK_PARITY":
        budgets = np.zeros(n, dtype=float)
        for i, m in enumerate(meta_list):
            sharpe = max(0.15, float(m.get("sharpe_ratio", 0.40)))
            mu_q = max(0.08, float(m.get("composite_quant_return", 0.14)))
            budgets[i] = math.sqrt(sharpe * mu_q)
        budgets = budgets / np.sum(budgets)

        x = 1.0 / np.sqrt(np.maximum(np.diag(cov_10y), 1e-4))
        for _ in range(80):
            marginal = cov_10y @ x
            marginal = np.maximum(marginal, 1e-6)
            x = 0.5 * x + 0.5 * (budgets / marginal)
        raw_w = x / np.sum(x)

    else:
        rf = 0.045
        excess_mu = np.maximum(mu_vec - rf, 0.02)
        inv_cov = np.linalg.pinv(cov_10y)
        tangency = inv_cov @ excess_mu
        tangency = np.maximum(tangency, 0.02)

        growth_scores = np.zeros(n, dtype=float)
        for i, m in enumerate(meta_list):
            cagr = max(0.05, float(m.get("cagr_annualized", 0.14)))
            sharpe = max(0.15, float(m.get("sharpe_ratio", 0.40)))
            roe = max(8.0, float(m.get("roe_pct") or 16.0)) / 100.0
            a_type = str(m.get("asset_type", "STOCK")).upper()
            growth_multiplier = 0.55 if a_type == "BOND" else 1.35
            growth_scores[i] = (
                (cagr**1.5) * sharpe * (1.0 + 0.6 * min(1.0, roe)) * growth_multiplier
            )

        tan_norm = tangency / np.sum(tangency)
        gro_norm = growth_scores / np.sum(growth_scores)
        raw_w = 0.50 * tan_norm + 0.50 * gro_norm

    min_floor = min(0.04, 0.5 / float(n))
    clipped = np.clip(raw_w, min_floor, 0.65)
    norm_w = (clipped / np.sum(clipped)) * 100.0
    rounded_w = [round(float(val), 2) for val in norm_w]
    diff = round(100.0 - sum(rounded_w), 2)
    max_idx = int(np.argmax(rounded_w))
    rounded_w[max_idx] = round(rounded_w[max_idx] + diff, 2)

    weights_map = {tickers[i]: rounded_w[i] for i in range(n)}
    return resolved, weights_map, meta_list


@router.post(
    "/{id}/rebalance", response_model=RebalancePlanResponse, status_code=status.HTTP_200_OK
)
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
    Executes the deterministic Tolerance-Band Rebalancer against target allocations
    or computes 10-year quantitative optimal target weights (Min-Variance, Risk Parity,
    Max-Sharpe, or Equal-Weight) when a strategy is specified.
    """
    portfolio_model = await get_user_portfolio_or_404(id, current_user, db)
    domain_portfolio = orm_to_domain_portfolio(portfolio_model, fx_ccl=payload.fx_ccl)

    holdings_tickers = [h.asset.ticker for h in domain_portfolio.holdings]
    _, _, meta_list = compute_10y_covariance_and_expected_returns(holdings_tickers)
    meta_by_ticker = {m["ticker"]: m for m in meta_list}

    use_quant_strategy = bool(payload.strategy) or payload.targets is None
    if not use_quant_strategy and payload.targets is not None and len(payload.targets) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Target allocations cannot be empty.",
        )

    if use_quant_strategy:
        strategy_used, weights_map, _ = compute_10y_optimal_strategy_weights(
            tickers=holdings_tickers,
            strategy_code=payload.strategy or "AUTO",
            investor_profile=getattr(portfolio_model, "investor_profile", None)
            or current_user.investor_profile
            or "MODERATE",
        )
        domain_targets: list[TargetAllocation] = [
            TargetAllocation(
                ticker=t_sym,
                target_weight=weights_map.get(
                    t_sym, round(100.0 / max(1, len(holdings_tickers)), 2)
                ),
                tolerance_band=payload.tolerance_band,
            )
            for t_sym in holdings_tickers
        ]
    else:
        strategy_used = "CUSTOM_TARGETS"
        domain_targets = [
            TargetAllocation(
                ticker=t.ticker,
                target_weight=t.target_weight,
                tolerance_band=t.tolerance_band
                if t.tolerance_band is not None
                else payload.tolerance_band,
            )
            for t in (payload.targets or [])
        ]

    if not domain_targets:
        return RebalancePlanResponse(
            portfolio_id=portfolio_model.id,
            strategy_used=strategy_used,
            asset_metrics=[],
            orders=[],
            total_buy_amount=0.0,
            total_sell_amount=0.0,
            net_cash_flow=0.0,
            available_cash=domain_portfolio.cash_balance_ars,
            is_liquidity_sufficient=True,
            liquidity_warning=None,
        )

    plan: RebalancePlan = ToleranceBandRebalancer.generate_plan(
        portfolio=domain_portfolio,
        targets=domain_targets,
        prices=payload.custom_prices,
        fx_ccl=payload.fx_ccl,
        include_hold=payload.include_hold,
    )

    target_map = {t.ticker: float(t.target_weight) for t in domain_targets}
    total_val_ars = 0.0
    holding_vals_ars: dict[str, float] = {}
    for h in domain_portfolio.holdings:
        t_sym = h.asset.ticker
        px = (payload.custom_prices or {}).get(t_sym, h.current_price)
        val = h.quantity * px
        if h.currency == Currency.USD:
            val *= payload.fx_ccl
        holding_vals_ars[t_sym] = val
        total_val_ars += val

    enriched_metrics: list[dict[str, Any]] = []
    for h in domain_portfolio.holdings:
        t_sym = h.asset.ticker
        m_info = dict(meta_by_ticker.get(t_sym) or {})
        curr_w = (
            round((holding_vals_ars.get(t_sym, 0.0) / total_val_ars) * 100.0, 2)
            if total_val_ars > 0
            else 0.0
        )
        m_info["current_weight"] = curr_w
        m_info["target_weight"] = round(target_map.get(t_sym, curr_w), 2)
        enriched_metrics.append(m_info)

    if not dry_run:
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
                justification=f"[{strategy_used}] {order.justification}"
                if use_quant_strategy
                else order.justification,
            )
            db.add(order_model)

        await db.flush()

    return RebalancePlanResponse(
        portfolio_id=portfolio_model.id,
        strategy_used=strategy_used,
        asset_metrics=enriched_metrics,
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
                justification=f"[{strategy_used}] {o.justification}"
                if use_quant_strategy
                else o.justification,
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
