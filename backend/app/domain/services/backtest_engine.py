import datetime as dt
from typing import Any

import numpy as np

from app.domain.models.calendar import MarketExchange
from app.domain.models.order import Order, OrderSide, OrderType
from app.domain.services.backtest_metrics import calculate_performance_metrics
from app.domain.services.calendar_service import MarketCalendarService
from app.domain.services.market_frictions import calculate_net_execution_cost
from app.domain.services.portfolio_optimizer import (
    minimum_variance_portfolio,
    risk_parity_portfolio,
)
from app.domain.services.quantitative_risk import ledoit_wolf_covariance
from app.schemas.backtest import (
    BacktestConfig,
    BacktestResult,
    DailySnapshot,
    RebalanceFrequency,
)
from app.schemas.market_data import MarketBarDTO


def _parse_date(d: dt.date | dt.datetime | str) -> dt.date:
    """Convierte de forma segura strings, datetimes o dates a datetime.date."""
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


class BacktestEngine:
    """
    Motor institucional de simulación y backtesting histórico de carteras.

    Integra de forma determinista:
    - Sincronización y control de calendario bursátil (Módulo 1).
    - Optimización cuantitativa con contracción de covarianza Ledoit-Wolf (Módulo 2).
    - Máquina de Estados Finitos (FSM) estricta para órdenes (Módulo 4).
    - Motor de fricciones de mercado: comisiones ALyC + IVA, aranceles BYMA y slippage (Módulo 4).
    - Métricas financieras consolidadas: CAGR, Volatilidad, Sharpe, Sortino, MDD, Calmar (Módulo 5).
    """

    def __init__(
        self,
        config: BacktestConfig,
        calendar_service: MarketCalendarService | None = None,
    ) -> None:
        self.config = config
        self.calendar_service = calendar_service or MarketCalendarService()

    def run(
        self,
        prices_data: dict[str, dict[dt.date | str, float]],
    ) -> BacktestResult:
        """
        Ejecuta la simulación temporal día a día sobre el universo de precios provisto.

        Parámetros:
            prices_data: Mapeo de Ticker -> {Fecha: Precio_Ajustado}.

        Retorna:
            BacktestResult con snapshots diarios, historial de órdenes y métricas consolidadas.
        """
        start_date = _parse_date(self.config.start_date)
        end_date = _parse_date(self.config.end_date)

        if start_date > end_date:
            raise ValueError(
                f"start_date ({start_date}) no puede ser posterior a end_date ({end_date})."
            )

        # 1. Normalización del diccionario de precios
        normalized_prices: dict[str, dict[dt.date, float]] = {}
        for ticker, series in prices_data.items():
            t_norm = ticker.strip().upper()
            normalized_prices[t_norm] = {
                _parse_date(d): float(p)
                for d, p in series.items()
                if p is not None and float(p) > 0.0
            }

        # 2. Extracción de días hábiles de cotización dentro del rango
        candidate_dates: set[dt.date] = set()
        for t in self.config.tickers:
            if t in normalized_prices:
                candidate_dates.update(normalized_prices[t].keys())

        # Filtrar fechas dentro del rango [start_date, end_date] y días hábiles (lunes a viernes)
        trading_dates = sorted(
            [d for d in candidate_dates if start_date <= d <= end_date and d.weekday() < 5]
        )

        # Si no hay fechas en el diccionario de precios, generar días hábiles de calendario
        if not trading_dates:
            curr = start_date
            while curr <= end_date:
                if self.calendar_service.is_market_open(MarketExchange.BYMA, curr):
                    trading_dates.append(curr)
                curr += dt.timedelta(days=1)

        # 3. Inicialización del estado de la cartera
        cash: float = float(self.config.initial_capital)
        holdings: dict[str, float] = {t: 0.0 for t in self.config.tickers}
        latest_prices: dict[str, float] = {}
        total_frictions: float = 0.0
        orders_history: list[dict[str, Any]] = []
        snapshots: list[DailySnapshot] = []

        peak_nav: float = cash
        prev_portfolio_value: float = cash
        prev_date: dt.date | None = None

        # Historial de precios observados por fecha para cálculo de retornos en rebalanceo
        price_history: dict[str, dict[dt.date, float]] = {t: {} for t in self.config.tickers}

        # 4. Bucle temporal día a día
        for idx, current_date in enumerate(trading_dates):
            # 4.1 Actualizar y forward-fill precios del día
            for t in self.config.tickers:
                if t in normalized_prices and current_date in normalized_prices[t]:
                    latest_prices[t] = normalized_prices[t][current_date]
                # Registrar en historial acumulado si tenemos precio
                if t in latest_prices:
                    price_history[t][current_date] = latest_prices[t]

            # 4.2 Determinar si corresponde rebalancear hoy
            should_rebalance = self._should_rebalance(
                current_date=current_date,
                prev_date=prev_date,
                is_first_day=(idx == 0),
                frequency=self.config.rebalance_frequency,
            )

            # 4.3 Ejecutar rebalanceo si corresponde y hay precios disponibles
            priced_tickers = [
                t for t in self.config.tickers if t in latest_prices and latest_prices[t] > 0.0
            ]
            if should_rebalance and priced_tickers:
                target_weights = self._calculate_target_weights(
                    tickers=priced_tickers,
                    price_history=price_history,
                    current_date=current_date,
                )

                # Calcular NAV disponible previo al rebalanceo
                current_nav = cash + sum(holdings[t] * latest_prices[t] for t in priced_tickers)

                # Ejecutar rebalanceo con FSM y fricciones
                cash, holdings, total_frictions, executed_orders = self._execute_rebalance(
                    current_nav=current_nav,
                    cash=cash,
                    holdings=holdings,
                    latest_prices=latest_prices,
                    target_weights=target_weights,
                    total_frictions=total_frictions,
                )
                orders_history.extend(executed_orders)

            # 4.4 Computar NAV del día
            portfolio_value = cash + sum(
                holdings[t] * latest_prices[t] for t in self.config.tickers if t in latest_prices
            )
            peak_nav = max(peak_nav, portfolio_value)

            # Drawdown acumulado respecto al pico histórico (<= 0.0)
            drawdown = (portfolio_value - peak_nav) / peak_nav if peak_nav > 0.0 else 0.0

            # Retorno diario respecto a la jornada anterior
            if idx == 0:
                daily_return = (
                    (portfolio_value - self.config.initial_capital) / self.config.initial_capital
                    if self.config.initial_capital > 0.0
                    else 0.0
                )
            else:
                daily_return = (
                    (portfolio_value - prev_portfolio_value) / prev_portfolio_value
                    if prev_portfolio_value > 0.0
                    else 0.0
                )

            # Registrar snapshot diario inmutable
            snapshot = DailySnapshot(
                date=current_date,
                portfolio_value=round(portfolio_value, 2),
                cash=round(cash, 2),
                holdings={t: round(q, 4) for t, q in holdings.items() if q > 0.0},
                daily_return=round(daily_return, 6),
                drawdown=round(min(drawdown, 0.0), 6),
            )
            snapshots.append(snapshot)

            prev_portfolio_value = portfolio_value
            prev_date = current_date

        # 5. Consolidación de métricas de rendimiento y resultado final
        portfolio_values = [s.portfolio_value for s in snapshots]
        if not portfolio_values:
            portfolio_values = [self.config.initial_capital]

        metrics = calculate_performance_metrics(
            portfolio_values=portfolio_values,
            risk_free_rate=self.config.risk_free_rate,
            total_frictions=total_frictions,
            periods_per_year=252,
        )

        return BacktestResult(
            config=self.config,
            metrics=metrics,
            snapshots=snapshots,
            orders=orders_history,
        )

    def _should_rebalance(
        self,
        current_date: dt.date,
        prev_date: dt.date | None,
        is_first_day: bool,
        frequency: RebalanceFrequency,
    ) -> bool:
        """Determina si la fecha actual corresponde a un hito de rebalanceo."""
        if is_first_day:
            return True

        if prev_date is None:
            return False

        if frequency == RebalanceFrequency.DAILY:
            return True
        elif frequency == RebalanceFrequency.WEEKLY:
            return current_date.isocalendar()[:2] != prev_date.isocalendar()[:2]
        elif frequency == RebalanceFrequency.MONTHLY:
            return (current_date.year, current_date.month) != (prev_date.year, prev_date.month)
        elif frequency == RebalanceFrequency.QUARTERLY:
            curr_q = (current_date.year, (current_date.month - 1) // 3)
            prev_q = (prev_date.year, (prev_date.month - 1) // 3)
            return curr_q != prev_q

        return False

    def _calculate_target_weights(
        self,
        tickers: list[str],
        price_history: dict[str, dict[dt.date, float]],
        current_date: dt.date,
        lookback_window: int = 60,
        min_observations: int = 15,
    ) -> dict[str, float]:
        """
        Calcula las ponderaciones óptimas de la cartera mediante los algoritmos del Módulo 2.
        Aplica fallback determinista a equiponderación (1/N) si el historial es insuficiente.
        """
        n_assets = len(tickers)
        if n_assets == 0:
            return {}
        if n_assets == 1:
            return {tickers[0]: 1.0}

        # [DEFENSE: NUM-03] Extract union of all observed trading dates across tickers
        # to prevent a newly listed asset with short history from collapsing the lookback window of mature assets.
        all_dates_set: set[dt.date] = set()
        for t in tickers:
            all_dates_set.update(price_history[t].keys())

        sorted_dates = sorted([d for d in all_dates_set if d <= current_date])

        if len(sorted_dates) > lookback_window:
            sorted_dates = sorted_dates[-lookback_window:]

        # Si no hay observaciones suficientes en el mercado general, fallback a 1/N
        if len(sorted_dates) < min_observations:
            equal_weight = 1.0 / n_assets
            return {t: equal_weight for t in tickers}

        # Construir matriz de precios alineada con forward-fill y zero-imputation previa a la fecha de inicio
        n_periods = len(sorted_dates)
        aligned_prices = np.zeros((n_periods, n_assets), dtype=np.float64)

        for col_idx, t in enumerate(tickers):
            history_t = price_history[t]
            t_dates = sorted(
                [d for d in history_t.keys() if d in all_dates_set and d <= current_date]
            )
            first_known_price = history_t[t_dates[0]] if t_dates else 100.0
            last_price = first_known_price

            for row_idx, d in enumerate(sorted_dates):
                if d in history_t and history_t[d] > 0.0:
                    last_price = history_t[d]
                aligned_prices[row_idx, col_idx] = last_price

        # Retornos discretos R_t = (P_t - P_{t-1}) / P_{t-1} con protección contra denominador nulo
        denom = aligned_prices[:-1]
        valid_denom = denom > 0.0
        returns_matrix = np.zeros((n_periods - 1, n_assets), dtype=np.float64)
        np.divide(
            aligned_prices[1:] - denom,
            denom,
            out=returns_matrix,
            where=valid_denom,
        )

        # Validar estabilidad numérica de los retornos
        if (
            not np.all(np.isfinite(returns_matrix))
            or returns_matrix.shape[0] < min_observations - 1
        ):
            return {t: 1.0 / n_assets for t in tickers}

        try:
            # Contracción de covarianza de Ledoit-Wolf (Módulo 2)
            cov = ledoit_wolf_covariance(returns_matrix)

            method = getattr(self.config, "optimization_method", "MINIMUM_VARIANCE")
            if method == "RISK_PARITY":
                weights = risk_parity_portfolio(cov)
            elif method == "EQUAL_WEIGHTS":
                weights = np.full(n_assets, 1.0 / n_assets, dtype=np.float64)
            else:
                weights = minimum_variance_portfolio(cov)

            return {t: float(w) for t, w in zip(tickers, weights, strict=False)}
        except Exception:
            # Fallback seguro ante singularidades numéricas
            return {t: 1.0 / n_assets for t in tickers}

    def _execute_rebalance(
        self,
        current_nav: float,
        cash: float,
        holdings: dict[str, float],
        latest_prices: dict[str, float],
        target_weights: dict[str, float],
        total_frictions: float,
    ) -> tuple[float, dict[str, float], float, list[dict[str, Any]]]:
        """
        Ejecuta las operaciones de compra y venta requeridas para alcanzar las ponderaciones objetivo,
        gestionando el ciclo de órdenes con la FSM y aplicando fricciones de mercado.
        """
        frictions = self.config.friction_config
        executed_orders: list[dict[str, Any]] = []
        updated_holdings = dict(holdings)

        # 1. Calcular delta de unidades nominales enteras por activo
        deltas: dict[str, float] = {}
        for t, weight in target_weights.items():
            price = latest_prices.get(t, 0.0)
            if price <= 0.0:
                deltas[t] = 0.0
                continue
            target_amount = current_nav * weight
            target_qty = float(int(target_amount // price))
            current_qty = updated_holdings.get(t, 0.0)
            deltas[t] = target_qty - current_qty

        # 2. EJECUTAR VENTAS PRIMERO para liberar liquidez en efectivo
        sell_tickers = [t for t, d in deltas.items() if d < 0.0]
        for t in sell_tickers:
            desired_sell = abs(deltas[t])
            current_held = updated_holdings.get(t, 0.0)
            qty_to_sell = min(desired_sell, current_held)

            if qty_to_sell <= 0.0:
                continue

            price = latest_prices[t]
            order = Order(
                portfolio_id="backtest",
                ticker=t,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=qty_to_sell,
                price=price,
            )

            # Ciclo FSM: CREATED -> VALIDATED -> SUBMITTED
            order.validate()
            order.submit()

            # Cálculo de fricciones
            breakdown = calculate_net_execution_cost(
                quantity=qty_to_sell,
                price=price,
                side=OrderSide.SELL,
                alyc_rate=frictions.alyc_commission_rate,
                min_alyc_fee=frictions.min_commission_fee,
                market_fee_rate=frictions.market_fee_rate,
                slippage_rate=frictions.slippage_rate,
                include_vat=frictions.include_vat,
                vat_rate=frictions.vat_rate,
            )

            # FSM: SUBMITTED -> FILLED
            order.fill(filled_qty=qty_to_sell, filled_price=breakdown.effective_price)

            # [DEFENSE: NUM-04] Ensure cash never decreases on liquidation of residual positions
            cash += max(0.0, breakdown.net_total_amount)
            updated_holdings[t] -= qty_to_sell
            total_frictions += breakdown.total_frictions
            executed_orders.append(order.model_dump(mode="json"))

        # 3. EJECUTAR COMPRAS con el efectivo disponible
        buy_tickers = [t for t, d in deltas.items() if d > 0.0]
        for t in buy_tickers:
            desired_buy = deltas[t]
            price = latest_prices[t]

            # Estimar costo unitario por acción incluyendo comisiones e impacto
            unit_cost = price * (
                1.0
                + frictions.slippage_rate
                + (
                    frictions.alyc_commission_rate
                    * (1.0 + (frictions.vat_rate if frictions.include_vat else 0.0))
                )
                + frictions.market_fee_rate
            )

            if unit_cost <= 0.0 or cash <= 0.0:
                continue

            # Ajustar cantidad comprable a la liquidez efectiva de caja
            max_affordable = int(cash // unit_cost)
            qty_to_buy = float(min(int(desired_buy), max_affordable))

            if qty_to_buy <= 0.0:
                continue

            order = Order(
                portfolio_id="backtest",
                ticker=t,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=qty_to_buy,
                price=price,
            )

            order.validate()
            order.submit()

            breakdown = calculate_net_execution_cost(
                quantity=qty_to_buy,
                price=price,
                side=OrderSide.BUY,
                alyc_rate=frictions.alyc_commission_rate,
                min_alyc_fee=frictions.min_commission_fee,
                market_fee_rate=frictions.market_fee_rate,
                slippage_rate=frictions.slippage_rate,
                include_vat=frictions.include_vat,
                vat_rate=frictions.vat_rate,
            )

            if breakdown.net_total_amount <= cash:
                order.fill(filled_qty=qty_to_buy, filled_price=breakdown.effective_price)
                cash -= breakdown.net_total_amount
                updated_holdings[t] += qty_to_buy
                total_frictions += breakdown.total_frictions
                executed_orders.append(order.model_dump(mode="json"))
            else:
                order.reject("Efectivo insuficiente tras el cómputo final de fricciones.")
                executed_orders.append(order.model_dump(mode="json"))

        return cash, updated_holdings, total_frictions, executed_orders


def bars_to_price_history(
    bars_by_ticker: dict[str, list[MarketBarDTO]],
) -> dict[str, dict[dt.date, float]]:
    """
    Convierte series históricas de barras canónicas (MarketBarDTO) a la estructura
    matricial de precios de cierre requerida por el motor de backtesting (BacktestEngine.run).

    Parámetros:
    -----------
    bars_by_ticker: Mapeo de símbolo (ticker) a lista de barras canónicas OHLCV.

    Retorna:
    --------
    Dict[str, Dict[dt.date, float]]: Estructura {ticker: {fecha: precio_cierre_float}}.
    """
    price_history: dict[str, dict[dt.date, float]] = {}
    for raw_ticker, bars in bars_by_ticker.items():
        ticker = raw_ticker.strip().upper()
        ticker_prices: dict[dt.date, float] = {}
        for bar in bars:
            d = bar.timestamp.date() if hasattr(bar.timestamp, "date") else bar.timestamp
            ticker_prices[d] = float(bar.close)
        price_history[ticker] = ticker_prices
    return price_history
