from dataclasses import dataclass
from statistics import NormalDist
from typing import List, Tuple, Union
import numpy as np


def log_returns(prices: Union[List[float], np.ndarray]) -> np.ndarray:
    """
    Calculates continuous logarithmic returns from a sequential price series:
    r_t = ln(P_t / P_{t-1})
    """
    arr = np.asarray(prices, dtype=np.float64)
    if arr.ndim != 1 or len(arr) < 2:
        return np.empty(0, dtype=np.float64)

    if np.any(arr <= 0.0):
        return np.empty(0, dtype=np.float64)

    return np.log(arr[1:] / arr[:-1])


def realized_volatility(
    returns: Union[List[float], np.ndarray],
    trading_days: int = 252,
) -> float:
    """
    Calculates the sample realized volatility annualized:
    sigma_ann = std(returns, ddof=1) * sqrt(trading_days)
    """
    arr = np.asarray(returns, dtype=np.float64)
    if len(arr) < 2:
        return 0.0

    sample_std = float(np.std(arr, ddof=1))
    if np.isnan(sample_std) or sample_std <= 0.0 or trading_days <= 0:
        return 0.0

    return float(sample_std * np.sqrt(trading_days))


def portfolio_volatility(
    weights: Union[List[float], np.ndarray],
    cov_matrix: np.ndarray,
    trading_days: int = 252,
) -> float:
    """
    Calculates portfolio volatility using matrix formulation:
    sigma_p = sqrt(w^T * Sigma * w) * sqrt(trading_days)
    """
    w = np.asarray(weights, dtype=np.float64)
    sigma = np.asarray(cov_matrix, dtype=np.float64)

    if w.ndim != 1 or sigma.ndim != 2:
        return 0.0

    n = len(w)
    if n == 0 or sigma.shape != (n, n) or trading_days <= 0:
        return 0.0

    variance = float(w.T @ sigma @ w)
    if np.isnan(variance) or variance <= 0.0:
        return 0.0

    return float(np.sqrt(variance) * np.sqrt(trading_days))


def sharpe_ratio(
    returns: Union[List[float], np.ndarray],
    risk_free_rate: float = 0.0,
    trading_days: int = 252,
) -> float:
    """
    Calculates the annualized Sharpe Ratio.
    """
    arr = np.asarray(returns, dtype=np.float64)
    if len(arr) < 2:
        return 0.0

    vol = realized_volatility(arr, trading_days=trading_days)
    if vol <= 0.0:
        return 0.0

    ann_return = float(np.mean(arr) * trading_days)
    return float((ann_return - risk_free_rate) / vol)


def sortino_ratio(
    returns: Union[List[float], np.ndarray],
    risk_free_rate: float = 0.0,
    trading_days: int = 252,
    target_return: float = 0.0,
) -> float:
    """
    Calculates the annualized Sortino Ratio focusing on downside volatility.
    """
    arr = np.asarray(returns, dtype=np.float64)
    if len(arr) < 2:
        return 0.0

    downside_diff = np.minimum(arr - target_return, 0.0)
    downside_variance = float(np.mean(downside_diff**2))
    if np.isnan(downside_variance) or downside_variance <= 0.0 or trading_days <= 0:
        return 0.0

    downside_vol_ann = float(np.sqrt(downside_variance) * np.sqrt(trading_days))
    if downside_vol_ann <= 0.0:
        return 0.0

    ann_return = float(np.mean(arr) * trading_days)
    return float((ann_return - risk_free_rate) / downside_vol_ann)


def max_drawdown(
    nav_series: Union[List[float], np.ndarray],
    trading_days: int = 252,
) -> Tuple[float, float]:
    """
    Deterministically computes the Maximum Drawdown (MDD) and Calmar Ratio from a NAV series.
    """
    arr = np.asarray(nav_series, dtype=np.float64)
    if len(arr) < 2 or np.any(arr <= 0.0):
        return 0.0, 0.0

    peaks = np.maximum.accumulate(arr)
    drawdowns = (arr - peaks) / peaks
    mdd = float(np.min(drawdowns))

    if mdd > 0.0:
        mdd = 0.0

    periods = len(arr) - 1
    start_val = float(arr[0])
    end_val = float(arr[-1])

    if start_val > 0.0 and end_val > 0.0 and periods > 0:
        cagr = float((end_val / start_val) ** (trading_days / periods) - 1.0)
    else:
        cagr = 0.0

    if abs(mdd) > 1e-9:
        calmar = float(cagr / abs(mdd))
    else:
        calmar = 0.0

    return mdd, calmar


def parametric_var(
    returns: Union[List[float], np.ndarray],
    confidence: float = 0.95,
) -> float:
    """
    Calculates Parametric Value at Risk (VaR) under a Gaussian assumption:
    VaR_alpha = Z_alpha * sigma - mu
    """
    if not (0.0 < confidence < 1.0):
        return 0.0

    arr = np.asarray(returns, dtype=np.float64)
    if len(arr) < 2:
        return 0.0

    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))

    if np.isnan(sigma) or sigma <= 0.0:
        return 0.0

    z_score = float(NormalDist().inv_cdf(confidence))
    var = (z_score * sigma) - mu
    return float(var)


@dataclass(frozen=True)
class QuantitativeRiskSummary:
    realized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    parametric_var_95: float

    @classmethod
    def from_returns_and_nav(
        cls,
        returns: Union[List[float], np.ndarray],
        nav_series: Union[List[float], np.ndarray],
        risk_free_rate: float = 0.0,
        trading_days: int = 252,
    ) -> QuantitativeRiskSummary:
        vol = realized_volatility(returns, trading_days=trading_days)
        sharpe = sharpe_ratio(returns, risk_free_rate=risk_free_rate, trading_days=trading_days)
        sortino = sortino_ratio(returns, risk_free_rate=risk_free_rate, trading_days=trading_days)
        mdd, calmar = max_drawdown(nav_series, trading_days=trading_days)
        var_95 = parametric_var(returns, confidence=0.95)

        return cls(
            realized_volatility=round(vol, 4),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            max_drawdown=round(mdd, 4),
            calmar_ratio=round(calmar, 4),
            parametric_var_95=round(var_95, 4),
        )
