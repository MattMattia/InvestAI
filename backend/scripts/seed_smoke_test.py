"""
Script Semilla de Demostración de Alta Velocidad para InvestAI Enterprise.
Crea o actualiza el usuario demo, catálogo BYMA calibrado y cartera institucional en < 0.3s.
"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

# Asegurar backend en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal, async_engine, init_db
from app.core.security import get_password_hash
from app.domain.services.market_data_provider import infer_instrument_metadata
from app.models import AssetModel, HoldingModel, PortfolioModel, UserModel
from app.schemas.user import UserRole

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("investai.seed")

DEMO_EMAIL = "demo@investai.com"
DEMO_PASSWORD = "InvestAI2026!"
DEMO_PORTFOLIO_NAME = "Cartera Institucional Alfa"

DEMO_ASSETS = [
    {
        "ticker": "GGAL",
        "name": "Grupo Financiero Galicia S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Financials",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "YPFD",
        "name": "YPF S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Energy",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "PAMP",
        "name": "Pampa Energía S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Energy",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "BMA",
        "name": "Banco Macro S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Financials",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "ALUA",
        "name": "Aluar Aluminio Argentino S.A.I.C.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Materials",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "TXAR",
        "name": "Ternium Argentina S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Materials",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "COME",
        "name": "Sociedad Comercial del Plata S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Conglomerates",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "CEPU",
        "name": "Central Puerto S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Utilities",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "EDN",
        "name": "Edenor S.A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Utilities",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "CRES",
        "name": "Cresud S.A.C.I.F. y A.",
        "asset_type": "EQUITY",
        "currency": "ARS",
        "sector": "Real Estate & Agro",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "AAPL",
        "name": "Apple Inc. (CEDEAR 10:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Technology",
        "market": "BYMA",
        "cedear_ratio": 10.0,
        "underlying_ticker": "AAPL",
    },
    {
        "ticker": "NVDA",
        "name": "NVIDIA Corp. (CEDEAR 24:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Technology",
        "market": "BYMA",
        "cedear_ratio": 24.0,
        "underlying_ticker": "NVDA",
    },
    {
        "ticker": "MSFT",
        "name": "Microsoft Corp. (CEDEAR 30:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Technology",
        "market": "BYMA",
        "cedear_ratio": 30.0,
        "underlying_ticker": "MSFT",
    },
    {
        "ticker": "SPY",
        "name": "SPDR S&P 500 ETF Trust (CEDEAR 20:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Index ETF",
        "market": "BYMA",
        "cedear_ratio": 20.0,
        "underlying_ticker": "SPY",
    },
    {
        "ticker": "QQQ",
        "name": "Invesco QQQ Trust (CEDEAR 20:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Index ETF",
        "market": "BYMA",
        "cedear_ratio": 20.0,
        "underlying_ticker": "QQQ",
    },
    {
        "ticker": "MELI",
        "name": "MercadoLibre Inc. (CEDEAR 60:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Consumer Discretionary",
        "market": "BYMA",
        "cedear_ratio": 60.0,
        "underlying_ticker": "MELI",
    },
    {
        "ticker": "KO",
        "name": "The Coca-Cola Co. (CEDEAR 5:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Consumer Staples",
        "market": "BYMA",
        "cedear_ratio": 5.0,
        "underlying_ticker": "KO",
    },
    {
        "ticker": "TSLA",
        "name": "Tesla Inc. (CEDEAR 15:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Automotive",
        "market": "BYMA",
        "cedear_ratio": 15.0,
        "underlying_ticker": "TSLA",
    },
    {
        "ticker": "AMZN",
        "name": "Amazon.com Inc. (CEDEAR 144:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Technology",
        "market": "BYMA",
        "cedear_ratio": 144.0,
        "underlying_ticker": "AMZN",
    },
    {
        "ticker": "GOOGL",
        "name": "Alphabet Inc. (CEDEAR 58:1)",
        "asset_type": "CEDEAR",
        "currency": "ARS",
        "sector": "Technology",
        "market": "BYMA",
        "cedear_ratio": 58.0,
        "underlying_ticker": "GOOGL",
    },
    {
        "ticker": "AL30",
        "name": "Bono Rep. Argentina USD Step-Up 2030 (ARS)",
        "asset_type": "BOND",
        "currency": "ARS",
        "sector": "Sovereign",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "AL30D",
        "name": "Bono Rep. Argentina USD Step-Up 2030 (USD MEP)",
        "asset_type": "BOND",
        "currency": "USD",
        "sector": "Sovereign",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "GD30",
        "name": "Bono Global Rep. Argentina USD 2030 (ARS)",
        "asset_type": "BOND",
        "currency": "ARS",
        "sector": "Sovereign",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "GD30D",
        "name": "Bono Global Rep. Argentina USD 2030 (USD MEP)",
        "asset_type": "BOND",
        "currency": "USD",
        "sector": "Sovereign",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "AE38",
        "name": "Bono Rep. Argentina USD 2038 (ARS)",
        "asset_type": "BOND",
        "currency": "ARS",
        "sector": "Sovereign",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
    {
        "ticker": "AE38D",
        "name": "Bono Rep. Argentina USD 2038 (USD MEP)",
        "asset_type": "BOND",
        "currency": "USD",
        "sector": "Sovereign",
        "market": "BYMA",
        "cedear_ratio": None,
        "underlying_ticker": None,
    },
]

DEMO_HOLDINGS = [
    {
        "asset_ticker": "GGAL",
        "quantity": 1500.0,
        "average_buy_price": 4850.0,
        "current_price": 5120.0,
    },
    {
        "asset_ticker": "YPFD",
        "quantity": 250.0,
        "average_buy_price": 28500.0,
        "current_price": 30200.0,
    },
    {
        "asset_ticker": "AAPL",
        "quantity": 180.0,
        "average_buy_price": 14200.0,
        "current_price": 15450.0,
    },
    {
        "asset_ticker": "AL30",
        "quantity": 5000.0,
        "average_buy_price": 790.0,
        "current_price": 838.70,
    },
]


async def seed_demo_data() -> None:
    await init_db()

    async with AsyncSessionLocal() as session:
        # 1. Asegurar Activos en BYMA en una sola consulta en lote con métricas 10Y
        existing_assets_res = await session.execute(select(AssetModel))
        existing_assets_map = {a.ticker: a for a in existing_assets_res.scalars().all()}

        new_count = 0
        for asset_data in DEMO_ASSETS:
            t_sym = asset_data["ticker"]
            meta = infer_instrument_metadata(t_sym)
            if t_sym not in existing_assets_map:
                asset_obj = AssetModel(**asset_data)
                session.add(asset_obj)
                new_count += 1
            else:
                asset_obj = existing_assets_map[t_sym]

            asset_obj.history_start_date = meta.get("history_start_date", "2016-11-01")
            asset_obj.history_years_available = float(meta.get("history_years_available", 10.0))
            asset_obj.data_points_count = int(meta.get("data_points_count", 2520))
            asset_obj.cagr_annualized = float(meta.get("cagr_annualized", 0.14))
            asset_obj.volatility_annualized = float(meta.get("volatility_annualized", 0.25))
            asset_obj.sharpe_ratio = float(meta.get("sharpe_ratio", 0.48))
            asset_obj.sortino_ratio = float(meta.get("sortino_ratio", 0.68))
            asset_obj.max_drawdown = float(meta.get("max_drawdown", 0.28))
            asset_obj.beta_market = float(meta.get("beta_market", 1.0))
            asset_obj.var_95_daily = float(meta.get("var_95_daily", 0.026))
            asset_obj.pe_ratio = meta.get("pe_ratio")
            asset_obj.pb_ratio = meta.get("pb_ratio")
            asset_obj.roe_pct = meta.get("roe_pct")
            asset_obj.debt_to_equity = meta.get("debt_to_equity")
            asset_obj.dividend_yield_pct = meta.get("dividend_yield_pct")
            asset_obj.market_cap_usd = meta.get("market_cap_usd")
            asset_obj.ytm_tir_pct = meta.get("ytm_tir_pct")
            asset_obj.modified_duration = meta.get("modified_duration")
            asset_obj.parity_pct = meta.get("parity_pct")
            asset_obj.metrics_payload = meta

        await session.commit()
        if new_count:
            logger.info(f"Insertados {new_count} activos BYMA con métricas 10Y en catálogo.")

        # 2. Asegurar Usuario Demo (evita re-hashear bcrypt si ya existe)
        stmt = select(UserModel).where(UserModel.email == DEMO_EMAIL)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.info(f"Creando usuario demo: {DEMO_EMAIL} con rol TRADER...")
            user = UserModel(
                id=str(uuid.uuid4()),
                email=DEMO_EMAIL,
                hashed_password=get_password_hash(DEMO_PASSWORD),
                full_name="Trader Demo InvestAI",
                is_active=True,
                role=UserRole.TRADER.value,
                investor_profile="MODERATE",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Asegurar rol TRADER activo
            if user.role != UserRole.TRADER.value and user.role != UserRole.ADMIN.value:
                user.role = UserRole.TRADER.value
                await session.commit()

        user_id_str = str(user.id)

        # 3. Asegurar Cartera Institucional Demo
        stmt = select(PortfolioModel).where(
            PortfolioModel.user_id == user_id_str,
            PortfolioModel.name == DEMO_PORTFOLIO_NAME,
        )
        result = await session.execute(stmt)
        portfolio = result.scalar_one_or_none()

        if not portfolio:
            portfolio = PortfolioModel(
                id=str(uuid.uuid4()),
                user_id=user_id_str,
                name=DEMO_PORTFOLIO_NAME,
                investor_profile="MODERATE",
                cash_balance_ars=2500000.0,
                cash_balance_usd=15000.0,
                updated_at=datetime.now(UTC),
            )
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)

        portfolio_id_str = str(portfolio.id)

        # 4. Asegurar Tenencias / Posiciones Calibradas en lote
        holdings_res = await session.execute(
            select(HoldingModel).where(HoldingModel.portfolio_id == portfolio_id_str)
        )
        existing_holdings_map = {h.asset_ticker: h for h in holdings_res.scalars().all()}

        for holding_data in DEMO_HOLDINGS:
            ticker = holding_data["asset_ticker"]
            if ticker not in existing_holdings_map:
                session.add(
                    HoldingModel(
                        portfolio_id=portfolio_id_str,
                        asset_ticker=ticker,
                        quantity=holding_data["quantity"],
                        average_buy_price=holding_data["average_buy_price"],
                        current_price=holding_data["current_price"],
                    )
                )
            else:
                # Calibrar precio actual de mercado si quedó con valor viejo
                existing_h = existing_holdings_map[ticker]
                existing_h.current_price = holding_data["current_price"]
                if ticker == "AL30" and existing_h.average_buy_price < 700.0:
                    existing_h.average_buy_price = holding_data["average_buy_price"]

        await session.commit()

    await async_engine.dispose()
    logger.info("Semilla institucional verificada y calibrada.")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
