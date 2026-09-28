import datetime as dt
import unittest
from typing import Dict, List, Tuple
import numpy as np

from app.domain.models.order import OrderState
from app.domain.services.backtest_engine import BacktestEngine
from app.schemas.backtest import (
    BacktestConfig,
    BacktestFrictionConfig,
    BacktestResult,
    RebalanceFrequency,
)


def _generate_synthetic_market_data(
    start_date: dt.date,
    n_days: int = 252,
) -> Tuple[List[dt.date], Dict[str, Dict[dt.date, float]]]:
    """Genera series históricas sintéticas deterministas para pruebas de integración."""
    np.random.seed(42)
    dates: List[dt.date] = []
    curr = start_date
    while len(dates) < n_days:
        if curr.weekday() < 5:
            dates.append(curr)
        curr += dt.timedelta(days=1)

    p_aapl = 150.0   # CEDEAR
    p_ggal = 2500.0  # Renta variable local
    p_al30 = 55.0    # Bono soberano

    prices: Dict[str, Dict[dt.date, float]] = {"AAPL": {}, "GGAL": {}, "AL30": {}}

    for d in dates:
        p_aapl *= (1.0 + float(np.random.normal(0.0006, 0.012)))
        p_ggal *= (1.0 + float(np.random.normal(0.0008, 0.022)))
        p_al30 *= (1.0 + float(np.random.normal(0.0003, 0.006)))

        prices["AAPL"][d] = round(p_aapl, 2)
        prices["GGAL"][d] = round(p_ggal, 2)
        prices["AL30"][d] = round(p_al30, 2)

    return dates, prices


class TestBacktestEngineIntegration(unittest.TestCase):
    """
    Pruebas de integración del motor de simulación histórica (BacktestEngine).
    Valida la orquestación integral de optimización, ciclo de órdenes FSM y fricciones de mercado.
    """

    @classmethod
    def setUpClass(cls):
        cls.start_date = dt.date(2024, 1, 2)
        cls.trading_dates, cls.prices_data = _generate_synthetic_market_data(
            start_date=cls.start_date,
            n_days=252,
        )
        cls.end_date = cls.trading_dates[-1]

    def test_full_backtest_monthly_rebalance(self):
        """Ejecuta una simulación completa a 1 año con rebalanceo mensual."""
        config = BacktestConfig(
            initial_capital=500_000.0,
            tickers=["AAPL", "GGAL", "AL30"],
            start_date=self.start_date,
            end_date=self.end_date,
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            risk_free_rate=0.04,
            optimization_method="MINIMUM_VARIANCE",
        )

        engine = BacktestEngine(config=config)
        result = engine.run(prices_data=self.prices_data)

        self.assertIsInstance(result, BacktestResult)
        # 1. Snapshots diarios
        self.assertEqual(len(result.snapshots), len(self.trading_dates))
        self.assertEqual(result.snapshots[0].date, self.start_date)
        self.assertEqual(result.snapshots[-1].date, self.end_date)

        # 2. Métricas de rendimiento válidas y finitas
        m = result.metrics
        self.assertTrue(np.isfinite(m.total_return))
        self.assertTrue(np.isfinite(m.cagr))
        self.assertGreater(m.annualized_volatility, 0.0)
        self.assertTrue(np.isfinite(m.sharpe_ratio))
        self.assertTrue(np.isfinite(m.sortino_ratio))
        self.assertGreaterEqual(m.max_drawdown, 0.0)
        self.assertTrue(np.isfinite(m.calmar_ratio))
        self.assertGreater(m.total_frictions, 0.0)

        # 3. Órdenes ejecutadas mediante FSM
        self.assertGreater(len(result.orders), 0)
        for ord_dict in result.orders:
            self.assertIn(ord_dict["state"], {OrderState.FILLED.value, OrderState.REJECTED.value})
            if ord_dict["state"] == OrderState.FILLED.value:
                self.assertGreater(ord_dict["filled_quantity"], 0.0)
                self.assertIsNotNone(ord_dict["filled_avg_price"])

        # 4. Consistencia del NAV final
        last_snapshot = result.snapshots[-1]
        self.assertGreater(last_snapshot.portfolio_value, 0.0)
        self.assertGreaterEqual(last_snapshot.cash, 0.0)

    def test_frictions_impact_on_portfolio_nav(self):
        """Verifica que las fricciones reduzcan deterministamente el NAV final."""
        # 1. Configuración con costos y comisiones de mercado
        config_with_frictions = BacktestConfig(
            initial_capital=300_000.0,
            tickers=["AAPL", "AL30"],
            start_date=self.start_date,
            end_date=self.end_date,
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            friction_config=BacktestFrictionConfig(
                alyc_commission_rate=0.01,  # 1%
                min_commission_fee=50.0,
                market_fee_rate=0.002,     # 0.20%
                slippage_rate=0.003,       # 0.30%
            ),
        )

        # 2. Configuración con fricciones cero (mercado perfecto teórico)
        config_zero_frictions = BacktestConfig(
            initial_capital=300_000.0,
            tickers=["AAPL", "AL30"],
            start_date=self.start_date,
            end_date=self.end_date,
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            friction_config=BacktestFrictionConfig(
                alyc_commission_rate=0.0,
                min_commission_fee=0.0,
                market_fee_rate=0.0,
                slippage_rate=0.0,
                include_vat=False,
            ),
        )

        res_fric = BacktestEngine(config_with_frictions).run(self.prices_data)
        res_zero = BacktestEngine(config_zero_frictions).run(self.prices_data)

        # Las fricciones acumuladas deben ser mayores en el escenario real
        self.assertGreater(res_fric.metrics.total_frictions, 0.0)
        self.assertEqual(res_zero.metrics.total_frictions, 0.0)

        # El valor final de cartera sin fricciones debe superar al valor con fricciones
        final_nav_fric = res_fric.snapshots[-1].portfolio_value
        final_nav_zero = res_zero.snapshots[-1].portfolio_value
        self.assertGreater(final_nav_zero, final_nav_fric)

    def test_rebalance_frequency_order_counts(self):
        """Valida que una mayor frecuencia de rebalanceo genere más órdenes y turnover."""
        config_weekly = BacktestConfig(
            initial_capital=200_000.0,
            tickers=["AAPL", "GGAL"],
            start_date=self.start_date,
            end_date=self.end_date,
            rebalance_frequency=RebalanceFrequency.WEEKLY,
        )
        config_quarterly = BacktestConfig(
            initial_capital=200_000.0,
            tickers=["AAPL", "GGAL"],
            start_date=self.start_date,
            end_date=self.end_date,
            rebalance_frequency=RebalanceFrequency.QUARTERLY,
        )

        res_weekly = BacktestEngine(config_weekly).run(self.prices_data)
        res_quarterly = BacktestEngine(config_quarterly).run(self.prices_data)

        self.assertGreater(len(res_weekly.orders), len(res_quarterly.orders))

    def test_risk_parity_and_equal_weights_methods(self):
        """Valida la ejecución con optimización Risk Parity y fallback Equiponderado."""
        for method in ["RISK_PARITY", "EQUAL_WEIGHTS"]:
            config = BacktestConfig(
                initial_capital=200_000.0,
                tickers=["AAPL", "GGAL", "AL30"],
                start_date=self.start_date,
                end_date=self.end_date,
                rebalance_frequency=RebalanceFrequency.MONTHLY,
                optimization_method=method,
            )
            res = BacktestEngine(config).run(self.prices_data)
            self.assertGreater(len(res.snapshots), 0)
            self.assertTrue(np.isfinite(res.metrics.cagr))

    def test_missing_data_forward_fill_resilience(self):
        """Valida que el motor no falle si un ticker tiene precios faltantes en varios días."""
        corrupted_prices = {
            "AAPL": dict(self.prices_data["AAPL"]),
            "GGAL": dict(self.prices_data["GGAL"]),
        }
        # Eliminar los primeros 30 días de GGAL (simulando IPO o incorporación tardía)
        for d in self.trading_dates[:30]:
            if d in corrupted_prices["GGAL"]:
                del corrupted_prices["GGAL"][d]

        config = BacktestConfig(
            initial_capital=150_000.0,
            tickers=["AAPL", "GGAL"],
            start_date=self.start_date,
            end_date=self.end_date,
            rebalance_frequency=RebalanceFrequency.MONTHLY,
        )
        res = BacktestEngine(config).run(corrupted_prices)
        self.assertEqual(len(res.snapshots), len(self.trading_dates))
        self.assertTrue(np.isfinite(res.metrics.total_return))


if __name__ == "__main__":
    unittest.main()
