import numpy as np
from scipy.optimize import minimize


def minimum_variance_portfolio(cov_matrix: np.ndarray) -> np.ndarray:
    """
    Computes the long-only Global Minimum Variance (GMV) portfolio weights:
        min_w  (1/2) * w^T * Sigma * w
        s.t.   sum(w) = 1.0,  w_i >= 0 for all i

    Parameters:
        cov_matrix: (N, N) covariance matrix.

    Returns:
        1D array of optimal weights of length N, strictly non-negative and summing to 1.0.
    """
    cov = np.asarray(cov_matrix, dtype=np.float64)
    if np.isnan(cov).any() or np.isinf(cov).any():
        raise ValueError("cov_matrix contiene valores NaN o Infinitos.")
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError(
            f"cov_matrix debe ser una matriz cuadrada (N, N). Forma recibida: {cov.shape}"
        )

    n_assets = cov.shape[0]
    if n_assets == 0:
        raise ValueError("cov_matrix no contiene activos (N = 0).")
    if n_assets == 1:
        return np.array([1.0], dtype=np.float64)

    # Initial guess: Equal weights 1/N
    w0 = np.full(n_assets, 1.0 / n_assets, dtype=np.float64)

    def objective(w: np.ndarray) -> float:
        return 0.5 * float(w.T @ cov @ w)

    def gradient(w: np.ndarray) -> np.ndarray:
        return cov @ w

    # Constraints: sum(w) = 1.0
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0, "jac": lambda w: np.ones_like(w)}

    # Bounds: w_i in [0.0, 1.0] (long-only)
    bounds = [(0.0, 1.0) for _ in range(n_assets)]

    result = minimize(
        fun=objective,
        x0=w0,
        jac=gradient,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-13, "maxiter": 200, "disp": False},
    )

    # [DEFENSE: NUM-02] Verify solver convergence and output integrity; fallback to 1/N on failure or NaNs
    if (not result.success) or (result.x is None) or (not np.all(np.isfinite(result.x))):
        return w0

    raw_weights = np.maximum(0.0, result.x)
    sum_w = float(np.sum(raw_weights))
    if sum_w <= 0.0 or not np.isfinite(sum_w):
        return w0

    # Guarantee sum(w) == 1.0 exactly
    normalized_weights = raw_weights / sum_w
    if not np.all(np.isfinite(normalized_weights)):
        return w0

    return np.round(normalized_weights, 6)


def risk_parity_portfolio(
    cov_matrix: np.ndarray,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> np.ndarray:
    """
    Computes the long-only Equal Risk Contribution (Risk Parity) portfolio weights.
    Each asset contributes an identical proportion of total portfolio risk:
        RC_i = w_i * (Sigma * w)_i / sigma_p = sigma_p / N

    Solved via the strictly convex Spinu (2013) / Maillard et al. (2010) formulation:
        min_y  (1/2) * y^T * Sigma * y - sum(ln(y_i))
        s.t.   y_i > 0
    with analytical gradient:
        grad(y) = Sigma * y - (1 / y)
    The unique global minimum normalized gives:
        w_i = y_i / sum(y)

    Parameters:
        cov_matrix: (N, N) covariance matrix.
        max_iter: Maximum solver iterations.
        tol: Optimization tolerance.

    Returns:
        1D array of Risk Parity weights of length N, summing to 1.0.
    """
    cov = np.asarray(cov_matrix, dtype=np.float64)
    if np.isnan(cov).any() or np.isinf(cov).any():
        raise ValueError("cov_matrix contiene valores NaN o Infinitos.")
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError(
            f"cov_matrix debe ser una matriz cuadrada (N, N). Forma recibida: {cov.shape}"
        )

    n_assets = cov.shape[0]
    if n_assets == 0:
        raise ValueError("cov_matrix no contiene activos (N = 0).")
    if n_assets == 1:
        return np.array([1.0], dtype=np.float64)

    # [DEFENSE: NUM-01] Isolate zero-variance assets to prevent analytical gradient -1/y explosion
    variances = np.diag(cov)
    pos_mask = variances > 1e-12
    n_pos = int(np.sum(pos_mask))

    def inverse_vol_fallback() -> np.ndarray:
        vols = np.sqrt(np.maximum(variances, 0.0))
        inv_v = np.zeros(n_assets, dtype=np.float64)
        if n_pos > 0:
            inv_v[pos_mask] = 1.0 / vols[pos_mask]
            s = float(np.sum(inv_v))
            if s > 0.0 and np.isfinite(s):
                return np.round(inv_v / s, 6)
        return np.full(n_assets, 1.0 / n_assets, dtype=np.float64)

    # If all assets have near-zero variance, fallback to equal weights
    if n_pos == 0:
        return np.full(n_assets, 1.0 / n_assets, dtype=np.float64)

    # If only 1 asset has positive variance, it absorbs all risk allocation
    if n_pos == 1:
        w = np.zeros(n_assets, dtype=np.float64)
        w[pos_mask] = 1.0
        return w

    # If a subset of assets has zero variance, isolate and solve on the strictly positive submatrix
    if n_pos < n_assets:
        cov_sub = cov[np.ix_(pos_mask, pos_mask)]
        sub_weights = risk_parity_portfolio(cov_sub, max_iter=max_iter, tol=tol)
        w = np.zeros(n_assets, dtype=np.float64)
        w[pos_mask] = sub_weights
        return np.round(w, 6)

    # Symmetrize and regularize strictly positive-definite property to guarantee Spinu convexity
    sym_cov = 0.5 * (cov + cov.T)
    min_eig = float(np.min(np.linalg.eigvalsh(sym_cov)))
    if min_eig < 1e-8:
        sym_cov = sym_cov + (abs(min_eig) + 1e-6) * np.eye(n_assets, dtype=np.float64)

    # Initial guess y0 = 1 / sqrt(diag(sym_cov))
    y0 = 1.0 / np.sqrt(np.maximum(np.diag(sym_cov), 1e-8))
    y0 = y0 / np.sum(y0)

    def objective_and_grad(y: np.ndarray) -> tuple[float, np.ndarray]:
        y_safe = np.maximum(y, 1e-12)
        val = 0.5 * float(y_safe.T @ sym_cov @ y_safe) - float(np.sum(np.log(y_safe)))
        grad = (sym_cov @ y_safe) - (1.0 / y_safe)
        return val, grad

    bounds = [(1e-8, None) for _ in range(n_assets)]

    result = minimize(
        fun=objective_and_grad,
        x0=y0,
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": max_iter, "ftol": tol, "gtol": tol},
    )

    # [DEFENSE: NUM-02] Explicit verification: do not trust result.x if solver failed or output is invalid
    if (not result.success) or (result.x is None) or (not np.all(np.isfinite(result.x))):
        return inverse_vol_fallback()

    y_opt = np.maximum(0.0, result.x)
    sum_y = float(np.sum(y_opt))
    if sum_y <= 0.0 or not np.isfinite(sum_y):
        return inverse_vol_fallback()

    w = y_opt / sum_y
    if not np.all(np.isfinite(w)):
        return inverse_vol_fallback()

    return np.round(w, 6)


def calculate_portfolio_volatility(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
    annualized: bool = True,
    trading_days: int = 252,
) -> float:
    """
    Computes total portfolio volatility:
        sigma_p = sqrt(w^T * Sigma * w)
    """
    w = np.asarray(weights, dtype=np.float64).flatten()
    cov = np.asarray(cov_matrix, dtype=np.float64)
    var = float(w.T @ cov @ w)
    vol = float(np.sqrt(max(0.0, var)))
    if annualized:
        vol *= float(np.sqrt(trading_days))
    return round(vol, 6)


def calculate_risk_contributions(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> np.ndarray:
    """
    Computes the percentage risk contribution of each asset to total portfolio risk:
        RC_i = w_i * (Sigma * w)_i / (w^T * Sigma * w)
    Sums to 1.0 (100% of risk).
    """
    w = np.asarray(weights, dtype=np.float64).flatten()
    cov = np.asarray(cov_matrix, dtype=np.float64)
    port_var = float(w.T @ cov @ w)
    if port_var <= 1e-12:
        return np.full_like(w, 1.0 / len(w))

    marginal_contrib = cov @ w
    risk_contrib = w * marginal_contrib
    percentage_contrib = risk_contrib / port_var
    return np.round(percentage_contrib, 6)


def calculate_diversification_ratio(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """
    Computes the Choueifaty & Coignard (2008) Diversification Ratio (DR):
        DR = (sum_i w_i * sigma_i) / sigma_p
    For uncorrelated or diversified portfolios, DR > 1.0.
    """
    w = np.asarray(weights, dtype=np.float64).flatten()
    cov = np.asarray(cov_matrix, dtype=np.float64)
    asset_vols = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    weighted_vol = float(np.sum(w * asset_vols))
    port_vol = float(np.sqrt(max(1e-12, w.T @ cov @ w)))
    dr = weighted_vol / port_vol
    return round(float(dr), 4)
