import math
import unittest
import numpy as np
from app.domain.models.metrics import (
    QuantitativeRiskSummary,
    log_returns,
    max_drawdown,
    parametric_var,
    portfolio_volatility,
    realized_volatility,
    sharpe_ratio,
    sortino_ratio,
)


class TestQuantitativeMetrics(unittest.TestCase):
    def test_log_returns_standard(self):
        prices = [100.0, 110.0, 121.0]
        returns = log_returns(prices)
        self.assertEqual(len(returns), 2)
        expected = np.array([np.log(1.1), np.log(1.1)])
        np.testing.assert_allclose(returns, expected, rtol=1e-5)

    def test_log_returns_edge_cases(self):
        self.assertEqual(len(log_returns([100.0])), 0)
        self.assertEqual(len(log_returns([])), 0)
        self.assertEqual(len(log_returns([100.0, -10.0, 110.0])), 0)
        self.assertEqual(len(log_returns([100.0, 0.0, 110.0])), 0)

    def test_realized_volatility_standard(self):
        rets = [0.01, -0.01, 0.02, -0.02]
        vol = realized_volatility(rets, trading_days=252)
        sample_std = float(np.std(rets, ddof=1))
        expected_vol = sample_std * math.sqrt(252)
        self.assertAlmostEqual(vol, expected_vol, places=5)

    def test_realized_volatility_safeguards(self):
        self.assertEqual(realized_volatility([0.05]), 0.0)
        self.assertEqual(realized_volatility([]), 0.0)
        self.assertEqual(realized_volatility([0.02, 0.02, 0.02]), 0.0)
        self.assertEqual(realized_volatility([0.01, -0.01], trading_days=0), 0.0)

    def test_portfolio_volatility_matrix(self):
        weights = [0.6, 0.4]
        cov = np.array([
            [0.0004, 0.0001],
            [0.0001, 0.0009],
        ])
        expected_var = 0.000336
        expected_vol = math.sqrt(expected_var) * math.sqrt(252)
        vol = portfolio_volatility(weights, cov, trading_days=252)
        self.assertAlmostEqual(vol, expected_vol, places=5)

    def test_portfolio_volatility_dimension_mismatch(self):
        weights = [0.5, 0.3, 0.2]
        cov = np.array([
            [0.04, 0.01],
            [0.01, 0.04],
        ])
        self.assertEqual(portfolio_volatility(weights, cov), 0.0)
        self.assertEqual(portfolio_volatility([], np.array([[]])), 0.0)

    def test_sharpe_ratio_standard_and_negative(self):
        rets = [0.01, 0.02, -0.005, 0.015, 0.008]
        sr = sharpe_ratio(rets, risk_free_rate=0.0, trading_days=252)
        ann_return = float(np.mean(rets)) * 252
        vol = realized_volatility(rets, trading_days=252)
        self.assertAlmostEqual(sr, ann_return / vol, places=5)

        sr_high_rf = sharpe_ratio(rets, risk_free_rate=10.0, trading_days=252)
        self.assertLess(sr_high_rf, 0.0)

    def test_sharpe_ratio_safeguards(self):
        self.assertEqual(sharpe_ratio([0.05]), 0.0)
        self.assertEqual(sharpe_ratio([0.01, 0.01, 0.01]), 0.0)

    def test_sortino_ratio_standard(self):
        rets = [0.03, -0.01, 0.02, -0.02, 0.015]
        sortino = sortino_ratio(rets, risk_free_rate=0.0, trading_days=252)
        downside = [min(r, 0.0) for r in rets]
        downside_var = float(np.mean([d**2 for d in downside]))
        downside_vol_ann = math.sqrt(downside_var) * math.sqrt(252)
        expected_sortino = (float(np.mean(rets)) * 252) / downside_vol_ann
        self.assertAlmostEqual(sortino, expected_sortino, places=5)

    def test_sortino_ratio_safeguards(self):
        self.assertEqual(sortino_ratio([0.01, 0.02, 0.03]), 0.0)
        self.assertEqual(sortino_ratio([0.01]), 0.0)

    def test_max_drawdown_standard(self):
        nav = [100.0, 120.0, 90.0, 110.0, 80.0, 100.0]
        mdd, calmar = max_drawdown(nav, trading_days=252)
        self.assertAlmostEqual(mdd, -1.0 / 3.0, places=5)
        self.assertAlmostEqual(calmar, 0.0, places=5)

    def test_max_drawdown_strictly_increasing(self):
        nav = [100.0, 110.0, 125.0, 140.0]
        mdd, calmar = max_drawdown(nav)
        self.assertEqual(mdd, 0.0)
        self.assertEqual(calmar, 0.0)

    def test_max_drawdown_edge_cases(self):
        self.assertEqual(max_drawdown([100.0]), (0.0, 0.0))
        self.assertEqual(max_drawdown([]), (0.0, 0.0))
        self.assertEqual(max_drawdown([100.0, -10.0, 50.0]), (0.0, 0.0))

    def test_parametric_var_standard(self):
        rets = [0.01, -0.015, 0.02, -0.025, 0.012, -0.008]
        var_95 = parametric_var(rets, confidence=0.95)
        mu = float(np.mean(rets))
        sigma = float(np.std(rets, ddof=1))
        z_95 = 1.6448536269514722
        expected_var = (z_95 * sigma) - mu
        self.assertAlmostEqual(var_95, expected_var, places=5)

    def test_parametric_var_safeguards(self):
        self.assertEqual(parametric_var([0.01, -0.01], confidence=1.5), 0.0)
        self.assertEqual(parametric_var([0.01, -0.01], confidence=0.0), 0.0)
        self.assertEqual(parametric_var([0.01]), 0.0)
        self.assertEqual(parametric_var([0.01, 0.01, 0.01]), 0.0)

    def test_quantitative_risk_summary(self):
        prices = [100.0, 102.0, 99.0, 105.0, 103.0, 108.0]
        rets = log_returns(prices)
        summary = QuantitativeRiskSummary.from_returns_and_nav(
            returns=rets,
            nav_series=prices,
            risk_free_rate=0.02,
            trading_days=252,
        )
        self.assertIsInstance(summary.realized_volatility, float)
        self.assertIsInstance(summary.sharpe_ratio, float)
        self.assertIsInstance(summary.sortino_ratio, float)
        self.assertIsInstance(summary.max_drawdown, float)
        self.assertIsInstance(summary.calmar_ratio, float)
        self.assertIsInstance(summary.parametric_var_95, float)
        self.assertLessEqual(summary.max_drawdown, 0.0)


if __name__ == "__main__":
    unittest.main()
