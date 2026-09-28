import unittest
from datetime import date
import numpy as np
from pydantic import ValidationError

from app.domain.services.backtest_metrics import (
    calculate_annualized_volatility,
    calculate_cagr,
    calculate_calmar_ratio,
    calculate_daily_returns,
    calculate_drawdown_series,
    calculate_max_drawdown,
    calculate_performance_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_total_return,
)
from app.schemas.backtest import (
    BacktestConfig,
    BacktestFrictionConfig,
    BacktestPerformanceMetrics,
    BacktestResult,
    DailySnapshot,
    RebalanceFrequency,
)


class TestBacktestSchemas(unittest.TestCase):
    """Pruebas unitarias para los esquemas Pydantic v2 de backtesting."""

    def test_rebalance_frequency_enum(self):
        self.assertEqual(RebalanceFrequency.DAILY.value, "DAILY")
        self.assertEqual(RebalanceFrequency.WEEKLY.value, "WEEKLY")
        self.assertEqual(RebalanceFrequency.MONTHLY.value, "MONTHLY")
        self.assertEqual(RebalanceFrequency.QUARTERLY.value, "QUARTERLY")

    def test_backtest_config_defaults_and_normalization(self):
        config = BacktestConfig(
            tickers=["  aapl ", "Spy", "aapl  "],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        self.assertEqual(config.initial_capital, 100_000.0)
        self.assertEqual(config.rebalance_frequency, RebalanceFrequency.MONTHLY)
        self.assertEqual(config.risk_free_rate, 0.0)
        # Normalizados y deduplicados
        self.assertEqual(config.tickers, ["AAPL", "SPY"])
        self.assertEqual(config.friction_config.alyc_commission_rate, 0.005)
        self.assertEqual(config.friction_config.vat_rate, 0.21)

    def test_backtest_config_empty_tickers_raises(self):
        with self.assertRaises(ValidationError):
            BacktestConfig(
                tickers=["   "],
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

    def test_backtest_config_frozen_immutability(self):
        config = BacktestConfig(
            tickers=["GGAL"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        with self.assertRaises(ValidationError):
            config.initial_capital = 50_000.0  # type: ignore

    def test_daily_snapshot_schema(self):
        snapshot = DailySnapshot(
            date="2024-01-02",
            portfolio_value=105_000.0,
            cash=15_000.0,
            holdings={"AAPL": 50.0, "SPY": 100.0},
            daily_return=0.05,
            drawdown=0.0,
        )
        self.assertEqual(snapshot.portfolio_value, 105_000.0)
        self.assertEqual(snapshot.holdings["AAPL"], 50.0)
        with self.assertRaises(ValidationError):
            snapshot.cash = 10_000.0  # type: ignore

    def test_backtest_result_schema(self):
        config = BacktestConfig(
            tickers=["AAPL"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        metrics = BacktestPerformanceMetrics(
            total_return=0.15,
            cagr=0.15,
            annualized_volatility=0.18,
            sharpe_ratio=0.83,
            sortino_ratio=1.12,
            max_drawdown=0.08,
            calmar_ratio=1.875,
            total_frictions=350.0,
        )
        result = BacktestResult(
            config=config,
            metrics=metrics,
            snapshots=[],
            orders=[{"id": "ord-1", "ticker": "AAPL", "side": "BUY", "amount": 1000.0}],
        )
        self.assertEqual(result.metrics.sharpe_ratio, 0.83)
        self.assertEqual(len(result.orders), 1)


class TestBacktestMetricsService(unittest.TestCase):
    """Pruebas unitarias para el servicio cuantitativo de métricas de backtesting."""

    def test_calculate_total_return_standard(self):
        # Ganancia del 25%
        self.assertAlmostEqual(calculate_total_return([100.0, 110.0, 125.0]), 0.25)
        # Pérdida del 30%
        self.assertAlmostEqual(calculate_total_return([100.0, 70.0]), -0.30)
        # Quiebra total
        self.assertEqual(calculate_total_return([100.0, 50.0, 0.0]), -1.0)

    def test_calculate_total_return_defensive(self):
        self.assertEqual(calculate_total_return([]), 0.0)
        self.assertEqual(calculate_total_return([100.0]), 0.0)
        self.assertEqual(calculate_total_return([0.0, 100.0]), 0.0)
        self.assertEqual(calculate_total_return([-50.0, 100.0]), 0.0)
        self.assertEqual(calculate_total_return([100.0, np.nan, 120.0]), 0.0)
        self.assertEqual(calculate_total_return([100.0, np.inf]), 0.0)

    def test_calculate_cagr_standard(self):
        # 252 días de trading exactamente, rendimiento del 10%
        # N = 252 transiciones (253 puntos)
        nav = [100.0] * 252 + [110.0]
        self.assertAlmostEqual(calculate_cagr(nav, periods_per_year=252), 0.10, places=5)

        # 504 días (2 años), retorno acumulado de 21% -> CAGR = 10%
        nav_2y = [100.0] * 504 + [121.0]
        self.assertAlmostEqual(calculate_cagr(nav_2y, periods_per_year=252), 0.10, places=5)

    def test_calculate_cagr_defensive(self):
        self.assertEqual(calculate_cagr([]), 0.0)
        self.assertEqual(calculate_cagr([100.0]), 0.0)
        self.assertEqual(calculate_cagr([0.0, 100.0]), 0.0)
        self.assertEqual(calculate_cagr([100.0, 0.0]), -1.0)
        self.assertEqual(calculate_cagr([100.0, -10.0]), -1.0)
        self.assertEqual(calculate_cagr([100.0, np.nan]), 0.0)

    def test_calculate_daily_returns(self):
        nav = [100.0, 105.0, 99.75]
        returns = calculate_daily_returns(nav)
        self.assertEqual(len(returns), 2)
        self.assertAlmostEqual(returns[0], 0.05)
        self.assertAlmostEqual(returns[1], -0.05)

        # Serie insuficiente
        self.assertEqual(len(calculate_daily_returns([100.0])), 0)
        self.assertEqual(len(calculate_daily_returns([])), 0)

    def test_calculate_annualized_volatility(self):
        # Serie con volatilidad nula (retornos constantes)
        returns_flat = [0.01, 0.01, 0.01, 0.01]
        self.assertAlmostEqual(calculate_annualized_volatility(returns_flat), 0.0)

        # Serie con volatilidad conocida
        returns = [0.02, -0.02, 0.02, -0.02]
        vol = calculate_annualized_volatility(returns, periods_per_year=252)
        self.assertGreater(vol, 0.0)

        # Casos defensivos
        self.assertEqual(calculate_annualized_volatility([]), 0.0)
        self.assertEqual(calculate_annualized_volatility([0.05]), 0.0)
        self.assertEqual(calculate_annualized_volatility([0.01, np.nan]), 0.0)

    def test_calculate_sharpe_ratio(self):
        # Retornos diarios positivos y estables
        returns = [0.001, 0.0012, 0.0009, 0.0011, 0.0010] * 20
        sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=252)
        self.assertGreater(sharpe, 0.0)

        # Con tasa libre de riesgo superior al rendimiento de la cartera
        sharpe_rf = calculate_sharpe_ratio(returns, risk_free_rate=0.50, periods_per_year=252)
        self.assertLess(sharpe_rf, 0.0)

        # Volatilidad cero
        self.assertEqual(calculate_sharpe_ratio([0.01, 0.01, 0.01]), 0.0)

        # Casos defensivos
        self.assertEqual(calculate_sharpe_ratio([]), 0.0)
        self.assertEqual(calculate_sharpe_ratio([0.01]), 0.0)
        self.assertEqual(calculate_sharpe_ratio([0.01, np.nan]), 0.0)

    def test_calculate_sortino_ratio(self):
        # Caso puramente alcista (sin retornos negativos bajo rf) -> downside vol = 0 -> sortino protegido = 0.0
        returns_bull = [0.01, 0.02, 0.015, 0.03]
        self.assertEqual(calculate_sortino_ratio(returns_bull, risk_free_rate=0.0), 0.0)

        # Serie mixta con días negativos
        returns_mixed = [0.02, -0.01, 0.015, -0.008, 0.03, -0.012] * 10
        sortino = calculate_sortino_ratio(returns_mixed, risk_free_rate=0.0, periods_per_year=252)
        self.assertGreater(sortino, 0.0)

        # Casos defensivos
        self.assertEqual(calculate_sortino_ratio([]), 0.0)
        self.assertEqual(calculate_sortino_ratio([0.01]), 0.0)
        self.assertEqual(calculate_sortino_ratio([0.01, np.nan]), 0.0)

    def test_calculate_drawdown_series_and_mdd(self):
        # Serie con subidas, caídas y nuevos máximos
        nav = [100.0, 120.0, 90.0, 108.0, 130.0]
        dd = calculate_drawdown_series(nav)
        self.assertEqual(len(dd), 5)
        self.assertAlmostEqual(dd[0], 0.0)
        self.assertAlmostEqual(dd[1], 0.0)
        self.assertAlmostEqual(dd[2], -0.25)  # (90 - 120) / 120 = -0.25
        self.assertAlmostEqual(dd[3], -0.10)  # (108 - 120) / 120 = -0.10
        self.assertAlmostEqual(dd[4], 0.0)

        # Máximo drawdown es 0.25 (25% en valor absoluto positivo)
        mdd = calculate_max_drawdown(nav)
        self.assertAlmostEqual(mdd, 0.25)

    def test_calculate_mdd_edge_cases(self):
        # Serie monótonamente creciente (sin caídas)
        nav_up = [100.0, 110.0, 120.0, 130.0]
        self.assertEqual(calculate_max_drawdown(nav_up), 0.0)

        # Serie plana
        nav_flat = [100.0, 100.0, 100.0]
        self.assertEqual(calculate_max_drawdown(nav_flat), 0.0)

        # Serie monótonamente decreciente
        nav_down = [100.0, 80.0, 60.0]
        self.assertAlmostEqual(calculate_max_drawdown(nav_down), 0.40)

        # Casos defensivos
        self.assertEqual(calculate_max_drawdown([]), 0.0)
        self.assertEqual(calculate_max_drawdown([100.0]), 0.0)
        self.assertEqual(calculate_max_drawdown([100.0, np.nan]), 0.0)

    def test_calculate_calmar_ratio(self):
        # CAGR = 20%, MDD = 25% -> Calmar = 0.80
        self.assertAlmostEqual(calculate_calmar_ratio(0.20, 0.25), 0.80)

        # MDD = 0.0 -> Protección contra división por cero
        self.assertEqual(calculate_calmar_ratio(0.15, 0.0), 0.0)

        # CAGR negativo
        self.assertAlmostEqual(calculate_calmar_ratio(-0.10, 0.20), -0.50)

        # Valores corruptos
        self.assertEqual(calculate_calmar_ratio(np.nan, 0.20), 0.0)
        self.assertEqual(calculate_calmar_ratio(0.20, np.nan), 0.0)

    def test_calculate_performance_metrics_consolidated(self):
        # Simulación de 253 valores diarios
        np.random.seed(42)
        daily_rets = np.random.normal(0.0005, 0.01, 252)
        nav = [100_000.0]
        for r in daily_rets:
            nav.append(nav[-1] * (1.0 + r))

        metrics = calculate_performance_metrics(
            portfolio_values=nav,
            risk_free_rate=0.03,
            total_frictions=1250.75,
            periods_per_year=252,
        )

        self.assertIsInstance(metrics, BacktestPerformanceMetrics)
        self.assertGreater(metrics.annualized_volatility, 0.0)
        self.assertGreater(metrics.max_drawdown, 0.0)
        self.assertEqual(metrics.total_frictions, 1250.75)

    def test_calculate_performance_metrics_flat_series(self):
        nav_flat = [100_000.0] * 50
        metrics = calculate_performance_metrics(nav_flat)
        self.assertEqual(metrics.total_return, 0.0)
        self.assertEqual(metrics.cagr, 0.0)
        self.assertEqual(metrics.annualized_volatility, 0.0)
        self.assertEqual(metrics.sharpe_ratio, 0.0)
        self.assertEqual(metrics.sortino_ratio, 0.0)
        self.assertEqual(metrics.max_drawdown, 0.0)
        self.assertEqual(metrics.calmar_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
