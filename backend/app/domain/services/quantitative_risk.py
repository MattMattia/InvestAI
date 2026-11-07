from statistics import NormalDist

import numpy as np


def ledoit_wolf_covariance(returns: np.ndarray) -> np.ndarray:
    """
    Computes the Ledoit-Wolf (2004) shrinkage covariance matrix.
    Shrinks the sample covariance matrix towards a scaled identity target matrix:
        Sigma* = (1 - delta*) * S + delta* * F
    Guarantees that the resulting covariance matrix is well-conditioned,
    symmetric, strictly positive-definite and invertible, even when T < N
    or when asset returns exhibit high collinearity.

    Parameters:
        returns: 2D array of shape (T, N) where T = observations, N = assets.

    Returns:
        A positive-definite (N, N) covariance matrix.
    """
    arr = np.asarray(returns, dtype=np.float64)
    if np.isnan(arr).any() or np.isinf(arr).any():
        raise ValueError("La matriz de retornos contiene valores NaN o Infinitos.")
    if arr.ndim != 2:
        raise ValueError(
            f"returns debe ser una matriz 2D de dimensiones (T, N). Dimensiones dadas: {arr.ndim}"
        )

    t_obs, n_assets = arr.shape
    if t_obs < 2:
        raise ValueError(
            f"Se requieren al menos 2 periodos temporales (T >= 2). T recibido: {t_obs}"
        )
    if n_assets == 0:
        raise ValueError("La matriz de retornos no contiene activos (N = 0).")
    if n_assets == 1:
        var = float(np.var(arr[:, 0], ddof=1))
        return np.array([[max(var, 1e-6)]], dtype=np.float64)

    # 1. De-mean returns
    mean_vec = np.mean(arr, axis=0)
    x = arr - mean_vec

    # 2. Sample covariance matrix S
    s = (x.T @ x) / t_obs

    # 3. Shrinkage target F = mu * I_N (average sample variance on the diagonal)
    mu = float(np.trace(s) / n_assets)
    f = mu * np.eye(n_assets, dtype=np.float64)

    # 4. Squared Frobenius norm between S and F: d^2 = ||S - F||_F^2
    diff_sf = s - f
    d2 = float(np.sum(diff_sf**2))
    if d2 < 1e-15:
        # S is already proportional to identity
        return s

    # 5. Variance of sample covariance: b_bar^2 = 1/T^2 * sum_t ||x_t x_t^T - S||_F^2
    # Efficient vectorized computation across observations
    # Note that ||x_t x_t^T - S||_F^2 = ||x_t x_t^T||_F^2 - 2 * x_t^T S x_t + ||S||_F^2
    # where ||x_t x_t^T||_F^2 = (x_t^T x_t)^2
    sum_b_bar = 0.0
    for t in range(t_obs):
        xt = x[t, :]
        zt = np.outer(xt, xt)
        sum_b_bar += float(np.sum((zt - s) ** 2))

    b_bar2 = sum_b_bar / (t_obs**2)

    # 6. Optimal shrinkage intensity delta* in [0, 1]
    b2 = min(b_bar2, d2)
    shrinkage = max(0.0, min(1.0, b2 / d2))

    # 7. Shrunk Covariance Matrix
    shrunk_cov = (1.0 - shrinkage) * s + shrinkage * f

    # 8. Enforce exact symmetry and strict positive definiteness
    shrunk_cov = 0.5 * (shrunk_cov + shrunk_cov.T)
    eigvals = np.linalg.eigvalsh(shrunk_cov)
    min_eig = float(np.min(eigvals))
    if min_eig < 1e-8:
        ridge = abs(min_eig) + 1e-6
        shrunk_cov += ridge * np.eye(n_assets, dtype=np.float64)

    return shrunk_cov


def calculate_skewness(returns: np.ndarray | list) -> float:
    """
    Computes sample skewness (third standardized central moment) for a return series:
        Skewness = E[(R - mu)^3] / sigma^3
    """
    arr = np.asarray(returns, dtype=np.float64).flatten()
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < 3:
        return 0.0

    mean = float(np.mean(arr))
    variance = float(np.mean((arr - mean) ** 2))
    if variance < 1e-14:
        return 0.0

    m3 = float(np.mean((arr - mean) ** 3))
    skew = m3 / (variance**1.5)
    return round(float(skew), 4)


def calculate_kurtosis(returns: np.ndarray | list) -> float:
    """
    Computes excess kurtosis (fourth standardized central moment minus 3.0):
        Excess Kurtosis = (E[(R - mu)^4] / sigma^4) - 3.0
    A standard normal distribution has excess kurtosis = 0.0.
    Positive excess kurtosis indicates fat tails (leptokurtic).
    """
    arr = np.asarray(returns, dtype=np.float64).flatten()
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < 4:
        return 0.0

    mean = float(np.mean(arr))
    variance = float(np.mean((arr - mean) ** 2))
    if variance < 1e-14:
        return 0.0

    m4 = float(np.mean((arr - mean) ** 4))
    kurt = (m4 / (variance**2)) - 3.0
    return round(float(kurt), 4)


def calculate_var(
    returns: np.ndarray | list,
    alpha: float = 0.95,
    method: str = "historical",
) -> float:
    """
    Calculates Value at Risk (VaR) at confidence level alpha.
    Reported as a positive loss magnitude (e.g. 0.05 for 5% potential loss).

    Parameters:
        returns: 1D array of portfolio or asset periodic returns.
        alpha: Confidence level (e.g. 0.95 for 95% VaR).
        method: 'historical' (empirical quantile) or 'parametric' (Gaussian assumption).
    """
    arr = np.asarray(returns, dtype=np.float64).flatten()
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return 0.0

    if not (0.5 < alpha < 1.0):
        raise ValueError("alpha debe estar en el intervalo (0.5, 1.0), típicamente 0.95 o 0.99.")

    if method.lower() == "historical":
        quantile_pct = (1.0 - alpha) * 100.0
        cutoff = float(np.percentile(arr, quantile_pct))
        # Loss magnitude
        var = -cutoff if cutoff < 0.0 else 0.0
        return round(float(var), 6)

    elif method.lower() == "parametric":
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1))
        z = NormalDist().inv_cdf(alpha)  # e.g., 1.64485 for 95%
        # VaR = z * std - mean (positive loss)
        var = max(0.0, z * std - mean)
        return round(float(var), 6)

    else:
        raise ValueError(
            f"Método de VaR no soportado: '{method}'. Opciones: 'historical', 'parametric'."
        )


def calculate_cvar(
    returns: np.ndarray | list,
    alpha: float = 0.95,
) -> float:
    """
    Calculates Conditional Value at Risk (CVaR / Expected Shortfall) at confidence level alpha.
    Represents the expected loss given that the loss has exceeded the VaR threshold:
        CVaR_alpha = -E[R | R <= Quantile(1 - alpha)]
    Reported as a positive loss magnitude.
    """
    arr = np.asarray(returns, dtype=np.float64).flatten()
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return 0.0

    if not (0.5 < alpha < 1.0):
        raise ValueError("alpha debe estar en el intervalo (0.5, 1.0), típicamente 0.95 o 0.99.")

    quantile_pct = (1.0 - alpha) * 100.0
    cutoff = float(np.percentile(arr, quantile_pct))
    tail_losses = arr[arr <= cutoff]

    if len(tail_losses) == 0:
        return calculate_var(arr, alpha=alpha, method="historical")

    mean_tail = float(np.mean(tail_losses))
    cvar = -mean_tail if mean_tail < 0.0 else 0.0
    return round(float(cvar), 6)
