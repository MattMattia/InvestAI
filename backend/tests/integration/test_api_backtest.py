import unittest
from fastapi.testclient import TestClient

from app.main import app


class TestApiBacktestIntegration(unittest.TestCase):
    """
    Pruebas de integración para el endpoint REST de Backtesting (/api/v1/backtest/run).
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_run_backtest_endpoint_success(self):
        """Valida la ejecución exitosa de un backtest con precios generados automáticamente (GBM)."""
        payload = {
            "initial_capital": 300_000.0,
            "tickers": ["AAPL", "GGAL", "AL30"],
            "start_date": "2024-01-02",
            "end_date": "2024-12-31",
            "rebalance_frequency": "MONTHLY",
            "risk_free_rate": 0.04,
            "optimization_method": "MINIMUM_VARIANCE",
            "friction_config": {
                "alyc_commission_rate": 0.005,
                "min_commission_fee": 10.0,
                "include_vat": True,
                "vat_rate": 0.21,
                "market_fee_rate": 0.0009,
                "slippage_rate": 0.001,
            },
        }

        response = self.client.post("/api/v1/backtest/run", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("config", data)
        self.assertIn("metrics", data)
        self.assertIn("snapshots", data)
        self.assertIn("orders", data)

        # 1. Configuración reflejada
        self.assertEqual(data["config"]["initial_capital"], 300_000.0)
        self.assertEqual(data["config"]["tickers"], ["AAPL", "AL30", "GGAL"])  # Ordenados y normalizados

        # 2. Métricas consolidadas
        metrics = data["metrics"]
        self.assertIn("total_return", metrics)
        self.assertIn("cagr", metrics)
        self.assertIn("annualized_volatility", metrics)
        self.assertIn("sharpe_ratio", metrics)
        self.assertIn("sortino_ratio", metrics)
        self.assertIn("max_drawdown", metrics)
        self.assertIn("calmar_ratio", metrics)
        self.assertIn("total_frictions", metrics)

        self.assertGreater(metrics["annualized_volatility"], 0.0)
        self.assertGreaterEqual(metrics["max_drawdown"], 0.0)
        self.assertGreater(metrics["total_frictions"], 0.0)

        # 3. Snapshots diarios
        self.assertGreater(len(data["snapshots"]), 200)
        first_snap = data["snapshots"][0]
        self.assertEqual(first_snap["date"], "2024-01-02")
        self.assertGreater(first_snap["portfolio_value"], 0.0)

        # 4. Historial de órdenes
        self.assertGreater(len(data["orders"]), 0)
        for order in data["orders"]:
            self.assertIn(order["state"], ["FILLED", "REJECTED"])

    def test_run_backtest_with_custom_prices(self):
        """Valida el endpoint cuando el cliente suministra su propio diccionario de cotizaciones."""
        custom_prices = {
            "AAPL": {
                "2024-01-02": 150.0,
                "2024-01-03": 152.0,
                "2024-01-04": 151.0,
                "2024-01-05": 155.0,
                "2024-01-08": 160.0,
            },
            "GGAL": {
                "2024-01-02": 2000.0,
                "2024-01-03": 2050.0,
                "2024-01-04": 2020.0,
                "2024-01-05": 2100.0,
                "2024-01-08": 2150.0,
            },
        }

        payload = {
            "initial_capital": 100_000.0,
            "tickers": ["AAPL", "GGAL"],
            "start_date": "2024-01-02",
            "end_date": "2024-01-08",
            "rebalance_frequency": "DAILY",
            "custom_prices": custom_prices,
        }

        response = self.client.post("/api/v1/backtest/run", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data["snapshots"]), 5)
        self.assertEqual(data["snapshots"][0]["date"], "2024-01-02")
        self.assertEqual(data["snapshots"][-1]["date"], "2024-01-08")

    def test_run_backtest_invalid_dates_returns_400(self):
        """Valida que un rango de fechas invertido retorne HTTP 400 Bad Request."""
        payload = {
            "initial_capital": 100_000.0,
            "tickers": ["AAPL"],
            "start_date": "2024-12-31",
            "end_date": "2024-01-01",
        }
        response = self.client.post("/api/v1/backtest/run", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("debe ser estrictamente anterior", response.json()["detail"])

    def test_run_backtest_empty_tickers_returns_422(self):
        """Valida que tickers vacíos o inválidos retornen error de validación 422."""
        payload = {
            "initial_capital": 100_000.0,
            "tickers": ["   "],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        }
        response = self.client.post("/api/v1/backtest/run", json=payload)
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
