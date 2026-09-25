import io
import unittest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # Registers all declarative tables first
from app.api.deps import get_db_session
from app.core.database import Base
from app.main import app as fastapi_app


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

        async def _override_get_db():
            async with self.SessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        fastapi_app.dependency_overrides[get_db_session] = _override_get_db
        self.transport = httpx.ASGITransport(app=fastapi_app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        fastapi_app.dependency_overrides.clear()
        await self.engine.dispose()

    async def test_health_and_root(self) -> None:
        root_res = await self.client.get("/")
        self.assertEqual(root_res.status_code, 200)
        self.assertEqual(root_res.json()["status"], "online")

        health_res = await self.client.get("/health")
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.json()["status"], "healthy")

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
        res_create = await self.client.post("/api/v1/portfolios", json=payload)
        self.assertEqual(res_create.status_code, 201)
        data = res_create.json()
        port_id = data["id"]
        self.assertEqual(data["name"], "Cartera Crecimiento 2026")
        self.assertEqual(data["holdings_count"], 2)
        self.assertGreater(data["total_market_value_ars"], 0)

        # 2. List Portfolios
        res_list = await self.client.get("/api/v1/portfolios")
        self.assertEqual(res_list.status_code, 200)
        port_list = res_list.json()
        self.assertEqual(len(port_list), 1)
        self.assertEqual(port_list[0]["id"], port_id)

        # 3. Get Details
        res_get = await self.client.get(f"/api/v1/portfolios/{port_id}")
        self.assertEqual(res_get.status_code, 200)
        port_details = res_get.json()
        self.assertEqual(len(port_details["holdings"]), 2)
        self.assertIn("weight_pct", port_details["holdings"][0])

        # 4. Delete Portfolio
        res_del = await self.client.delete(f"/api/v1/portfolios/{port_id}")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["status"], "deleted")

        # 5. Verify 404
        res_not_found = await self.client.get(f"/api/v1/portfolios/{port_id}")
        self.assertEqual(res_not_found.status_code, 404)

    async def test_holdings_endpoints(self) -> None:
        # Create empty portfolio
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Trading", "cash_balance_ars": 200000.0},
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
            f"/api/v1/portfolios/{port_id}/holdings", json=holding_payload
        )
        self.assertEqual(res_add.status_code, 201)
        h_data = res_add.json()
        holding_id = h_data["id"]
        self.assertEqual(h_data["asset_ticker"], "GGAL")
        self.assertEqual(h_data["quantity"], 100.0)
        self.assertEqual(h_data["unrealized_pnl"], (2100.0 - 1850.0) * 100.0)

        # Delete Holding
        res_del_h = await self.client.delete(
            f"/api/v1/portfolios/{port_id}/holdings/{holding_id}"
        )
        self.assertEqual(res_del_h.status_code, 200)
        self.assertEqual(res_del_h.json()["status"], "deleted")

        # Verify holding removed
        p_updated = await self.client.get(f"/api/v1/portfolios/{port_id}")
        self.assertEqual(p_updated.json()["holdings_count"], 0)

    async def test_csv_upload_import(self) -> None:
        p_res = await self.client.post(
            "/api/v1/portfolios",
            json={"name": "Cartera Ingesta", "cash_balance_ars": 50000.0},
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
            f"/api/v1/portfolios/{port_id}/upload", files=files
        )
        self.assertEqual(upload_res.status_code, 200)
        report_data = upload_res.json()
        self.assertEqual(report_data["total_rows"], 2)
        self.assertEqual(report_data["valid_records_count"], 2)
        self.assertEqual(report_data["discarded_records_count"], 0)
        self.assertTrue(report_data["is_successful"])

        # Check that holdings were persisted
        port_get = await self.client.get(f"/api/v1/portfolios/{port_id}")
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
        )
        port_id = p_res.json()["id"]

        res_eval = await self.client.get(f"/api/v1/portfolios/{port_id}/evaluate?fx_ccl=1300.0")
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
            f"/api/v1/portfolios/{port_id}/rebalance", json=rebalance_payload
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
        )
        self.assertEqual(p_res.status_code, 201)
        port_id = p_res.json()["id"]
        self.assertEqual(p_res.json()["investor_profile"], "MODERATE")

        # Update to CONSERVATIVE
        patch_res = await self.client.patch(
            f"/api/v1/portfolios/{port_id}",
            json={"investor_profile": "CONSERVATIVE"},
        )
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.json()["investor_profile"], "CONSERVATIVE")

        # Verify persistence with GET
        get_res = await self.client.get(f"/api/v1/portfolios/{port_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["investor_profile"], "CONSERVATIVE")

        # Update to AGGRESSIVE
        patch_res2 = await self.client.patch(
            f"/api/v1/portfolios/{port_id}",
            json={"investor_profile": "AGGRESSIVE"},
        )
        self.assertEqual(patch_res2.status_code, 200)
        self.assertEqual(patch_res2.json()["investor_profile"], "AGGRESSIVE")


if __name__ == "__main__":
    unittest.main()
