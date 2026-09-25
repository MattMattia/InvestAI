import unittest
import numpy as np

from app.domain.services.markov_regime import (
    MarkovRegimeModel,
    MarketRegime,
    get_dynamic_rebalance_band,
)
from app.domain.services.numerical_stability import (
    matrix_condition_number,
    nearest_positive_definite,
    safe_cholesky,
    safe_pinv,
)


class TestNumericalStability(unittest.TestCase):
    def setUp(self) -> None:
        np.random.seed(42)

    def test_safe_cholesky_well_conditioned(self) -> None:
        # Standard positive-definite matrix
        a = np.array([
            [4.0, 1.2, 0.8],
            [1.2, 3.0, 0.5],
            [0.8, 0.5, 2.0],
        ])
        l_mat = safe_cholesky(a)

        # 1. Lower triangular structure
        self.assertTrue(np.allclose(l_mat, np.tril(l_mat)))

        # 2. Decomposition equality: L @ L.T == A
        reconstructed = l_mat @ l_mat.T
        self.assertTrue(np.allclose(reconstructed, a, atol=1e-6))

    def test_safe_cholesky_collinear_and_singular(self) -> None:
        """
        Validates safe_cholesky when the covariance matrix is rank-deficient
        (collinear assets), which makes standard np.linalg.cholesky fail with LinAlgError.
        """
        # Create collinear matrix with rank 2 for 4 assets
        base = np.random.randn(50, 2)
        # Duplicate columns / linear combinations
        collinear_returns = np.column_stack([
            base[:, 0],
            base[:, 1],
            base[:, 0] * 2.0,
            base[:, 0] + base[:, 1],
        ])
        singular_cov = np.cov(collinear_returns, rowvar=False)

        # Standard Cholesky must fail on singular matrix
        with self.assertRaises(np.linalg.LinAlgError):
            np.linalg.cholesky(singular_cov)

        # safe_cholesky must handle it gracefully by adding jitter
        l_safe = safe_cholesky(singular_cov, jitter=1e-5)

        # 1. Structure
        self.assertEqual(l_safe.shape, (4, 4))
        self.assertTrue(np.allclose(l_safe, np.tril(l_safe)))

        # 2. Diagonal entries must be strictly positive
        diag_entries = np.diag(l_safe)
        self.assertTrue(np.all(diag_entries > 0.0), f"Diagonals must be positive: {diag_entries}")

        # 3. Regularized matrix L @ L.T is strictly positive-definite
        reg_cov = l_safe @ l_safe.T
        eigvals = np.linalg.eigvalsh(reg_cov)
        self.assertTrue(np.all(eigvals > 0.0), f"All eigenvalues must be positive: {eigvals}")

    def test_safe_cholesky_single_element(self) -> None:
        mat_pos = np.array([[9.0]])
        l_pos = safe_cholesky(mat_pos)
        self.assertAlmostEqual(l_pos[0, 0], 3.0)

        mat_zero = np.array([[0.0]])
        l_zero = safe_cholesky(mat_zero, jitter=1e-4)
        self.assertGreater(l_zero[0, 0], 0.0)

    def test_safe_pinv_singular_matrix(self) -> None:
        # Singular 4x4 matrix of rank 2
        u = np.random.randn(4, 2)
        v = np.random.randn(2, 4)
        singular_matrix = u @ v

        pinv = safe_pinv(singular_matrix)
        self.assertEqual(pinv.shape, (4, 4))

        # Check Moore-Penrose condition 1: A @ A^+ @ A == A
        rec1 = singular_matrix @ pinv @ singular_matrix
        self.assertTrue(np.allclose(rec1, singular_matrix, atol=1e-5))

        # Check Moore-Penrose condition 2: A^+ @ A @ A^+ == A^+
        rec2 = pinv @ singular_matrix @ pinv
        self.assertTrue(np.allclose(rec2, pinv, atol=1e-5))

    def test_safe_pinv_rectangular(self) -> None:
        rect = np.random.randn(6, 3)
        pinv = safe_pinv(rect)
        self.assertEqual(pinv.shape, (3, 6))
        # For full column rank matrix, A^+ @ A == I_3
        identity_test = pinv @ rect
        self.assertTrue(np.allclose(identity_test, np.eye(3), atol=1e-6))

    def test_nearest_positive_definite(self) -> None:
        # Indefinite matrix with negative eigenvalue
        mat = np.array([
            [1.0, 2.0],
            [2.0, 1.0],
        ])
        min_eig_orig = min(np.linalg.eigvalsh(mat))
        self.assertLess(min_eig_orig, 0.0)

        spd = nearest_positive_definite(mat, min_eigenvalue=1e-4)
        min_eig_spd = min(np.linalg.eigvalsh(spd))
        self.assertAlmostEqual(min_eig_spd, 1e-4, places=6)

    def test_matrix_condition_number(self) -> None:
        # Identity has condition number 1.0
        eye = np.eye(5)
        self.assertAlmostEqual(matrix_condition_number(eye), 1.0)

        # Singular matrix has inf condition number
        singular = np.ones((3, 3))
        self.assertEqual(matrix_condition_number(singular), float("inf"))


class TestMarkovRegime(unittest.TestCase):
    def setUp(self) -> None:
        np.random.seed(42)
        self.model = MarkovRegimeModel(
            transition_matrix=np.array([
                [0.90, 0.10],
                [0.20, 0.80],
            ]),
            annualized_vol_threshold=0.20,
        )

    def test_transition_matrix_row_stochastic(self) -> None:
        row_sums = np.sum(self.model.transition_matrix, axis=1)
        self.assertTrue(np.allclose(row_sums, [1.0, 1.0]))

    def test_stationary_distribution(self) -> None:
        # Analytically:
        # p01 = 0.10, p10 = 0.20 -> pi0 = 0.20 / (0.10 + 0.20) = 2/3 ≈ 0.6667
        # pi1 = 0.10 / 0.30 = 1/3 ≈ 0.3333
        stat = self.model.stationary_distribution()
        self.assertAlmostEqual(stat[MarketRegime.LOW_VOLATILITY.value], 0.6667, places=3)
        self.assertAlmostEqual(stat[MarketRegime.HIGH_VOLATILITY.value], 0.3333, places=3)
        self.assertAlmostEqual(sum(stat.values()), 1.0, places=4)

    def test_predict_probabilities(self) -> None:
        # From LOW_VOLATILITY 1 step ahead: P(Low)=0.90, P(High)=0.10
        pred_low = self.model.predict_next_regime_probabilities(MarketRegime.LOW_VOLATILITY, steps=1)
        self.assertAlmostEqual(pred_low[MarketRegime.LOW_VOLATILITY.value], 0.90, places=3)
        self.assertAlmostEqual(pred_low[MarketRegime.HIGH_VOLATILITY.value], 0.10, places=3)

        # From HIGH_VOLATILITY 1 step ahead: P(Low)=0.20, P(High)=0.80
        pred_high = self.model.predict_next_regime_probabilities(MarketRegime.HIGH_VOLATILITY, steps=1)
        self.assertAlmostEqual(pred_high[MarketRegime.LOW_VOLATILITY.value], 0.20, places=3)
        self.assertAlmostEqual(pred_high[MarketRegime.HIGH_VOLATILITY.value], 0.80, places=3)

        # Multi-step ahead prediction converges to stationary distribution
        pred_long = self.model.predict_next_regime_probabilities(MarketRegime.HIGH_VOLATILITY, steps=50)
        stat = self.model.stationary_distribution()
        self.assertAlmostEqual(pred_long[MarketRegime.LOW_VOLATILITY.value], stat[MarketRegime.LOW_VOLATILITY.value], places=2)

    def test_detect_regime_from_returns(self) -> None:
        # Low volatility series: daily std ~ 0.5% -> annual ~ 8% < 20%
        calm_returns = np.random.normal(0.0002, 0.005, size=40)
        regime_calm = self.model.detect_regime(calm_returns)
        self.assertEqual(regime_calm, MarketRegime.LOW_VOLATILITY)

        # High volatility series: daily std ~ 2.5% -> annual ~ 40% > 20%
        turbulent_returns = np.random.normal(0.0, 0.025, size=40)
        regime_turbulent = self.model.detect_regime(turbulent_returns)
        self.assertEqual(regime_turbulent, MarketRegime.HIGH_VOLATILITY)

    def test_fit_from_returns(self) -> None:
        # Synthetic return series with alternating regime periods
        calm_block = np.random.normal(0.0003, 0.006, size=50)
        crisis_block = np.random.normal(-0.001, 0.03, size=50)
        returns = np.concatenate([calm_block, crisis_block, calm_block])

        fitted_model = MarkovRegimeModel.fit_from_returns(returns, rolling_window=10, annualized_vol_threshold=0.20)
        p = fitted_model.transition_matrix

        # Row stochastic
        self.assertTrue(np.allclose(np.sum(p, axis=1), [1.0, 1.0]))
        # Probabilities in [0, 1]
        self.assertTrue(np.all(p >= 0.0))
        self.assertTrue(np.all(p <= 1.0))

    def test_get_dynamic_rebalance_band(self) -> None:
        base_band = 0.05  # +-5%

        # 1. Low volatility / expansion regime: tightens band by 15% (0.85x)
        band_low = get_dynamic_rebalance_band(MarketRegime.LOW_VOLATILITY, base_band)
        self.assertEqual(band_low, 0.0425)

        band_exp = get_dynamic_rebalance_band("EXPANSION", base_band)
        self.assertEqual(band_exp, 0.0425)

        # 2. High volatility / crisis regime: widens band by 75% (1.75x) to avoid churning
        band_high = get_dynamic_rebalance_band(MarketRegime.HIGH_VOLATILITY, base_band)
        self.assertEqual(band_high, 0.0875)

        band_crisis = get_dynamic_rebalance_band("CRISIS", base_band)
        self.assertEqual(band_crisis, 0.0875)

        # 3. Input validation
        with self.assertRaises(ValueError):
            get_dynamic_rebalance_band("LOW_VOLATILITY", -0.01)

        with self.assertRaises(ValueError):
            get_dynamic_rebalance_band("LOW_VOLATILITY", 0.0)


if __name__ == "__main__":
    unittest.main()
