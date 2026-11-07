import numpy as np

from app.schemas.backtest import BacktestPerformanceMetrics


def _clean_series(values: list[float] | np.ndarray) -> np.ndarray:
    """
    Sanea y valida una serie numérica para garantizar que sea un array 1D
    finito (sin NaNs ni Infs) de tipo float64.
    """
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (ValueError, TypeError):
        return np.empty(0, dtype=np.float64)

    if arr.ndim != 1 or len(arr) == 0:
        return np.empty(0, dtype=np.float64)

    if not np.all(np.isfinite(arr)):
        return np.empty(0, dtype=np.float64)

    return arr


def calculate_total_return(portfolio_values: list[float] | np.ndarray) -> float:
    """
    Calcula el retorno total acumulado de una serie de valor liquidativo (NAV):
    Total Return = (Valor Final - Valor Inicial) / Valor Inicial = (V_N / V_0) - 1

    Retorna 0.0 si la serie tiene menos de 2 elementos, si V_0 <= 0 o ante valores corruptos.
    """
    arr = _clean_series(portfolio_values)
    if len(arr) < 2:
        return 0.0

    v0 = float(arr[0])
    vn = float(arr[-1])

    if v0 <= 0.0:
        return 0.0

    if vn <= 0.0:
        return -1.0

    total_ret = (vn / v0) - 1.0
    return float(total_ret) if np.isfinite(total_ret) else 0.0


def calculate_cagr(
    portfolio_values: list[float] | np.ndarray,
    periods_per_year: int = 252,
) -> float:
    """
    Calcula la Tasa de Crecimiento Anual Compuesto (CAGR):
    CAGR = (Valor Final / Valor Inicial) ** (periods_per_year / N) - 1

    donde N es el número de períodos transcurridos (len(portfolio_values) - 1).
    Retorna 0.0 si no hay observaciones suficientes o ante división por cero.
    """
    arr = _clean_series(portfolio_values)
    n = len(arr) - 1

    if n <= 0 or periods_per_year <= 0:
        return 0.0

    v0 = float(arr[0])
    vn = float(arr[-1])

    if v0 <= 0.0:
        return 0.0

    if vn <= 0.0:
        return -1.0

    try:
        cagr = (vn / v0) ** (periods_per_year / n) - 1.0
        return float(cagr) if np.isfinite(cagr) else 0.0
    except (OverflowError, ZeroDivisionError):
        return 0.0


def calculate_daily_returns(portfolio_values: list[float] | np.ndarray) -> np.ndarray:
    """
    Calcula la serie de retornos diarios discretos:
    R_t = (V_t - V_{t-1}) / V_{t-1}

    Retorna un array vacío si la serie es insuficiente o contiene valores inválidos.
    """
    arr = _clean_series(portfolio_values)
    if len(arr) < 2:
        return np.empty(0, dtype=np.float64)

    prev_vals = arr[:-1]
    curr_vals = arr[1:]

    # Protección contra denominadores no positivos
    valid_mask = prev_vals > 0.0
    returns = np.zeros(len(curr_vals), dtype=np.float64)
    returns[valid_mask] = (curr_vals[valid_mask] - prev_vals[valid_mask]) / prev_vals[valid_mask]

    return returns


def calculate_annualized_volatility(
    daily_returns: list[float] | np.ndarray,
    periods_per_year: int = 252,
) -> float:
    """
    Calcula la volatilidad anualizada de los retornos:
    sigma_ann = std(returns, ddof=1) * sqrt(periods_per_year)

    Retorna 0.0 si hay menos de 2 retornos o si la varianza es nula/inválida.
    """
    arr = _clean_series(daily_returns)
    if len(arr) < 2 or periods_per_year <= 0:
        return 0.0

    sample_std = float(np.std(arr, ddof=1))
    if not np.isfinite(sample_std) or sample_std <= 0.0:
        return 0.0

    vol = sample_std * np.sqrt(periods_per_year)
    return float(vol) if np.isfinite(vol) else 0.0


def calculate_sharpe_ratio(
    daily_returns: list[float] | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Calcula el Ratio de Sharpe anualizado:
    Sharpe = (mean(returns) * periods_per_year - risk_free_rate) / sigma_ann

    Retorna 0.0 si la volatilidad es cero o insuficiente.
    """
    arr = _clean_series(daily_returns)
    if len(arr) < 2 or periods_per_year <= 0:
        return 0.0

    vol = calculate_annualized_volatility(arr, periods_per_year=periods_per_year)
    if vol <= 1e-12:
        return 0.0

    ann_return = float(np.mean(arr) * periods_per_year)
    excess_return = ann_return - risk_free_rate

    sharpe = excess_return / vol
    return float(sharpe) if np.isfinite(sharpe) else 0.0


def calculate_sortino_ratio(
    daily_returns: list[float] | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Calcula el Ratio de Sortino anualizado evaluando únicamente el desvío bajista
    (downside deviation) respecto a la tasa libre de riesgo:
    tau = risk_free_rate / periods_per_year
    d_t = min(0.0, R_t - tau)
    downside_vol = sqrt(mean(d_t^2)) * sqrt(periods_per_year)
    Sortino = (mean(returns) * periods_per_year - risk_free_rate) / downside_vol

    Retorna 0.0 si no hay desvío bajista o si el cálculo es indeterminado.
    """
    arr = _clean_series(daily_returns)
    if len(arr) < 2 or periods_per_year <= 0:
        return 0.0

    daily_rf = risk_free_rate / periods_per_year
    downside_diff = np.minimum(arr - daily_rf, 0.0)
    downside_variance = float(np.mean(downside_diff**2))

    if not np.isfinite(downside_variance) or downside_variance <= 1e-16:
        return 0.0

    downside_vol_ann = np.sqrt(downside_variance) * np.sqrt(periods_per_year)
    if downside_vol_ann <= 1e-12:
        return 0.0

    ann_return = float(np.mean(arr) * periods_per_year)
    excess_return = ann_return - risk_free_rate

    sortino = excess_return / downside_vol_ann
    return float(sortino) if np.isfinite(sortino) else 0.0


def calculate_drawdown_series(portfolio_values: list[float] | np.ndarray) -> np.ndarray:
    """
    Calcula la serie histórica de drawdowns relativos respecto al máximo histórico acumulado:
    DD_t = (V_t - Peak_t) / Peak_t <= 0.0

    Retorna un array del mismo tamaño con valores no positivos (o array vacío si la entrada es inválida).
    """
    arr = _clean_series(portfolio_values)
    if len(arr) == 0:
        return np.empty(0, dtype=np.float64)

    peaks = np.maximum.accumulate(arr)
    valid_peaks = peaks > 0.0

    dd = np.zeros(len(arr), dtype=np.float64)
    dd[valid_peaks] = (arr[valid_peaks] - peaks[valid_peaks]) / peaks[valid_peaks]
    dd = np.minimum(dd, 0.0)

    return dd


def calculate_max_drawdown(portfolio_values: list[float] | np.ndarray) -> float:
    """
    Calcula el Máximo Drawdown (MDD) histórico como magnitud positiva (>= 0.0):
    MDD = |min(DD_t)|

    Retorna 0.0 si la serie no experimentó ninguna pérdida o es insuficiente.
    """
    dd_series = calculate_drawdown_series(portfolio_values)
    if len(dd_series) < 2:
        return 0.0

    min_dd = float(np.min(dd_series))
    mdd_magnitude = abs(min_dd)
    return float(mdd_magnitude) if np.isfinite(mdd_magnitude) else 0.0


def calculate_calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """
    Calcula el Ratio de Calmar determinista:
    Calmar = CAGR / |MDD|

    Retorna 0.0 si el MDD es nulo o cercano a cero (evitando división por cero).
    """
    abs_mdd = abs(float(max_drawdown))
    if not np.isfinite(cagr) or not np.isfinite(abs_mdd) or abs_mdd <= 1e-12:
        return 0.0

    calmar = cagr / abs_mdd
    return float(calmar) if np.isfinite(calmar) else 0.0


def calculate_performance_metrics(
    portfolio_values: list[float] | np.ndarray,
    risk_free_rate: float = 0.0,
    total_frictions: float = 0.0,
    periods_per_year: int = 252,
) -> BacktestPerformanceMetrics:
    """
    Calcula y consolida todas las métricas de rendimiento y riesgo de la cartera
    a partir de la serie temporal de valores liquidativos (NAV).
    """
    tot_return = calculate_total_return(portfolio_values)
    cagr_val = calculate_cagr(portfolio_values, periods_per_year=periods_per_year)
    returns = calculate_daily_returns(portfolio_values)
    ann_vol = calculate_annualized_volatility(returns, periods_per_year=periods_per_year)
    sharpe = calculate_sharpe_ratio(
        returns,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )
    sortino = calculate_sortino_ratio(
        returns,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )
    mdd = calculate_max_drawdown(portfolio_values)
    calmar = calculate_calmar_ratio(cagr=cagr_val, max_drawdown=mdd)

    return BacktestPerformanceMetrics(
        total_return=tot_return,
        cagr=cagr_val,
        annualized_volatility=ann_vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=mdd,
        calmar_ratio=calmar,
        total_frictions=max(0.0, float(total_frictions)),
    )
