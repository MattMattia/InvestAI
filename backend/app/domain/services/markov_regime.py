from enum import Enum
import math
from typing import Dict, Optional, Union
import numpy as np


class MarketRegime(str, Enum):
    LOW_VOLATILITY = "LOW_VOLATILITY"    # Régimen de Expansión / Estabilidad
    HIGH_VOLATILITY = "HIGH_VOLATILITY"  # Régimen de Turbulencia / Crisis


class MarkovRegimeModel:
    """
    Two-state Markov Switching / Transition model for market volatility regimes:
        State 0: Low Volatility / Expansion (Mercado estable)
        State 1: High Volatility / Crisis (Mercado en estrés)

    Row i of transition_matrix contains transition probabilities from state i:
        P = [[p_00, p_01],
             [p_10, p_11]]
    where p_00 + p_01 = 1.0 and p_10 + p_11 = 1.0.
    """

    def __init__(
        self,
        transition_matrix: Optional[np.ndarray] = None,
        annualized_vol_threshold: float = 0.22,
    ):
        """
        Parameters:
            transition_matrix: (2, 2) row-stochastic matrix. Defaults to realistic
                               empirical financial regime persistence (p_00=0.95, p_11=0.85).
            annualized_vol_threshold: Volatility threshold dividing Low vs High volatility regimes.
        """
        if transition_matrix is None:
            # Typical empirical persistence in financial markets:
            # Low volatility regimes are sticky (95% persistence)
            # High volatility/crisis regimes are moderately sticky (85% persistence)
            self.transition_matrix = np.array([
                [0.95, 0.05],
                [0.15, 0.85],
            ], dtype=np.float64)
        else:
            mat = np.asarray(transition_matrix, dtype=np.float64)
            if mat.shape != (2, 2):
                raise ValueError(f"transition_matrix debe tener dimensiones (2, 2). Forma recibida: {mat.shape}")
            # Ensure row-stochastic property
            row_sums = np.sum(mat, axis=1, keepdims=True)
            if np.any(row_sums <= 0):
                raise ValueError("Las filas de la matriz de transición no pueden sumar cero.")
            self.transition_matrix = mat / row_sums

        self.annualized_vol_threshold = float(annualized_vol_threshold)

    @classmethod
    def fit_from_returns(
        cls,
        returns: Union[np.ndarray, list],
        rolling_window: int = 20,
        annualized_vol_threshold: float = 0.22,
        trading_days: int = 252,
    ) -> "MarkovRegimeModel":
        """
        Calibrates transition matrix from an empirical return series by computing
        rolling realized volatility and observing historical regime state transitions.
        Uses Laplace add-one smoothing to prevent zero transition probabilities.
        """
        arr = np.asarray(returns, dtype=np.float64).flatten()
        arr = arr[~np.isnan(arr) & ~np.isinf(arr)]

        if len(arr) < rolling_window + 2:
            return cls(annualized_vol_threshold=annualized_vol_threshold)

        # 1. Compute rolling realized volatility
        rolling_vols = []
        scale = math.sqrt(trading_days)
        for i in range(rolling_window, len(arr) + 1):
            window_slice = arr[i - rolling_window : i]
            vol = float(np.std(window_slice, ddof=1)) * scale
            rolling_vols.append(vol)

        # 2. Discretize into states: 0 = LOW, 1 = HIGH
        states = [1 if v >= annualized_vol_threshold else 0 for v in rolling_vols]

        # 3. Count transitions with Laplace smoothing (+1)
        counts = np.ones((2, 2), dtype=np.float64)
        for t in range(len(states) - 1):
            s_from = states[t]
            s_to = states[t + 1]
            counts[s_from, s_to] += 1.0

        transition_matrix = counts / np.sum(counts, axis=1, keepdims=True)
        return cls(
            transition_matrix=transition_matrix,
            annualized_vol_threshold=annualized_vol_threshold,
        )

    def detect_regime(
        self,
        returns: Union[np.ndarray, list],
        window: int = 20,
        trading_days: int = 252,
    ) -> MarketRegime:
        """
        Classifies current regime based on recent return volatility relative to threshold.
        """
        arr = np.asarray(returns, dtype=np.float64).flatten()
        arr = arr[~np.isnan(arr) & ~np.isinf(arr)]

        if len(arr) < 2:
            return MarketRegime.LOW_VOLATILITY

        recent_slice = arr[-window:] if len(arr) >= window else arr
        vol = float(np.std(recent_slice, ddof=1)) * math.sqrt(trading_days)

        if vol >= self.annualized_vol_threshold:
            return MarketRegime.HIGH_VOLATILITY
        return MarketRegime.LOW_VOLATILITY

    def predict_next_regime_probabilities(
        self,
        current_regime: Union[MarketRegime, str],
        steps: int = 1,
    ) -> Dict[str, float]:
        """
        Forecasts regime probabilities k steps ahead:
            pi_{t+k} = pi_t @ (P^k)
        """
        regime_str = str(current_regime.value if isinstance(current_regime, MarketRegime) else current_regime).upper()
        if "HIGH" in regime_str or "CRISIS" in regime_str:
            pi_0 = np.array([0.0, 1.0], dtype=np.float64)
        else:
            pi_0 = np.array([1.0, 0.0], dtype=np.float64)

        # Matrix power P^k
        pk = np.linalg.matrix_power(self.transition_matrix, max(1, steps))
        pi_k = pi_0 @ pk

        return {
            MarketRegime.LOW_VOLATILITY.value: round(float(pi_k[0]), 4),
            MarketRegime.HIGH_VOLATILITY.value: round(float(pi_k[1]), 4),
        }

    def stationary_distribution(self) -> Dict[str, float]:
        """
        Computes the long-run ergodic steady-state probabilities pi such that:
            pi @ P = pi  and  sum(pi) = 1.0
        For 2-state chain:
            pi_0 = p_10 / (p_01 + p_10)
            pi_1 = p_01 / (p_01 + p_10)
        """
        p01 = float(self.transition_matrix[0, 1])
        p10 = float(self.transition_matrix[1, 0])
        denom = p01 + p10

        if denom <= 1e-12:
            return {
                MarketRegime.LOW_VOLATILITY.value: 0.5,
                MarketRegime.HIGH_VOLATILITY.value: 0.5,
            }

        pi_0 = p10 / denom
        pi_1 = p01 / denom

        return {
            MarketRegime.LOW_VOLATILITY.value: round(float(pi_0), 4),
            MarketRegime.HIGH_VOLATILITY.value: round(float(pi_1), 4),
        }


def get_dynamic_rebalance_band(
    current_regime: Union[MarketRegime, str],
    base_band: float,
) -> float:
    """
    Dynamically adjusts the rebalancing tolerance band based on market regime:

    - In LOW_VOLATILITY / EXPANSION (low volatility, normal bid-ask spread):
      Tightens the band (0.85x base) or maintains baseline, allowing precise target adherence
      because transaction slippage and volatility churn are minimal.

    - In HIGH_VOLATILITY / CRISIS (high volatility, wide bid-ask spread):
      Widens the band (1.75x base) to avoid costly whipsaw and excessive trading costs
      amid severe short-term market noise.

    Parameters:
        current_regime: 'LOW_VOLATILITY', 'HIGH_VOLATILITY', 'EXPANSION', 'CRISIS'.
        base_band: Baseline tolerance band fraction (e.g. 0.05 for +-5%).

    Returns:
        Adjusted tolerance band as float rounded to 4 decimals.
    """
    if base_band <= 0:
        raise ValueError("base_band debe ser un número estrictamente positivo.")

    regime_str = str(current_regime.value if isinstance(current_regime, MarketRegime) else current_regime).upper()

    if any(k in regime_str for k in ["HIGH", "CRISIS", "TURBULENCE"]):
        # Widens tolerance band by 75% to prevent costly churning in volatile markets
        multiplier = 1.75
    elif any(k in regime_str for k in ["LOW", "EXPANSION", "STABLE"]):
        # Tightens tolerance band to 85% of base in quiet trending regimes
        multiplier = 0.85
    else:
        multiplier = 1.0

    return round(float(base_band * multiplier), 4)
