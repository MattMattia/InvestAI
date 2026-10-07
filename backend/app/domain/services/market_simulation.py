"""
Servicio de simulación estocástica de mercados financieros.
Implementa trayectorias de precios sintéticos utilizando Movimiento Browniano Geométrico (GBM)
multivariado bajo la formulación SDE de Black-Scholes con correlación sistémica.
"""
import datetime as dt
from typing import Dict, List
import numpy as np


def generate_gbm_market_prices(
    tickers: List[str],
    start_date: dt.date,
    end_date: dt.date,
    seed: int = 42,
) -> Dict[str, Dict[dt.date, float]]:
    """
    Genera trayectorias deterministas y realistas de precios diarios mediante
    Movimiento Browniano Geométrico (GBM) multivariado con correlación de mercado.

    Parámetros:
    -----------
    tickers: Lista de activos / tickers a simular.
    start_date: Fecha de inicio de la simulación.
    end_date: Fecha de fin de la simulación.
    seed: Semilla pseudoaleatoria para reproducibilidad numérica.

    Retorna:
    --------
    Dict[str, Dict[dt.date, float]]: Mapeo de ticker -> {fecha: precio}.
    """
    # 1. Extraer días hábiles de negociación (lunes a viernes)
    trading_dates: List[dt.date] = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() < 5:
            trading_dates.append(curr)
        curr += dt.timedelta(days=1)

    n_days = len(trading_dates)
    if n_days < 2:
        raise ValueError("El rango de fechas no contiene suficientes días hábiles (mínimo 2).")

    rng = np.random.default_rng(seed=seed)

    # 2. Calibración empírica según especie / clase de activo
    initial_prices: List[float] = []
    annual_drifts: List[float] = []
    annual_vols: List[float] = []

    for t in tickers:
        t_up = t.upper()
        if any(term in t_up for term in ["AL30", "GD30", "BONO", "TX", "LETRA"]):
            initial_prices.append(55.0)
            annual_drifts.append(0.08)
            annual_vols.append(0.10)
        elif any(term in t_up for term in ["GGAL", "YPF", "PAMP", "BMA", "EDN", "TXAR"]):
            initial_prices.append(2500.0)
            annual_drifts.append(0.18)
            annual_vols.append(0.32)
        elif any(term in t_up for term in ["AAPL", "SPY", "MSFT", "NVDA", "MELI", "KO", "TSLA"]):
            initial_prices.append(180.0)
            annual_drifts.append(0.14)
            annual_vols.append(0.22)
        else:
            initial_prices.append(100.0)
            annual_drifts.append(0.10)
            annual_vols.append(0.18)

    # 3. Factor de mercado sistémico (rho = 0.35)
    dt_step = 1.0 / 252.0
    rho = 0.35
    market_shocks = rng.standard_normal(n_days)

    prices_dict: Dict[str, Dict[dt.date, float]] = {t: {} for t in tickers}

    for i, t in enumerate(tickers):
        p0 = initial_prices[i]
        mu = annual_drifts[i]
        sigma = annual_vols[i]

        idiosyncratic_shocks = rng.standard_normal(n_days)
        z = np.sqrt(rho) * market_shocks + np.sqrt(1.0 - rho) * idiosyncratic_shocks

        # SDE de Black-Scholes: dS_t = mu*S_t*dt + sigma*S_t*dW_t
        log_drift = (mu - 0.5 * (sigma ** 2)) * dt_step
        log_shock = sigma * np.sqrt(dt_step) * z
        log_returns = log_drift + log_shock

        cum_log_returns = np.cumsum(log_returns)
        price_trajectory = p0 * np.exp(cum_log_returns)

        for day_idx, d in enumerate(trading_dates):
            prices_dict[t][d] = round(float(price_trajectory[day_idx]), 2)

    return prices_dict

