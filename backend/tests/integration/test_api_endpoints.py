import io
import unittest
import uuid

import httpx
from app.api.deps import get_db_session
from app.core.database import Base
from app.core.security import create_access_token, get_password_hash
from app.main import app as fastapi_app
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.user import UserRole
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


class TestApiEndpointsIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Seed real users with explicit RBAC roles (TRADER A, TRADER B, VIEWER, ADMIN)
        pw_hash = get_password_hash("IntegrationTestPass!2026", rounds=4)
        self.trader_a = UserModel(
            id=uuid.uuid4(),
            email="trader.a@investai.internal",
            hashed_password=pw_hash,
            full_name="Trader Alpha",
            role=UserRole.TRADER,
            is_active=True,
        )
        self.trader_b = UserModel(
            id=uuid.uuid4(),
            email="trader.b@investai.internal",
            hashed_password=pw_hash,
            full_name="Trader Beta",
            role=UserRole.TRADER,
            is_active=True,
        )
        self.viewer_user = UserModel(
            id=uuid.uuid4(),
            email="viewer@investai.internal",
            hashed_password=pw_hash,
            full_name="Viewer User",
            role=UserRole.VIEWER,
            is_active=True,
        )
        self.admin_user = UserModel(
            id=uuid.uuid4(),
            email="admin@investai.internal",
            hashed_password=pw_hash,
            full_name="Admin Institutional",
            role=UserRole.ADMIN,
            is_active=True,
        )

        async with self.SessionLocal() as session:
            session.add_all([self.trader_a, self.trader_b, self.viewer_user, self.admin_user])
            await session.commit()

        # Generate legitimate JWT access tokens
        self.trader_a_token = create_access_token(
            self.trader_a.id, self.trader_a.role, email=self.trader_a.email
        )
        self.trader_b_token = create_access_token(
            self.trader_b.id, self.trader_b.role, email=self.trader_b.email
        )
        self.viewer_token = create_access_token(
            self.viewer_user.id, self.viewer_user.role, email=self.viewer_user.email
        )
        self.admin_token = create_access_token(
            self.admin_user.id, self.admin_user.role, email=self.admin_user.email
        )

        self.auth_headers = {"Authorization": f"Bearer {self.trader_a_token}"}
        self.trader_b_headers = {"Authorization": f"Bearer {self.trader_b_token}"}
        self.viewer_headers = {"Authorization": f"Bearer {self.viewer_token}"}
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

        async def _override_get_db():
            async with self.SessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()

        fastapi_app.dependency_overrides[get_db_session] = _override_get_db
        self.transport = httpx.ASGITransport(app=fastapi_app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            await self.client.aclose()
        fastapi_app.dependency_overrides.clear()
        if hasattr(self, "engine") and self.engine is not None:
            await self.engine.dispose()

    async def test_health_and_root(self) -> None:
        root_res = await self.client.get("/")
        self.assertEqual(root_res.status_code, 200)
        self.assertEqual(root_res.json()["status"], "online")
        self.assertIn("X-Request-ID", root_res.headers)
        self.assertIn("X-Execution-Time-Ms", root_res.headers)

        health_res = await self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.json()["status"], "healthy")
        self.assertEqual(health_res.json()["database"], "connected")
        self.assertIn("X-Request-ID", health_res.headers)
        self.assertIn("X-Execution-Time-Ms", health_res.headers)

    async def test_trace_middleware_correlation_headers(self) -> None:
        """Valida la inyección y preservación de X-Request-ID y X-Execution-Time-Ms (OBS-01)."""
        # Caso 1: Header suministrado externamente
        custom_id = "trace-client-correl-987"
        res_custom = await self.client.get("/", headers={"X-Request-ID": custom_id})
        self.assertEqual(res_custom.status_code, 200)
        self.assertEqual(res_custom.headers["X-Request-ID"], custom_id)
        self.assertIn("X-Execution-Time-Ms", res_custom.headers)
        self.assertGreaterEqual(float(res_custom.headers["X-Execution-Time-Ms"]), 0.0)

        # Caso 2: Header omitido -> generación automática de UUIDv4
        res_auto = await self.client.get("/")
        self.assertEqual(res_auto.status_code, 200)
        auto_id = res_auto.headers.get("X-Request-ID")
        self.assertIsNotNone(auto_id)
        self.assertGreater(len(auto_id), 10)
        self.assertIn("X-Execution-Time-Ms", res_auto.headers)

    async def test_semantic_health_probes(self) -> None:
        """Valida los endpoints semánticos de observabilidad liveness y readiness (OBS-02)."""
        # 1. Liveness probe (sin I/O)
        res_live = await self.client.get("/health/liveness")
        self.assertEqual(res_live.status_code, 200)
        self.assertEqual(res_live.json(), {"status": "alive"})
        self.assertIn("X-Request-ID", res_live.headers)

        # 2. Readiness probe (validación real de base de datos)
        res_ready = await self.client.get("/health/readiness")
        self.assertEqual(res_ready.status_code, 200)
        data = res_ready.json()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["database"]["status"], "up")
        self.assertGreaterEqual(data["database"]["latency_ms"], 0.0)
        self.assertIn("timestamp", data)
        self.assertIn("environment", data)
        self.assertIn("X-Request-ID", res_ready.headers)

    async def test_portfolio_crud_lifecycle(self) -> None:
        # 1. Create Portfolio with initial holdings
        payload = {
            "name": "Cartera Crecimiento 2026",
            "cash_balance_ars": 100000.0,
            "cash_balance_usd": 500.0,
            "holdings": [
                {
                    "ticker": "AAPL",
                    "quantity": 10.0,
                    "average_buy_price": 1200.0,
                    "current_price": 1350.0,
                    "currency": "ARS",
                    "asset_type": "CEDEAR",
                    "sector": "TECHNOLOGY",
                },
                {
                    "ticker": "AL30",
                    "quantity": 500.0,
                    "average_buy_price": 280.0,
                    "current_price": 320.0,
                    "currency": "ARS",
                    "asset_type": "BOND_SOVEREIGN",
                    "sector": "GOVERNMENT",
                },
            ],
        }
        res_create = await self.client.post(
            "/api/v1/portfolios", json=payload, headers=self.auth_headers
        )
        self.assertEqual(res_create.status_code, 201)
        data = res_create.json()
        port_id = data["id"]
        self.assertEqual(data["name"], "Cartera Crecimiento 2026")
        self.assertEqual(data["user_id"], str(self.trader_a.id))
        self.assertEqual(data["holdings_count"], 2)
        self.assertGreater(data["total_market_value_ars"], 0)

        # 2. List Portfolios
        res_list = await self.client.get("/api/v1/portfolios", headers=self.auth_headers)
        self.assertEqual(res_list.status_code, 200)
        port_list = res_list.json()
        self.assertEqual(len(port_list), 1)
        self.assertEqual(port_list[0]["id"], port_id)

        # 3. Get Details
        res_get = await self.client.get(f"/api/v1/portfolios/{port_id}", headers=self.auth_headers)
        self.assertEqual(res_get.status_code, 200)
        port_details = res_get.json()
        self.assertEqual(len(port_details["holdings"]), 2)
        self.assertIn("weight_pct", port_details["holdings"][0])

        # 4. Delete Portfolio
        res_del = await self.client.delete(
            f"/api/v1/portfolios/{port_id}", headers=self.auth_headers
        )
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["status"], "deleted")

        # 5. Verify 404
        res_not_found = await self.client.get(
            f"/api/v1/portfolios/{port_id}", headers=self.auth_headers
        )
        self.assertEqual(res_not_found.status_code, 404)

    async def test_holdings_endpoints(self) -> None:
        # Create empty portfolio
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Trading", "cash_balance_ars": 200000.0},
            headers=self.auth_headers,
        )
        port_id = p_res.json()["id"]

        # Add Holding (GGAL)
        holding_payload = {
            "ticker": "GGAL",
            "quantity": 100.0,
            "average_buy_price": 1850.0,
            "current_price": 2100.0,
            "currency": "ARS",
            "asset_type": "EQUITY",
            "sector": "FINANCIAL_SERVICES",
        }
        res_add = await self.client.post(
            f"/api/v1/portfolios/{port_id}/holdings",
            json=holding_payload,
            headers=self.auth_headers,
        )
        self.assertEqual(res_add.status_code, 201)
        h_data = res_add.json()
        holding_id = h_data["id"]
        self.assertEqual(h_data["asset_ticker"], "GGAL")
        self.assertEqual(h_data["quantity"], 100.0)
        self.assertEqual(h_data["unrealized_pnl"], (2100.0 - 1850.0) * 100.0)

        # Delete Holding
        res_del_h = await self.client.delete(
            f"/api/v1/portfolios/{port_id}/holdings/{holding_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res_del_h.status_code, 200)
        self.assertEqual(res_del_h.json()["status"], "deleted")

        # Verify holding removed
        p_updated = await self.client.get(
            f"/api/v1/portfolios/{port_id}", headers=self.auth_headers
        )
        self.assertEqual(p_updated.json()["holdings_count"], 0)

    async def test_csv_upload_import(self) -> None:
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Ingesta", "cash_balance_ars": 50000.0},
            headers=self.auth_headers,
        )
        port_id = p_res.json()["id"]

        csv_content = (
            "Ticker,Cantidad,Precio Compra,Precio Actual,Moneda\n"
            "MSFT,5,2400.00,2650.00,USD\n"
            "GD30,300,310.00,335.00,ARS\n"
        )
        files = {
            "file": ("balanz_reporte.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
        }
        upload_res = await self.client.post(
            f"/api/v1/portfolios/{port_id}/upload",
            files=files,
            headers=self.auth_headers,
        )
        self.assertEqual(upload_res.status_code, 200)
        report_data = upload_res.json()
        self.assertEqual(report_data["total_rows"], 2)
        self.assertEqual(report_data["valid_records_count"], 2)
        self.assertEqual(report_data["discarded_records_count"], 0)
        self.assertTrue(report_data["is_successful"])

        # Check that holdings were persisted
        port_get = await self.client.get(f"/api/v1/portfolios/{port_id}", headers=self.auth_headers)
        port_data = port_get.json()
        self.assertEqual(port_data["holdings_count"], 2)
        tickers = [h["asset_ticker"] for h in port_data["holdings"]]
        self.assertIn("MSFT", tickers)
        self.assertIn("GD30", tickers)

    async def test_risk_evaluation_endpoint(self) -> None:
        # Create portfolio with an extreme single asset concentration
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={
                "name": "Cartera Concentrada",
                "cash_balance_ars": 1000.0,
                "holdings": [
                    {
                        "ticker": "TSLA",
                        "quantity": 100.0,
                        "average_buy_price": 2000.0,
                        "current_price": 2200.0,
                        "currency": "ARS",
                        "asset_type": "CEDEAR",
                        "sector": "CONSUMER_CYCLICAL",
                    }
                ],
            },
            headers=self.auth_headers,
        )
        port_id = p_res.json()["id"]

        res_eval = await self.client.get(
            f"/api/v1/portfolios/{port_id}/evaluate?fx_ccl=1300.0",
            headers=self.auth_headers,
        )
        self.assertEqual(res_eval.status_code, 200)
        eval_data = res_eval.json()

        self.assertEqual(eval_data["portfolio_id"], port_id)
        self.assertIsNotNone(eval_data["snapshot_id"])
        self.assertGreater(eval_data["total_rules_evaluated"], 0)
        # Because TSLA is >99% of portfolio, concentration rule will flag WARNING or NON_COMPLIANT
        self.assertIn(eval_data["compliance_status"], ["WARNING", "NON_COMPLIANT"])

    async def test_rebalancing_endpoint(self) -> None:
        # Create portfolio with TSLA holding
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={
                "name": "Cartera Para Rebalanceo",
                "cash_balance_ars": 50000.0,
                "holdings": [
                    {
                        "ticker": "TSLA",
                        "quantity": 100.0,
                        "average_buy_price": 1000.0,
                        "current_price": 1000.0,
                        "currency": "ARS",
                        "asset_type": "CEDEAR",
                    }
                ],
            },
            headers=self.auth_headers,
        )
        port_id = p_res.json()["id"]

        # Target TSLA 20% (current is ~66.7%), should generate SELL order
        rebalance_payload = {
            "targets": [
                {
                    "ticker": "TSLA",
                    "target_weight": 20.0,
                    "tolerance_band": 5.0,
                }
            ],
            "fx_ccl": 1300.0,
        }
        res_rebalance = await self.client.post(
            f"/api/v1/portfolios/{port_id}/rebalance",
            json=rebalance_payload,
            headers=self.auth_headers,
        )
        self.assertEqual(res_rebalance.status_code, 200)
        plan_data = res_rebalance.json()

        self.assertEqual(plan_data["portfolio_id"], port_id)
        self.assertEqual(len(plan_data["orders"]), 1)
        order = plan_data["orders"][0]
        self.assertEqual(order["ticker"], "TSLA")
        self.assertEqual(order["side"], "SELL")
        self.assertGreater(order["estimated_shares"], 0)
        self.assertTrue(plan_data["is_liquidity_sufficient"])

    async def test_portfolio_update_investor_profile(self) -> None:
        # Create portfolio with default MODERATE profile
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Perfil Test", "investor_profile": "MODERATE"},
            headers=self.auth_headers,
        )
        self.assertEqual(p_res.status_code, 201)
        port_id = p_res.json()["id"]
        self.assertEqual(p_res.json()["investor_profile"], "MODERATE")

        # Update to CONSERVATIVE
        patch_res = await self.client.patch(
            f"/api/v1/portfolios/{port_id}",
            json={"investor_profile": "CONSERVATIVE"},
            headers=self.auth_headers,
        )
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.json()["investor_profile"], "CONSERVATIVE")

        # Verify persistence with GET
        get_res = await self.client.get(f"/api/v1/portfolios/{port_id}", headers=self.auth_headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["investor_profile"], "CONSERVATIVE")

        # Update to AGGRESSIVE
        patch_res2 = await self.client.patch(
            f"/api/v1/portfolios/{port_id}",
            json={"investor_profile": "AGGRESSIVE"},
            headers=self.auth_headers,
        )
        self.assertEqual(patch_res2.status_code, 200)
        self.assertEqual(patch_res2.json()["investor_profile"], "AGGRESSIVE")

    async def test_validation_error_envelope_integration(self) -> None:
        """Valida que los errores de validación 422 retornen el envelope canónico APIErrorResponse (ARQ-02)."""
        bad_payload = {
            "name": "Cartera Inválida",
            "forbidden_extra_attribute": "hack",
        }
        res = await self.client.post(
            "/api/v1/portfolios",
            json=bad_payload,
            headers={**self.auth_headers, "X-Request-ID": "req-trace-422-test"},
        )
        self.assertEqual(res.status_code, 422)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("Error de validación", body["error"]["message"])
        self.assertEqual(body["meta"]["request_id"], "req-trace-422-test")
        self.assertIn("timestamp", body["meta"])
        self.assertTrue(len(body["error"]["details"]) > 0)
        self.assertTrue(
            any(
                "forbidden_extra_attribute" in str(d.get("field")) for d in body["error"]["details"]
            )
        )

    # -------------------------------------------------------------------------
    # Pruebas Adversariales de Seguridad, RBAC y Aislamiento Anti-IDOR/BOLA (SEC-03)
    # -------------------------------------------------------------------------

    async def test_unauthenticated_request_rejected_401(self) -> None:
        """
        Certifica que peticiones sin header Authorization (o solo con el obsoleto X-User-Id)
        a /portfolios u /orders retornen 401 Unauthorized dentro del APIErrorResponse envelope.
        """
        res_portfolios = await self.client.get("/api/v1/portfolios")
        self.assertEqual(res_portfolios.status_code, 401)
        body_p = res_portfolios.json()
        self.assertFalse(body_p["success"])
        self.assertEqual(body_p["error"]["code"], "UNAUTHORIZED")
        self.assertIn("Not authenticated", body_p["error"]["message"])
        self.assertIn("request_id", body_p["meta"])

        res_orders = await self.client.get("/api/v1/orders")
        self.assertEqual(res_orders.status_code, 401)
        body_o = res_orders.json()
        self.assertFalse(body_o["success"])
        self.assertEqual(body_o["error"]["code"], "UNAUTHORIZED")

        # Verificar que enviar el obsoleto X-User-Id sin Bearer token sea igualmente rechazado con 401
        res_legacy_spoof = await self.client.get(
            "/api/v1/portfolios",
            headers={"X-User-Id": str(self.trader_a.id)},
        )
        self.assertEqual(res_legacy_spoof.status_code, 401)

    async def test_idor_bola_portfolio_isolation_404(self) -> None:
        """
        Certifica aislamiento Anti-IDOR/BOLA: Usuario B (TRADER) intenta leer, modificar,
        eliminar o rebalancear la cartera creada por Usuario A (TRADER) y recibe 404 Not Found.
        """
        # Usuario A crea su cartera
        create_res = await self.client.post(
            "/api/v1/portfolios",
            json={
                "name": "Cartera Privada Trader A",
                "cash_balance_ars": 500000.0,
                "holdings": [
                    {
                        "ticker": "AAPL",
                        "quantity": 50.0,
                        "average_buy_price": 1500.0,
                        "current_price": 1600.0,
                        "currency": "ARS",
                        "asset_type": "CEDEAR",
                    }
                ],
            },
            headers=self.auth_headers,
        )
        self.assertEqual(create_res.status_code, 201)
        port_a_id = create_res.json()["id"]

        # 1. Usuario B intenta leer la cartera de Usuario A -> 404 Not Found
        res_get_b = await self.client.get(
            f"/api/v1/portfolios/{port_a_id}",
            headers=self.trader_b_headers,
        )
        self.assertEqual(res_get_b.status_code, 404)
        self.assertEqual(res_get_b.json()["error"]["message"], "Portfolio not found")

        # 2. Usuario B intenta listar carteras -> no debe ver la de Usuario A
        res_list_b = await self.client.get(
            "/api/v1/portfolios",
            headers=self.trader_b_headers,
        )
        self.assertEqual(res_list_b.status_code, 200)
        self.assertEqual(len(res_list_b.json()), 0)

        # 3. Usuario B intenta rebalancear la cartera de Usuario A -> 404 Not Found
        res_reb_b = await self.client.post(
            f"/api/v1/portfolios/{port_a_id}/rebalance",
            json={
                "targets": [{"ticker": "AAPL", "target_weight": 50.0, "tolerance_band": 5.0}],
                "fx_ccl": 1300.0,
            },
            headers=self.trader_b_headers,
        )
        self.assertEqual(res_reb_b.status_code, 404)
        self.assertEqual(res_reb_b.json()["error"]["message"], "Portfolio not found")

        # 4. Usuario B intenta eliminar la cartera de Usuario A -> 404 Not Found
        res_del_b = await self.client.delete(
            f"/api/v1/portfolios/{port_a_id}",
            headers=self.trader_b_headers,
        )
        self.assertEqual(res_del_b.status_code, 404)

    async def test_idor_bola_order_submission_on_foreign_portfolio_404(self) -> None:
        """
        Certifica aislamiento Anti-IDOR/BOLA en órdenes: Usuario B (TRADER) intenta crear
        o consultar una orden sobre el portfolio_id del Usuario A y recibe 404 Not Found.
        """
        # Usuario A crea su cartera
        create_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Ordenes Trader A", "cash_balance_ars": 250000.0},
            headers=self.auth_headers,
        )
        self.assertEqual(create_res.status_code, 201)
        port_a_id = create_res.json()["id"]

        # Usuario B intenta enviar una orden sobre la cartera de Usuario A -> 404 Not Found
        foreign_order_res = await self.client.post(
            "/api/v1/orders",
            json={
                "portfolio_id": port_a_id,
                "ticker": "GGAL",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 100.0,
                "price": 2100.0,
                "currency": "ARS",
            },
            headers=self.trader_b_headers,
        )
        self.assertEqual(foreign_order_res.status_code, 404)
        self.assertEqual(foreign_order_res.json()["error"]["message"], "Portfolio not found")

        # Usuario A crea una orden legítima sobre su propia cartera -> 201 Created
        own_order_res = await self.client.post(
            "/api/v1/orders",
            json={
                "portfolio_id": port_a_id,
                "ticker": "GGAL",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": 100.0,
                "price": 2100.0,
                "currency": "ARS",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(own_order_res.status_code, 201)
        order_id = own_order_res.json()["id"]

        # Usuario B intenta consultar la orden de Usuario A -> 404 Not Found ("Order not found")
        get_foreign_order = await self.client.get(
            f"/api/v1/orders/{order_id}",
            headers=self.trader_b_headers,
        )
        self.assertEqual(get_foreign_order.status_code, 404)
        self.assertEqual(get_foreign_order.json()["error"]["message"], "Order not found")

    async def test_rbac_viewer_blocked_from_mutations_403(self) -> None:
        """
        Certifica control RBAC: un usuario con rol VIEWER puede hacer GET de su cartera,
        pero al intentar crear una cartera, enviar una orden o ejecutar un rebalanceo recibe 403 Forbidden.
        """
        # Sembrar una cartera asignada al usuario VIEWER para pruebas de lectura vs mutación
        viewer_port_id = str(uuid.uuid4())
        async with self.SessionLocal() as session:
            viewer_portfolio = PortfolioModel(
                id=viewer_port_id,
                user_id=str(self.viewer_user.id),
                name="Cartera Solo Lectura Viewer",
                investor_profile="CONSERVATIVE",
                cash_balance_ars=100000.0,
                cash_balance_usd=0.0,
            )
            session.add(viewer_portfolio)
            await session.commit()

        # 1. VIEWER puede consultar (GET) su propia cartera -> 200 OK
        res_get = await self.client.get(
            f"/api/v1/portfolios/{viewer_port_id}",
            headers=self.viewer_headers,
        )
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["id"], viewer_port_id)

        # 2. VIEWER intenta crear una nueva cartera -> 403 Forbidden
        res_create = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Intento Creacion Viewer", "cash_balance_ars": 10000.0},
            headers=self.viewer_headers,
        )
        self.assertEqual(res_create.status_code, 403)
        self.assertEqual(
            res_create.json()["error"]["message"],
            "Operation not permitted. Insufficient permissions",
        )

        # 3. VIEWER intenta enviar una orden -> 403 Forbidden
        res_order = await self.client.post(
            "/api/v1/orders",
            json={
                "portfolio_id": viewer_port_id,
                "ticker": "AL30",
                "side": "BUY",
                "order_type": "MARKET",
                "quantity": 10.0,
            },
            headers=self.viewer_headers,
        )
        self.assertEqual(res_order.status_code, 403)

        # 4. VIEWER intenta ejecutar un rebalanceo -> 403 Forbidden
        res_rebalance = await self.client.post(
            f"/api/v1/portfolios/{viewer_port_id}/rebalance",
            json={
                "targets": [{"ticker": "AL30", "target_weight": 100.0, "tolerance_band": 5.0}],
                "fx_ccl": 1300.0,
            },
            headers=self.viewer_headers,
        )
        self.assertEqual(res_rebalance.status_code, 403)

    async def test_rbac_admin_cross_tenant_visibility(self) -> None:
        """
        Certifica visibilidad cross-tenant para rol ADMIN: puede consultar válidamente
        la cartera creada por el Usuario A (TRADER).
        """
        create_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Auditada por Admin", "cash_balance_ars": 750000.0},
            headers=self.auth_headers,
        )
        self.assertEqual(create_res.status_code, 201)
        port_a_id = create_res.json()["id"]

        # ADMIN consulta la cartera de Trader A por ID -> 200 OK
        res_admin_get = await self.client.get(
            f"/api/v1/portfolios/{port_a_id}",
            headers=self.admin_headers,
        )
        self.assertEqual(res_admin_get.status_code, 200)
        admin_view = res_admin_get.json()
        self.assertEqual(admin_view["id"], port_a_id)
        self.assertEqual(admin_view["user_id"], str(self.trader_a.id))

        # ADMIN lista todas las carteras del sistema -> incluye la de Trader A
        res_admin_list = await self.client.get(
            "/api/v1/portfolios",
            headers=self.admin_headers,
        )
        self.assertEqual(res_admin_list.status_code, 200)
        ids_in_list = [p["id"] for p in res_admin_list.json()]
        self.assertIn(port_a_id, ids_in_list)


if __name__ == "__main__":
    unittest.main()
