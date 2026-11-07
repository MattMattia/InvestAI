from dataclasses import dataclass
from enum import Enum

from app.domain.models.portfolio import InvestorProfile, Portfolio


class OrderSide(str, Enum):
    """Trading action suggested by the rebalancer."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class TargetAllocation:
    """
    Desired target percentage weight and tolerance band for an individual asset.
    Weights are expressed in percentage terms (0.0 to 100.0).
    If tolerance_band is None, it defaults to the profile's tolerance band (3%, 5%, 8%).
    """

    ticker: str
    target_weight: float  # Desired weight % (e.g. 25.0 = 25%)
    tolerance_band: float | None = (
        None  # Permitted +/- drift (e.g. 5.0 or 0.05). If None, inferred from profile.
    )

    def __post_init__(self) -> None:
        if self.target_weight < 0.0 or self.target_weight > 100.0:
            raise ValueError(
                f"target_weight debe estar entre 0.0 y 100.0. Recibido: {self.target_weight}"
            )
        if self.tolerance_band is not None and self.tolerance_band < 0.0:
            raise ValueError(
                f"tolerance_band debe ser no negativa. Recibido: {self.tolerance_band}"
            )


@dataclass(frozen=True)
class RebalanceOrder:
    """
    Actionable rebalancing order generated deterministically by the ToleranceBandRebalancer.
    """

    ticker: str
    side: OrderSide
    current_weight: float  # Current portfolio weight %
    target_weight: float  # Desired target weight %
    delta_weight: float  # Difference: target_weight - current_weight
    delta_amount: float  # Nominal cash amount to adjust in base currency
    estimated_shares: int  # Truncated integer shares to trade
    price_used: float  # Price per share used for computation
    justification: str  # Deterministic audit rationale


@dataclass(frozen=True)
class RebalancePlan:
    """
    Consolidated rebalance execution plan including liquidity validation.
    """

    orders: list[RebalanceOrder]
    total_buy_amount: float
    total_sell_amount: float
    net_cash_flow: float  # total_sell_amount - total_buy_amount
    available_cash: float
    is_liquidity_sufficient: bool
    liquidity_warning: str | None = None


class ToleranceBandRebalancer:
    """
    Deterministic Tolerance-band Rebalancing Engine.
    Only triggers rebalance transactions when an asset's allocation breaches
    its target allocation by more than the tolerance threshold:
        |current_weight - target_weight| > tolerance_band
    Default tolerance bands by investor profile:
        - CONSERVATIVE: ±3% (0.03)
        - MODERATE: ±5% (0.05)
        - AGGRESSIVE: ±8% (0.08)
    """

    PROFILE_DEFAULT_BANDS: dict[InvestorProfile, float] = {
        InvestorProfile.CONSERVATIVE: 3.0,
        InvestorProfile.MODERATE: 5.0,
        InvestorProfile.AGGRESSIVE: 8.0,
    }

    PROFILE_DEFAULT_BANDS_DECIMAL: dict[InvestorProfile, float] = {
        InvestorProfile.CONSERVATIVE: 0.03,
        InvestorProfile.MODERATE: 0.05,
        InvestorProfile.AGGRESSIVE: 0.08,
    }

    @classmethod
    def get_default_band(cls, profile: InvestorProfile, as_decimal: bool = False) -> float:
        if as_decimal:
            return cls.PROFILE_DEFAULT_BANDS_DECIMAL.get(profile, 0.05)
        return cls.PROFILE_DEFAULT_BANDS.get(profile, 5.0)

    @classmethod
    def calculate_orders(
        cls,
        portfolio: Portfolio,
        targets: list[TargetAllocation],
        prices: dict[str, float] | None = None,
        fx_ccl: float = 1.0,
        include_hold: bool = False,
    ) -> list[RebalanceOrder]:
        plan = cls.generate_plan(
            portfolio=portfolio,
            targets=targets,
            prices=prices,
            fx_ccl=fx_ccl,
            include_hold=include_hold,
        )
        return plan.orders

    @classmethod
    def generate_plan(
        cls,
        portfolio: Portfolio,
        targets: list[TargetAllocation],
        prices: dict[str, float] | None = None,
        fx_ccl: float = 1.0,
        include_hold: bool = False,
    ) -> RebalancePlan:
        prices_map = prices or {}
        total_port_val = portfolio.total_value_ars(fx_ccl=fx_ccl)
        current_weights = portfolio.get_holding_weights(fx_ccl=fx_ccl)

        profile = getattr(portfolio, "investor_profile", InvestorProfile.MODERATE)
        if isinstance(profile, str):
            try:
                profile = InvestorProfile(profile)
            except ValueError:
                profile = InvestorProfile.MODERATE

        default_band = cls.PROFILE_DEFAULT_BANDS.get(profile, 5.0)

        holdings_by_ticker = {h.asset.ticker: h for h in portfolio.holdings}

        orders: list[RebalanceOrder] = []
        total_buy_val = 0.0
        total_sell_val = 0.0

        for target in targets:
            ticker = target.ticker
            w_target = target.target_weight
            band = target.tolerance_band if target.tolerance_band is not None else default_band
            if 0.0 < band <= 0.20:
                band = band * 100.0

            w_current = current_weights.get(ticker, 0.0)
            delta_w = round(w_target - w_current, 2)
            abs_drift = abs(w_current - w_target)

            holding = holdings_by_ticker.get(ticker)
            price = prices_map.get(ticker)
            if price is None and holding is not None:
                price = holding.current_price
            if price is None or price <= 0.0:
                price = 1.0

            if abs_drift > band:
                if w_current > w_target:
                    side = OrderSide.SELL
                    delta_amt = round((w_target - w_current) / 100.0 * total_port_val, 2)
                    shares = int(abs(delta_amt) / price)
                    actual_trade_val = shares * price
                    total_sell_val += actual_trade_val
                    justification = (
                        f"Activo '{ticker}' sobreponderado ({w_current:.2f}% vs objetivo {w_target:.2f}%). "
                        f"Desvío de {abs_drift:.2f}% supera la banda de tolerancia (±{band:.2f}%). "
                        f"Vender {shares} nominales estimados."
                    )
                else:
                    side = OrderSide.BUY
                    delta_amt = round((w_target - w_current) / 100.0 * total_port_val, 2)
                    shares = int(abs(delta_amt) / price)
                    actual_trade_val = shares * price
                    total_buy_val += actual_trade_val
                    justification = (
                        f"Activo '{ticker}' subponderado ({w_current:.2f}% vs objetivo {w_target:.2f}%). "
                        f"Desvío de {abs_drift:.2f}% supera la banda de tolerancia (±{band:.2f}%). "
                        f"Comprar {shares} nominales estimados."
                    )

                orders.append(
                    RebalanceOrder(
                        ticker=ticker,
                        side=side,
                        current_weight=w_current,
                        target_weight=w_target,
                        delta_weight=delta_w,
                        delta_amount=delta_amt,
                        estimated_shares=shares,
                        price_used=price,
                        justification=justification,
                    )
                )
            elif include_hold:
                orders.append(
                    RebalanceOrder(
                        ticker=ticker,
                        side=OrderSide.HOLD,
                        current_weight=w_current,
                        target_weight=w_target,
                        delta_weight=delta_w,
                        delta_amount=0.0,
                        estimated_shares=0,
                        price_used=price,
                        justification=(
                            f"Activo '{ticker}' dentro de la banda de tolerancia "
                            f"(Desvío {abs_drift:.2f}% <= ±{band:.2f}%). Mantener posición sin operar."
                        ),
                    )
                )

        available_cash = portfolio.cash_balance_ars + (portfolio.cash_balance_usd * fx_ccl)
        total_liquidity_available = available_cash + total_sell_val
        is_sufficient = total_buy_val <= (total_liquidity_available + 1e-4)

        warning_msg: str | None = None
        if not is_sufficient:
            deficit = round(total_buy_val - total_liquidity_available, 2)
            warning_msg = (
                f"Alerta de Liquidez: Las compras sugeridas superan el efectivo disponible "
                f"sumado a las ventas estimadas. "
                f"Déficit de capital para ejecutar rebalanceo: ${deficit:,.2f}."
            )

        return RebalancePlan(
            orders=orders,
            total_buy_amount=round(total_buy_val, 2),
            total_sell_amount=round(total_sell_val, 2),
            net_cash_flow=round(total_sell_val - total_buy_val, 2),
            available_cash=round(available_cash, 2),
            is_liquidity_sufficient=is_sufficient,
            liquidity_warning=warning_msg,
        )
