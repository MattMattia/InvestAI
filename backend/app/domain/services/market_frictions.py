from dataclasses import dataclass
from typing import Tuple, Union

from app.domain.models.order import OrderSide


@dataclass(frozen=True)
class ExecutionCostBreakdown:
    """
    Immutable representation of granular execution costs and frictions for a trade.
    """
    side: OrderSide
    quantity: float
    nominal_price: float
    effective_price: float                # Execution price incorporating slippage
    nominal_amount: float                 # nominal_price * quantity
    effective_amount: float               # effective_price * quantity
    slippage_amount: float                # Direct financial impact of slippage (|effective - nominal|)
    alyc_commission: float                # Base broker commission
    alyc_vat: float                       # VAT (IVA 21%) applied on broker commission
    market_fees: float                    # Exchange rights and clearing fees (BYMA / CNV)
    total_frictions: float                # Total costs: slippage + commission + VAT + market fees
    net_total_amount: float               # Total cash outlay (BUY) or net cash received (SELL)
    effective_net_price_per_share: float  # net_total_amount / quantity
    friction_pct: float                   # (total_frictions / nominal_amount) * 100


def calculate_alyc_commission(
    amount: float,
    rate: float = 0.005,
    min_fee: float = 0.0,
    vat_rate: float = 0.21,
    include_vat: bool = True,
) -> Tuple[float, float]:
    """
    Calculates the ALyC broker commission and applicable VAT (IVA).

    Parameters:
        amount: Traded volume in base currency (>= 0).
        rate: Broker commission percentage rate (default 0.5% = 0.005).
        min_fee: Minimum fixed commission amount.
        vat_rate: Value Added Tax rate (default 21% = 0.21 in Argentina).
        include_vat: Whether to compute VAT on the broker fee.

    Returns:
        Tuple of (base_commission, vat_amount).
    """
    if amount < 0.0:
        raise ValueError("El monto operado no puede ser negativo.")
    if rate < 0.0 or rate >= 1.0:
        raise ValueError("La tasa de comisión de ALyC debe estar en el intervalo [0.0, 1.0).")
    if min_fee < 0.0:
        raise ValueError("La comisión mínima no puede ser negativa.")
    if vat_rate < 0.0:
        raise ValueError("La alícuota de IVA no puede ser negativa.")

    raw_fee = amount * rate
    base_commission = max(min_fee, raw_fee)
    vat = base_commission * vat_rate if include_vat else 0.0

    return round(base_commission, 4), round(vat, 4)


def calculate_market_fees(
    amount: float,
    fee_rate: float = 0.0009,
) -> float:
    """
    Calculates market exchange duties and clearing house fees (e.g. BYMA & CNV).

    Parameters:
        amount: Traded volume in base currency (>= 0).
        fee_rate: Combined market fee rate (default 0.09% = 0.0009 for BYMA equities/CEDEARs).

    Returns:
        Market fee amount.
    """
    if amount < 0.0:
        raise ValueError("El monto operado no puede ser negativo.")
    if fee_rate < 0.0 or fee_rate >= 1.0:
        raise ValueError("La tasa de derechos de mercado debe estar en el intervalo [0.0, 1.0).")

    return round(amount * fee_rate, 4)


def calculate_slippage(
    price: float,
    quantity: float,
    side: Union[OrderSide, str],
    slippage_rate: float = 0.001,
) -> Tuple[float, float]:
    """
    Computes effective execution price and slippage monetary cost.
    For BUY orders: slippage shifts execution price upwards (adverse selection).
    For SELL orders: slippage shifts execution price downwards.

    Parameters:
        price: Nominal quoted price (> 0).
        quantity: Order quantity (> 0).
        side: OrderSide.BUY or OrderSide.SELL.
        slippage_rate: Proportional price impact (default 0.1% = 0.001).

    Returns:
        Tuple of (effective_price, slippage_monetary_amount).
    """
    if price <= 0.0:
        raise ValueError("El precio debe ser estrictamente positivo (> 0).")
    if quantity <= 0.0:
        raise ValueError("La cantidad debe ser estrictamente positiva (> 0).")
    if slippage_rate < 0.0 or slippage_rate >= 1.0:
        raise ValueError("La tasa de slippage debe estar en el intervalo [0.0, 1.0).")

    side_enum = OrderSide(side) if isinstance(side, str) else side

    if side_enum == OrderSide.BUY:
        effective_price = price * (1.0 + slippage_rate)
    elif side_enum == OrderSide.SELL:
        effective_price = price * (1.0 - slippage_rate)
    else:
        raise ValueError(f"OrderSide no soportado para cálculo de slippage: {side}")

    nominal_amt = price * quantity
    effective_amt = effective_price * quantity
    slippage_amt = abs(effective_amt - nominal_amt)

    return round(effective_price, 4), round(slippage_amt, 4)


def calculate_net_execution_cost(
    quantity: float,
    price: float,
    side: Union[OrderSide, str],
    alyc_rate: float = 0.005,
    min_alyc_fee: float = 0.0,
    market_fee_rate: float = 0.0009,
    slippage_rate: float = 0.001,
    include_vat: bool = True,
    vat_rate: float = 0.21,
) -> ExecutionCostBreakdown:
    """
    Pure deterministic calculation of total execution frictions and net financial outlay.

    - For BUY orders:
      net_total_amount = effective_amount + alyc_commission + alyc_vat + market_fees
      (Buyer spends more cash than nominal value).

    - For SELL orders:
      net_total_amount = effective_amount - (alyc_commission + alyc_vat + market_fees)
      (Seller receives less cash than nominal value).
    """
    if quantity <= 0.0:
        raise ValueError("La cantidad de la orden debe ser estrictamente positiva (> 0).")
    if price <= 0.0:
        raise ValueError("El precio de la orden debe ser estrictamente positivo (> 0).")

    side_enum = OrderSide(side) if isinstance(side, str) else side

    # 1. Slippage and effective price
    effective_price, slippage_amount = calculate_slippage(
        price=price,
        quantity=quantity,
        side=side_enum,
        slippage_rate=slippage_rate,
    )

    nominal_amount = round(price * quantity, 4)
    effective_amount = round(effective_price * quantity, 4)

    # 2. Broker commission on effective execution value
    alyc_comm, alyc_vat = calculate_alyc_commission(
        amount=effective_amount,
        rate=alyc_rate,
        min_fee=min_alyc_fee,
        vat_rate=vat_rate,
        include_vat=include_vat,
    )

    # 3. Market and clearing fees (BYMA / CNV)
    market_fees = calculate_market_fees(
        amount=effective_amount,
        fee_rate=market_fee_rate,
    )

    # 4. Total frictions and net outlay
    total_frictions = round(slippage_amount + alyc_comm + alyc_vat + market_fees, 4)

    if side_enum == OrderSide.BUY:
        net_total = round(effective_amount + alyc_comm + alyc_vat + market_fees, 4)
    else:
        net_total = round(effective_amount - (alyc_comm + alyc_vat + market_fees), 4)

    effective_net_price = round(net_total / quantity, 4)
    friction_pct = round((total_frictions / nominal_amount) * 100.0, 4) if nominal_amount > 0 else 0.0

    return ExecutionCostBreakdown(
        side=side_enum,
        quantity=quantity,
        nominal_price=round(price, 4),
        effective_price=effective_price,
        nominal_amount=nominal_amount,
        effective_amount=effective_amount,
        slippage_amount=slippage_amount,
        alyc_commission=alyc_comm,
        alyc_vat=alyc_vat,
        market_fees=market_fees,
        total_frictions=total_frictions,
        net_total_amount=net_total,
        effective_net_price_per_share=effective_net_price,
        friction_pct=friction_pct,
    )
