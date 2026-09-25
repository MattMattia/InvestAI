from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.asset import Asset, AssetType, Currency, Sector
from app.domain.models.portfolio import Holding, InvestorProfile, Portfolio
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.schemas.portfolio import AssetResponse, HoldingResponse, PortfolioResponse


async def get_user_portfolio_or_404(
    portfolio_id: str,
    user_id: str,
    db: AsyncSession,
) -> PortfolioModel:
    """Fetches a portfolio belonging to the user with eager-loaded holdings and assets."""
    stmt = (
        select(PortfolioModel)
        .where(PortfolioModel.id == portfolio_id, PortfolioModel.user_id == user_id)
        .options(
            selectinload(PortfolioModel.holdings).selectinload(HoldingModel.asset)
        )
    )
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portafolio con id '{portfolio_id}' no encontrado o no pertenece al usuario.",
        )
    return portfolio


async def ensure_asset(
    db: AsyncSession,
    ticker: str,
    asset_type: Optional[str] = None,
    currency: str = "ARS",
    name: Optional[str] = None,
    sector: str = "OTHER",
    market: str = "BYMA",
) -> AssetModel:
    """Finds an existing asset by ticker or inserts a new one."""
    t = ticker.strip().upper()
    stmt = select(AssetModel).where(AssetModel.ticker == t)
    result = await db.execute(stmt)
    asset = result.scalar_one_or_none()

    if not asset:
        inferred_type = asset_type or "CEDEAR"
        asset = AssetModel(
            ticker=t,
            name=name or t,
            asset_type=inferred_type,
            currency=currency.strip().upper(),
            sector=sector.strip().upper() if sector else "OTHER",
            market=market.strip().upper() if market else "BYMA",
        )
        db.add(asset)
        await db.flush()

    return asset


def orm_to_domain_portfolio(
    p_model: PortfolioModel,
    fx_ccl: float = 1300.0,
    investor_profile: Optional[InvestorProfile] = None,
) -> Portfolio:
    """Converts a persisted PortfolioModel into a pure domain Portfolio entity."""
    if investor_profile is None:
        try:
            profile_val = getattr(p_model, "investor_profile", "MODERATE")
            investor_profile = InvestorProfile(profile_val)
        except Exception:
            investor_profile = InvestorProfile.MODERATE

    domain_holdings: List[Holding] = []

    for h in p_model.holdings:
        asset_model = h.asset
        try:
            at = AssetType(asset_model.asset_type) if asset_model else AssetType.CEDEAR
        except ValueError:
            at = AssetType.CEDEAR

        try:
            cur = Currency(asset_model.currency) if asset_model else Currency.ARS
        except ValueError:
            cur = Currency.ARS

        try:
            sec = Sector(asset_model.sector) if asset_model else Sector.OTHER
        except ValueError:
            sec = Sector.OTHER

        domain_asset = Asset(
            ticker=h.asset_ticker,
            name=asset_model.name if asset_model else h.asset_ticker,
            asset_type=at,
            currency=cur,
            sector=sec,
            country="AR",
            cedear_ratio=asset_model.cedear_ratio if asset_model else None,
            underlying_ticker=asset_model.underlying_ticker if asset_model else None,
        )

        domain_holdings.append(
            Holding(
                asset=domain_asset,
                quantity=h.quantity,
                average_buy_price=h.average_buy_price,
                current_price=h.current_price,
                currency=cur,
            )
        )

    return Portfolio(
        id=p_model.id,
        name=p_model.name,
        investor_profile=investor_profile,
        holdings=domain_holdings,
        cash_balance_ars=p_model.cash_balance_ars,
        cash_balance_usd=p_model.cash_balance_usd,
    )


def build_portfolio_response(
    p_model: PortfolioModel,
    fx_ccl: float = 1300.0,
) -> PortfolioResponse:
    """Assembles a rich PortfolioResponse DTO with computed weights and valuations."""
    total_holdings_ars = 0.0
    total_holdings_usd = 0.0

    holding_dtos: List[HoldingResponse] = []
    holding_values_ars: List[float] = []

    for h in p_model.holdings:
        is_usd = (h.asset.currency == "USD") if h.asset else False
        if is_usd:
            val_ars = h.quantity * h.current_price * fx_ccl
            val_usd = h.quantity * h.current_price
            cost_ars = h.quantity * h.average_buy_price * fx_ccl
        else:
            val_ars = h.quantity * h.current_price
            val_usd = (h.quantity * h.current_price) / fx_ccl if fx_ccl > 0 else 0.0
            cost_ars = h.quantity * h.average_buy_price

        total_holdings_ars += val_ars
        total_holdings_usd += val_usd
        holding_values_ars.append(val_ars)

        pnl = val_ars - cost_ars
        pnl_pct = round((pnl / cost_ars) * 100.0, 2) if cost_ars > 0 else 0.0

        asset_dto = None
        if h.asset:
            asset_dto = AssetResponse(
                ticker=h.asset.ticker,
                name=h.asset.name,
                asset_type=h.asset.asset_type,
                currency=h.asset.currency,
                sector=h.asset.sector,
                market=h.asset.market,
                cedear_ratio=h.asset.cedear_ratio,
                underlying_ticker=h.asset.underlying_ticker,
            )

        holding_dtos.append(
            HoldingResponse(
                id=h.id,
                portfolio_id=h.portfolio_id,
                asset_ticker=h.asset_ticker,
                quantity=h.quantity,
                average_buy_price=h.average_buy_price,
                current_price=h.current_price,
                total_cost=round(cost_ars, 2),
                market_value=round(val_ars, 2),
                unrealized_pnl=round(pnl, 2),
                unrealized_pnl_pct=pnl_pct,
                asset=asset_dto,
            )
        )

    total_portfolio_ars = total_holdings_ars + p_model.cash_balance_ars + (p_model.cash_balance_usd * fx_ccl)
    total_portfolio_usd = total_holdings_usd + p_model.cash_balance_usd + (p_model.cash_balance_ars / fx_ccl if fx_ccl > 0 else 0.0)

    for i, h_dto in enumerate(holding_dtos):
        if total_portfolio_ars > 0:
            h_dto.weight_pct = round((holding_values_ars[i] / total_portfolio_ars) * 100.0, 2)
        else:
            h_dto.weight_pct = 0.0

    return PortfolioResponse(
        id=p_model.id,
        user_id=p_model.user_id,
        name=p_model.name,
        investor_profile=getattr(p_model, "investor_profile", "MODERATE"),
        cash_balance_ars=p_model.cash_balance_ars,
        cash_balance_usd=p_model.cash_balance_usd,
        total_market_value_ars=round(total_portfolio_ars, 2),
        total_market_value_usd=round(total_portfolio_usd, 2),
        holdings_count=len(holding_dtos),
        holdings=holding_dtos,
        updated_at=p_model.updated_at,
    )
