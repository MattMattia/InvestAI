"""
Script Semilla de Demostración para InvestAI Enterprise.
Crea el usuario demo, cartera institucional y tenencias iniciales en BYMA de forma idempotente.
"""
import asyncio
from datetime import datetime, timezone
import logging
import os
import sys
import uuid

from sqlalchemy import select

# Asegurar backend en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal, async_engine, init_db, is_sqlite
from app.core.security import get_password_hash
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
        "ticker": "AL30",
        "name": "Bono Bonar 2030 L.A.",
        "asset_type": "BOND",
        "currency": "ARS",
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
        "average_buy_price": 610.0,
        "current_price": 645.0,
    },
]


async def seed_demo_data() -> None:
    logger.info("Iniciando verificación e inserción de datos semilla...")
    await init_db()

    # Migración defensiva en caliente para SQLite local si el archivo es preexistente
    if is_sqlite:
        async with async_engine.begin() as conn:
            def _migrate_sqlite_schema(sync_conn):
                user_res = sync_conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
                user_cols = [r[1] for r in user_res]
                if user_cols:
                    if "full_name" not in user_cols:
                        sync_conn.exec_driver_sql(
                            "ALTER TABLE users ADD COLUMN full_name VARCHAR(255) DEFAULT 'InvestAI User' NOT NULL"
                        )
                    if "is_active" not in user_cols:
                        sync_conn.exec_driver_sql(
                            "ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"
                        )
                    if "role" not in user_cols:
                        sync_conn.exec_driver_sql(
                            "ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'TRADER' NOT NULL"
                        )
                    if "updated_at" not in user_cols:
                        sync_conn.exec_driver_sql(
                            "ALTER TABLE users ADD COLUMN updated_at DATETIME"
                        )
            await conn.run_sync(_migrate_sqlite_schema)

    async with AsyncSessionLocal() as session:
        # 1. Asegurar Activos en BYMA
        for asset_data in DEMO_ASSETS:
            stmt = select(AssetModel).where(AssetModel.ticker == asset_data["ticker"])
            result = await session.execute(stmt)
            existing_asset = result.scalar_one_or_none()
            if not existing_asset:
                logger.info(f"Creando activo {asset_data['ticker']} ({asset_data['asset_type']})...")
                new_asset = AssetModel(**asset_data)
                session.add(new_asset)
        await session.commit()

        # 2. Asegurar Usuario Demo
        stmt = select(UserModel).where(UserModel.email == DEMO_EMAIL)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.info(f"Creando usuario demo: {DEMO_EMAIL} con rol TRADER...")
            user_id = str(uuid.uuid4())
            user = UserModel(
                id=user_id,
                email=DEMO_EMAIL,
                hashed_password=get_password_hash(DEMO_PASSWORD),
                full_name="Trader Demo InvestAI",
                is_active=True,
                role=UserRole.TRADER.value,
                investor_profile="MODERATE",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"Usuario demo creado exitosamente con ID: {user.id}")
        else:
            logger.info(f"Usuario demo existente con ID: {user.id}")

        user_id_str = str(user.id)

        # 3. Asegurar Cartera Institucional Demo
        stmt = select(PortfolioModel).where(
            PortfolioModel.user_id == user_id_str,
            PortfolioModel.name == DEMO_PORTFOLIO_NAME,
        )
        result = await session.execute(stmt)
        portfolio = result.scalar_one_or_none()

        if not portfolio:
            logger.info(f"Creando cartera demo '{DEMO_PORTFOLIO_NAME}'...")
            portfolio_id = str(uuid.uuid4())
            portfolio = PortfolioModel(
                id=portfolio_id,
                user_id=user_id_str,
                name=DEMO_PORTFOLIO_NAME,
                investor_profile="MODERATE",
                cash_balance_ars=2500000.0,
                cash_balance_usd=15000.0,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            logger.info(f"Cartera demo creada exitosamente con ID: {portfolio.id}")
        else:
            logger.info(f"Cartera demo existente con ID: {portfolio.id}")

        portfolio_id_str = str(portfolio.id)

        # 4. Asegurar Tenencias / Posiciones en la Cartera
        for holding_data in DEMO_HOLDINGS:
            stmt = select(HoldingModel).where(
                HoldingModel.portfolio_id == portfolio_id_str,
                HoldingModel.asset_ticker == holding_data["asset_ticker"],
            )
            result = await session.execute(stmt)
            existing_holding = result.scalar_one_or_none()
            if not existing_holding:
                logger.info(f"Agregando posición {holding_data['asset_ticker']} ({holding_data['quantity']} un.) a la cartera...")
                new_holding = HoldingModel(
                    portfolio_id=portfolio_id_str,
                    asset_ticker=holding_data["asset_ticker"],
                    quantity=holding_data["quantity"],
                    average_buy_price=holding_data["average_buy_price"],
                    current_price=holding_data["current_price"],
                )
                session.add(new_holding)
        await session.commit()

    await async_engine.dispose()
    logger.info("Datos semilla verificados y persistidos exitosamente.")


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
