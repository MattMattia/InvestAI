import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from app.domain.services.portfolio_optimizer import (
    calculate_diversification_ratio,
    calculate_portfolio_volatility,
    calculate_risk_contributions,
    minimum_variance_portfolio,
    risk_parity_portfolio,
)
from app.domain.services.quantitative_risk import (
    calculate_cvar,
    calculate_kurtosis,
    calculate_skewness,
    calculate_var,
    ledoit_wolf_covariance,
)
from app.schemas.optimization import (
    OptimizationMethod,
    OptimizationRequest,
    OptimizationResult,
    TailRiskMetrics,
)


class TestQuantitativeRisk(unittest.TestCase):
    def setUp(self) -> None:
        np.random.seed(42)

    def test_ledoit_wolf_ill_conditioned_and_small_t(self) -> None:
        """
        Validates Ledoit-Wolf shrinkage when T < N (rank-deficient sample covariance)
        and with collinear assets.
        """
        # T = 5 observations, N = 8 assets (T < N)
        t_obs = 5
        n_assets = 8
        base_returns = np.random.randn(t_obs, 4)
        # Create collinear assets (duplicates and linear combinations)
        collinear_1 = base_returns[:, 0] * 1.5
        collinear_2 = 0.5 * base_returns[:, 1] + 0.5 * base_returns[:, 2]
        collinear_3 = base_returns[:, 3] + 0.0001 * np.random.randn(t_obs)
        collinear_4 = -base_returns[:, 0]

        returns = np.column_stack(
            [base_returns, collinear_1, collinear_2, collinear_3, collinear_4]
        )
        self.assertEqual(returns.shape, (t_obs, n_assets))

        # Standard sample covariance would be singular / rank deficient (rank <= 4 < 8)
        sample_cov = np.cov(returns, rowvar=False)
        sample_eigvals = np.linalg.eigvalsh(sample_cov)
        self.assertLessEqual(min(sample_eigvals), 1e-10)  # Has 0 or negative eigenvalues

        # Ledoit-Wolf shrinkage must produce a strictly positive-definite and invertible matrix
        shrunk_cov = ledoit_wolf_covariance(returns)

        # 1. Dimensions
        self.assertEqual(shrunk_cov.shape, (n_assets, n_assets))

        # 2. Exact symmetry
        diff_transpose = np.max(np.abs(shrunk_cov - shrunk_cov.T))
        self.assertLess(diff_transpose, 1e-12)

        # 3. Strictly positive eigenvalues
        eigvals = np.linalg.eigvalsh(shrunk_cov)
        self.assertTrue(np.all(eigvals > 1e-7), f"Eigenvalues must be strictly positive: {eigvals}")

        # 4. Invertible without numerical instability
        inv_cov = np.linalg.inv(shrunk_cov)
        identity_test = shrunk_cov @ inv_cov
        diff_identity = np.max(np.abs(identity_test - np.eye(n_assets)))
        self.assertLess(diff_identity, 1e-5)

    def test_ledoit_wolf_single_asset(self) -> None:
        returns = np.array([[0.01], [0.02], [-0.01], [0.03]], dtype=np.float64)
        cov = ledoit_wolf_covariance(returns)
        self.assertEqual(cov.shape, (1, 1))
        self.assertGreater(cov[0, 0], 0.0)

    def test_skewness_calculation(self) -> None:
        # 1. Symmetric normal returns -> skewness ~ 0
        normal_series = np.random.normal(loc=0.001, scale=0.02, size=10000)
        skew_normal = calculate_skewness(normal_series)
        self.assertAlmostEqual(skew_normal, 0.0, delta=0.1)

        # 2. Positively skewed returns (right tail)
        pos_skewed = np.array([-0.01, -0.01, -0.01, -0.01, -0.01, 0.20])
        skew_pos = calculate_skewness(pos_skewed)
        self.assertGreater(skew_pos, 1.0)

        # 3. Negatively skewed returns (left tail, typical financial crash)
        neg_skewed = np.array([0.01, 0.01, 0.01, 0.01, 0.01, -0.20])
        skew_neg = calculate_skewness(neg_skewed)
        self.assertLess(skew_neg, -1.0)

    def test_kurtosis_calculation(self) -> None:
        # Standard normal distribution -> excess kurtosis ~ 0
        normal_series = np.random.normal(loc=0.0, scale=0.01, size=20000)
        kurt_normal = calculate_kurtosis(normal_series)
        self.assertAlmostEqual(kurt_normal, 0.0, delta=0.2)

        # Heavy-tailed distribution (Student's t with df=3) -> high positive excess kurtosis
        t_series = np.random.standard_t(df=3, size=20000) * 0.01
        kurt_heavy = calculate_kurtosis(t_series)
        self.assertGreater(kurt_heavy, 1.5)

    def test_var_and_cvar_properties(self) -> None:
        # Daily return series
        returns = np.random.normal(loc=0.0005, scale=0.02, size=5000)
        alpha = 0.95

        var_hist = calculate_var(returns, alpha=alpha, method="historical")
        var_param = calculate_var(returns, alpha=alpha, method="parametric")
        cvar_hist = calculate_cvar(returns, alpha=alpha)

        # Both VaR and CVaR must be positive loss magnitudes
        self.assertGreater(var_hist, 0.0)
        self.assertGreater(var_param, 0.0)
        self.assertGreater(cvar_hist, 0.0)

        # Theoretical guarantee: CVaR (Expected Shortfall) >= VaR
        self.assertGreaterEqual(cvar_hist, var_hist)

        # Increasing confidence level increases VaR and CVaR
        var_99 = calculate_var(returns, alpha=0.99, method="historical")
        cvar_99 = calculate_cvar(returns, alpha=0.99)
        self.assertGreater(var_99, var_hist)
        self.assertGreater(cvar_99, cvar_hist)


class TestPortfolioOptimizer(unittest.TestCase):
    def setUp(self) -> None:
        # 3 assets: Asset 0 has high volatility (40%), Asset 1 moderate (20%), Asset 2 low (10%)
        # Correlation matrix
        corr = np.array(
            [
                [1.0, 0.3, 0.1],
                [0.3, 1.0, 0.2],
                [0.1, 0.2, 1.0],
            ]
        )
        vols = np.array([0.40, 0.20, 0.10])
        # Covariance matrix = D * R * D
        self.cov = np.outer(vols, vols) * corr

    def test_minimum_variance_portfolio(self) -> None:
        w_gmv = minimum_variance_portfolio(self.cov)

        # 1. Weights sum exactly to 1.0
        self.assertAlmostEqual(float(np.sum(w_gmv)), 1.0, places=5)

        # 2. Long-only constraint: all weights >= 0
        self.assertTrue(np.all(w_gmv >= -1e-8), f"Negative weight detected: {w_gmv}")

        # 3. Minimum variance allocates most weight to lowest variance asset (Asset 2)
        # and least to high volatility asset (Asset 0)
        self.assertGreater(w_gmv[2], w_gmv[1])
        self.assertGreater(w_gmv[1], w_gmv[0])

        # 4. Volatility of GMV must be lower than any individual asset volatility
        vol_gmv = calculate_portfolio_volatility(w_gmv, self.cov, annualized=False)
        self.assertLess(vol_gmv, 0.10)

    def test_risk_parity_portfolio(self) -> None:
        w_rp = risk_parity_portfolio(self.cov)

        # 1. Weights sum to 1.0
        self.assertAlmostEqual(float(np.sum(w_rp)), 1.0, places=5)

        # 2. Long-only: all weights strictly positive
        self.assertTrue(np.all(w_rp > 0.0), f"Risk parity weights must be positive: {w_rp}")

        # 3. Inverse volatility property: more volatile asset gets smaller weight
        # vols are: asset 0 (40%) > asset 1 (20%) > asset 2 (10%)
        # Therefore: w_rp[2] > w_rp[1] > w_rp[0]
        self.assertGreater(w_rp[2], w_rp[1])
        self.assertGreater(w_rp[1], w_rp[0])

        # 4. Equal risk contributions: RC_i = w_i * (cov * w)_i / sigma_p^2 == 1/3
        risk_contribs = calculate_risk_contributions(w_rp, self.cov)
        self.assertAlmostEqual(float(np.sum(risk_contribs)), 1.0, places=4)
        for i in range(len(risk_contribs)):
            self.assertAlmostEqual(risk_contribs[i], 1.0 / 3.0, places=3)

    def test_diversification_ratio(self) -> None:
        w_rp = risk_parity_portfolio(self.cov)
        dr = calculate_diversification_ratio(w_rp, self.cov)
        # When assets are not perfectly correlated, DR > 1.0
        self.assertGreater(dr, 1.0)

    def test_single_asset_portfolio(self) -> None:
        cov_1 = np.array([[0.04]])
        w_gmv = minimum_variance_portfolio(cov_1)
        w_rp = risk_parity_portfolio(cov_1)
        self.assertEqual(list(w_gmv), [1.0])
        self.assertEqual(list(w_rp), [1.0])

    def test_risk_parity_with_zero_variance_asset(self) -> None:
        """[DEFENSE: NUM-01] Valida que activos de varianza cero se aíslen sin divergencia de gradiente -1/y."""
        # Matriz 3x3 donde el activo 2 tiene varianza nula (ej. efectivo sin riesgo)
        cov_zero = np.array(
            [
                [0.04, 0.01, 0.0],
                [0.01, 0.09, 0.0],
                [0.0, 0.0, 0.0],
            ]
        )
        weights = risk_parity_portfolio(cov_zero)
        self.assertAlmostEqual(float(np.sum(weights)), 1.0, places=5)
        self.assertTrue(np.all(np.isfinite(weights)))
        self.assertEqual(weights[2], 0.0)  # Activo sin volatilidad recibe peso 0.0
        self.assertGreater(weights[0], 0.0)
        self.assertGreater(weights[1], 0.0)

    def test_risk_parity_all_zero_variance(self) -> None:
        """[DEFENSE: NUM-01] Valida fallback seguro a equiponderación si todos los activos tienen varianza nula."""
        cov_all_zero = np.zeros((3, 3))
        weights = risk_parity_portfolio(cov_all_zero)
        self.assertTrue(np.all(np.isfinite(weights)))
        np.testing.assert_allclose(weights, [1 / 3, 1 / 3, 1 / 3], atol=1e-5)

    def test_minimum_variance_solver_failure_fallback_on_nan(self) -> None:
        """[DEFENSE: NUM-02] Valida fallback a 1/N si el solver SLSQP devuelve NaNs o falla."""
        fake_result = MagicMock()
        fake_result.success = False
        fake_result.x = np.array([np.nan, 0.5, 0.5])

        with patch("app.domain.services.portfolio_optimizer.minimize", return_value=fake_result):
            weights = minimum_variance_portfolio(self.cov)
            self.assertTrue(np.all(np.isfinite(weights)))
            np.testing.assert_allclose(weights, [1 / 3, 1 / 3, 1 / 3], atol=1e-5)

    def test_risk_parity_solver_failure_fallback_on_nan(self) -> None:
        """[DEFENSE: NUM-02] Valida fallback a volatilidad inversa si L-BFGS-B devuelve NaNs o falla."""
        fake_result = MagicMock()
        fake_result.success = False
        fake_result.x = np.array([np.nan, np.nan, np.nan])

        with patch("app.domain.services.portfolio_optimizer.minimize", return_value=fake_result):
            weights = risk_parity_portfolio(self.cov)
            self.assertTrue(np.all(np.isfinite(weights)))
            self.assertAlmostEqual(float(np.sum(weights)), 1.0, places=5)
            # Volatilidades: activo 0 (40%) > activo 1 (20%) > activo 2 (10%) -> w2 > w1 > w0
            self.assertGreater(weights[2], weights[1])
            self.assertGreater(weights[1], weights[0])


class TestOptimizationSchemas(unittest.TestCase):
    def test_tail_metrics_schema(self) -> None:
        metrics = TailRiskMetrics(
            skewness=-0.45,
            kurtosis=1.85,
            var_historical=0.024,
            var_parametric=0.022,
            cvar_historical=0.035,
            confidence_level=0.95,
        )
        self.assertEqual(metrics.skewness, -0.45)
        self.assertEqual(metrics.confidence_level, 0.95)

    def test_optimization_request_defaults(self) -> None:
        req = OptimizationRequest()
        self.assertEqual(req.method, OptimizationMethod.MINIMUM_VARIANCE)
        self.assertTrue(req.use_ledoit_wolf)
        self.assertEqual(req.confidence_level, 0.95)

    def test_optimization_result_schema(self) -> None:
        res = OptimizationResult(
            portfolio_id="p-100",
            method=OptimizationMethod.MINIMUM_VARIANCE.value,
            weights={"AAPL": 0.4, "AL30": 0.6},
            expected_annual_volatility=0.145,
            risk_contributions={"AAPL": 0.5, "AL30": 0.5},
            diversification_ratio=1.25,
            tail_metrics=TailRiskMetrics(
                skewness=-0.1,
                kurtosis=0.5,
                var_historical=0.02,
                var_parametric=0.019,
                cvar_historical=0.028,
            ),
        )
        self.assertEqual(res.portfolio_id, "p-100")
        self.assertEqual(sum(res.weights.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
