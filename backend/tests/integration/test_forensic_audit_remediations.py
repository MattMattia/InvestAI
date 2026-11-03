"""
Suite de pruebas de integración y regresión para el Protocolo de Auditoría Forense (Apartados 1 al 7).
Valida:
1. Hot-swap de perfil de inversor y rol RBAC mediante PATCH /api/v1/auth/me.
2. Detección de esquema real de Balanz ("Descripcion, Cantidad, Precio...") y limpieza de tickers descriptivos ("CEDEAR NVDA" -> "NVDA").
3. Simulación idempotente de rebalanceo (?dry_run=true) sin duplicación de órdenes PENDING.
4. Ejecución contable (POST /api/v1/orders/{id}/execute) con deducción de aranceles BYMA/CNV y actualización de tenencias, cancelación FSM (/cancel) y defensa anti-IDOR/BOLA.
5. CRUD completo de cartera (PATCH y DELETE /api/v1/portfolios/{id}).
"""
from typing import AsyncGenerator
import uuid
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.deps import get_db_session
from app.core.database import Base
from app.core.security import create_access_token, get_password_hash
from app.domain.services.ingestion.csv_parser import CSVReportParser
from app.domain.services.ingestion.data_cleaning_pipeline import DataCleaningPipeline
from app.domain.services.ingestion.schema_detector import (
    CanonicalReportField,
    SchemaDetector,
)
from app.main import app
from app.models.user import UserModel
from app.schemas.user import UserRole


@pytest_asyncio.fixture
async def forensic_env() -> AsyncGenerator[dict, None]:
    """Entorno HTTP + DB aislado en memoria para pruebas de auditoría forense."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield {"client": client, "session_factory": session_factory}

    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_trader_user(
    session_factory: async_sessionmaker[AsyncSession],
    prefix: str = "audit_trader",
) -> dict:
    """Crea un usuario TRADER directamente en la sesión de prueba y retorna sus cabeceras JWT."""
    unique_email = f"{prefix}_{uuid.uuid4().hex[:8]}@investai.com"
    async with session_factory() as session:
        user = UserModel(
            email=unique_email,
            hashed_password=get_password_hash("StrongPassword123!"),
            full_name="Operador Institucional Auditado",
            investor_profile="MODERATE",
            role=UserRole.TRADER,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token(subject=str(user.id), role=UserRole.TRADER.value)
        return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": str(user.id)}


@pytest.mark.asyncio
async def test_patch_auth_me_hot_swap_profile_and_rbac_role(
    forensic_env: dict,
) -> None:
    """Verifica que PATCH /api/v1/auth/me permita conmutar perfil de inversor y rol RBAC en caliente."""
    client: httpx.AsyncClient = forensic_env["client"]
    ctx = await _seed_trader_user(forensic_env["session_factory"], "hotswap")
    headers = ctx["headers"]

    # Switch to CONSERVATIVE + ADMIN via PATCH /api/v1/auth/me
    update_res = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={
            "full_name": "Director de Cumplimiento",
            "investor_profile": "CONSERVATIVE",
            "role": "ADMIN",
        },
    )
    assert update_res.status_code == 200
    raw_updated = update_res.json()
    updated = raw_updated.get("data", raw_updated)
    assert updated["full_name"] == "Director de Cumplimiento"
    assert updated["investor_profile"] == "CONSERVATIVE"
    assert updated["role"] == "ADMIN"

    # Verify GET /api/v1/auth/me reflects the hot-swapped role and profile
    me_res = await client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    raw_me = me_res.json()
    me_data = raw_me.get("data", raw_me)
    assert me_data["role"] == "ADMIN"
    assert me_data["investor_profile"] == "CONSERVATIVE"


def test_balanz_real_header_detection_and_descriptive_ticker_cleaning() -> None:
    """Verifica que el detector de esquema y el pipeline de limpieza procesen extractos reales de Balanz."""
    balanz_headers = [
        "Descripcion",
        "Cantidad",
        "Precio",
        "ValorActual",
        "%Ganancia",
        "Ganancia$",
        "Moneda",
    ]
    detector = SchemaDetector()
    result = detector.detect_schema(balanz_headers)

    assert CanonicalReportField.TICKER in result.mappings
    assert result.mappings[CanonicalReportField.TICKER].raw_header == "Descripcion"
    assert result.mappings[CanonicalReportField.TICKER].confidence_score == 1.0
    assert result.mappings[CanonicalReportField.QUANTITY].raw_header == "Cantidad"
    assert result.mappings[CanonicalReportField.CURRENCY].raw_header == "Moneda"

    # Verify descriptive ticker cleaning
    assert DataCleaningPipeline.normalize_ticker("CEDEAR NVDA") == "NVDA"
    assert DataCleaningPipeline.normalize_ticker("GGAL - Grupo Financiero Galicia") == "GGAL"
    assert DataCleaningPipeline.normalize_ticker("AL30 (Bono)") == "AL30"
    assert DataCleaningPipeline.normalize_ticker("YPFD S.A.") == "YPFD"

    # Verify full CSV parsing + cleaning pipeline on Balanz format
    csv_content = (
        "Tenencias al 02/11/2026,,,,,,\n"
        "Descripcion,Cantidad,Precio,ValorActual,%Ganancia,Ganancia$,Moneda\n"
        "GGAL - Grupo Financiero Galicia,1200,5120.00,6144000.00,21.90%,1104000.00,Pesos\n"
        "CEDEAR NVDA,150,14290.00,2143500.00,14.78%,276000.00,Pesos\n"
        "AL30D (Bono USD),2500,68.45,171125.00,15.04%,22375.00,Dolares\n"
    ).encode("utf-8")

    raw_records = CSVReportParser()._parse_sync(csv_content, "Tenencias_Balanz.csv")
    tickers = [DataCleaningPipeline.normalize_ticker(rec.raw_ticker) for rec in raw_records]
    assert tickers == ["GGAL", "NVDA", "AL30D"]


@pytest.mark.asyncio
async def test_rebalance_dry_run_idempotency(
    forensic_env: dict,
) -> None:
    """Verifica que POST /portfolios/{id}/rebalance?dry_run=true no inserte órdenes duplicadas en DB."""
    client: httpx.AsyncClient = forensic_env["client"]
    ctx = await _seed_trader_user(forensic_env["session_factory"], "rebal_dry")
    headers = ctx["headers"]

    port_res = await client.post(
        "/api/v1/portfolios",
        headers=headers,
        json={
            "name": "Cartera Rebalanceo DryRun",
            "investor_profile": "MODERATE",
            "cash_balance_ars": 5000000.0,
            "cash_balance_usd": 1000.0,
            "holdings": [
                {
                    "ticker": "GGAL",
                    "quantity": 1000,
                    "average_buy_price": 4500.0,
                    "current_price": 5120.0,
                    "currency": "ARS",
                    "asset_type": "STOCK",
                },
                {
                    "ticker": "YPFD",
                    "quantity": 20,
                    "average_buy_price": 28000.0,
                    "current_price": 30200.0,
                    "currency": "ARS",
                    "asset_type": "STOCK",
                },
            ],
        },
    )
    assert port_res.status_code == 201
    portfolio_id = port_res.json()["id"]

    rebal_payload = {
        "targets": [
            {"ticker": "GGAL", "target_weight": 50.0, "tolerance_band": 2.0},
            {"ticker": "YPFD", "target_weight": 50.0, "tolerance_band": 2.0},
        ],
        "include_hold": False,
    }

    # Execute dry_run twice
    for _ in range(2):
        sim_res = await client.post(
            f"/api/v1/portfolios/{portfolio_id}/rebalance?dry_run=true",
            headers=headers,
            json=rebal_payload,
        )
        assert sim_res.status_code == 200
        assert len(sim_res.json()["orders"]) > 0

    # Verify 0 orders were persisted in DB during dry_run simulations
    orders_res = await client.get(
        f"/api/v1/orders?portfolio_id={portfolio_id}",
        headers=headers,
    )
    assert orders_res.status_code == 200
    assert len(orders_res.json()) == 0


@pytest.mark.asyncio
async def test_order_execute_and_cancel_fsm_settlement_and_bola_isolation(
    forensic_env: dict,
) -> None:
    """Verifica la liquidación contable de órdenes (POST /orders/{id}/execute), cancelación y defensa anti-IDOR."""
    client: httpx.AsyncClient = forensic_env["client"]
    owner_ctx = await _seed_trader_user(forensic_env["session_factory"], "ord_owner")
    intruder_ctx = await _seed_trader_user(forensic_env["session_factory"], "ord_intruder")

    owner_headers = owner_ctx["headers"]
    intruder_headers = intruder_ctx["headers"]

    port_res = await client.post(
        "/api/v1/portfolios",
        headers=owner_headers,
        json={
            "name": "Cartera Ejecución FSM",
            "investor_profile": "AGGRESSIVE",
            "cash_balance_ars": 1000000.0,
            "cash_balance_usd": 5000.0,
            "holdings": [
                {
                    "ticker": "GGAL",
                    "quantity": 100,
                    "average_buy_price": 5000.0,
                    "current_price": 5120.0,
                    "currency": "ARS",
                    "asset_type": "STOCK",
                }
            ],
        },
    )
    assert port_res.status_code == 201
    portfolio_id = port_res.json()["id"]

    # 1. Create BUY order for 10 GGAL @ $5,120 ARS
    create_buy = await client.post(
        "/api/v1/orders",
        headers=owner_headers,
        json={
            "portfolio_id": portfolio_id,
            "ticker": "GGAL",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": 10,
            "price": 5120.0,
            "currency": "ARS",
            "justification": "Compra asistida pre-trade",
        },
    )
    assert create_buy.status_code == 201
    buy_order_id = create_buy.json()["id"]

    # BOLA check: intruder cannot execute owner's order
    bola_exec = await client.post(
        f"/api/v1/orders/{buy_order_id}/execute",
        headers=intruder_headers,
    )
    assert bola_exec.status_code == 404

    # Owner executes the order
    exec_res = await client.post(
        f"/api/v1/orders/{buy_order_id}/execute",
        headers=owner_headers,
    )
    assert exec_res.status_code == 200
    assert exec_res.json()["status"] == "EXECUTED"

    # Cannot cancel an already executed order
    cancel_after_exec = await client.post(
        f"/api/v1/orders/{buy_order_id}/cancel",
        headers=owner_headers,
    )
    assert cancel_after_exec.status_code == 400

    # Verify portfolio cash_balance_ars and GGAL holding quantity were updated
    # Gross = 10 * 5120 = 51200; Broker fee (0.5%) = 256; VAT (21%) = 53.76; Market fee (0.1%) = 51.20 -> Total fees = 360.96
    # Expected cash = 1,000,000 - 51,560.96 = 948,439.04
    updated_port = await client.get(
        f"/api/v1/portfolios/{portfolio_id}",
        headers=owner_headers,
    )
    assert updated_port.status_code == 200
    port_json = updated_port.json()
    assert abs(float(port_json["cash_balance_ars"]) - 948439.04) < 0.05
    ggal_holding = next(
        h for h in port_json["holdings"] if h["asset_ticker"] == "GGAL"
    )
    assert float(ggal_holding["quantity"]) == 110.0

    # 2. Create another order and cancel it
    create_sell = await client.post(
        "/api/v1/orders",
        headers=owner_headers,
        json={
            "portfolio_id": portfolio_id,
            "ticker": "GGAL",
            "side": "SELL",
            "order_type": "LIMIT",
            "quantity": 25,
            "price": 5300.0,
            "currency": "ARS",
        },
    )
    assert create_sell.status_code == 201
    sell_order_id = create_sell.json()["id"]

    cancel_res = await client.post(
        f"/api/v1/orders/{sell_order_id}/cancel",
        headers=owner_headers,
        json={"reason": "Cancelada por el operador"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_portfolio_crud_treasury_and_delete(
    forensic_env: dict,
) -> None:
    """Verifica el ciclo CRUD completo de cartera: actualización de tesorería bimonetaria, perfil y baja."""
    client: httpx.AsyncClient = forensic_env["client"]
    ctx = await _seed_trader_user(forensic_env["session_factory"], "port_crud")
    headers = ctx["headers"]

    create_res = await client.post(
        "/api/v1/portfolios",
        headers=headers,
        json={
            "name": "Cartera Temporal Test",
            "investor_profile": "CONSERVATIVE",
            "cash_balance_ars": 500000.0,
            "cash_balance_usd": 1000.0,
        },
    )
    assert create_res.status_code == 201
    pid = create_res.json()["id"]

    patch_res = await client.patch(
        f"/api/v1/portfolios/{pid}",
        headers=headers,
        json={
            "name": "Cartera Institucional Editada",
            "investor_profile": "AGGRESSIVE",
            "cash_balance_ars": 2500000.0,
            "cash_balance_usd": 7500.0,
        },
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["name"] == "Cartera Institucional Editada"
    assert patched["investor_profile"] == "AGGRESSIVE"
    assert float(patched["cash_balance_ars"]) == 2500000.0
    assert float(patched["cash_balance_usd"]) == 7500.0

    del_res = await client.delete(
        f"/api/v1/portfolios/{pid}",
        headers=headers,
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    get_deleted = await client.get(
        f"/api/v1/portfolios/{pid}",
        headers=headers,
    )
    assert get_deleted.status_code == 404
