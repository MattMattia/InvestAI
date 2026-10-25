"""
Dynamic Tolerance-Band Portfolio Rebalancing Engine (Module 7.3 - Phases 1 & 2).

Implements:
- Absolute, Relative, and Dynamic Volatility-Scaled tolerance corridors
  ($w_i^* \\pm \\theta_i$) with configurable minimum/maximum half-width bounds.
- Dynamic ATR Volatility Band Calibration (`calibrate_specs_from_indicators`)
  bridging `TechnicalIndicatorsSnapshot` (`atr_14 / close`) from Module 7.1.
- Full-to-Target (`FULL_TO_TARGET`) and Minimum-Turnover Band-Boundary
  (`TO_BAND_BOUNDARY`) rebalancing modes, plus Excess-Cash Inflow Deployment
  (`deploy_excess_cash_when_inside_bands`).
- Self-Financing Liquidity Waterfall (Sell-Before-Buy) guaranteeing zero cash
  overdraft (`projected_ending_cash >= 0`), Post-Trade Weight/Drift Projections,
  and Realized PnL Estimation (`estimated_realized_pnl`).
- Direct integration with `PortfolioMarkToMarketReport` (Module 7.2) and
  idempotent two-phase Order FSM execution batching (`RebalanceFSMExecutionBatch`).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from enum import Enum
import hashlib
import math
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from app.domain.services.portfolio_valuation_service import PortfolioMarkToMarketReport
from app.domain.services.signal_generator import OrderFSMIntent
from app.domain.services.technical_indicators import TechnicalIndicatorsSnapshot
from app.schemas.envelope import BaseSchema

# ============================================================================
# Quantitative Constants & Defensive Boundaries
# ============================================================================
REBALANCE_QUANTIZE: Decimal = Decimal("0.0001")
INTERMEDIATE_DECIMAL_PRECISION: int = 50
MAX_REBALANCE_ASSETS: int = 5_000


# ============================================================================
# Typed Domain Exception Hierarchy
# ============================================================================
class RebalancingError(Exception):
    """Base domain exception for tolerance-band portfolio rebalancing."""


class InvalidTargetAllocationError(RebalancingError):
    """Raised when target weights, cash buffers, or asset specifications are invalid."""


class InvalidToleranceBandConfigError(RebalancingError):
    """Raised when tolerance band configuration parameters are invalid or inconsistent."""


class MissingRebalancePriceError(RebalancingError):
    """Raised when a required market/reference price is missing or non-positive."""


class InsufficientLiquidityForRebalanceError(RebalancingError):
    """Raised when total portfolio net worth is non-positive or insufficient to rebalance."""


# ============================================================================
# Typed Enums
# ============================================================================
class BandType(str, Enum):
    """Tolerance corridor width calculation mode."""

    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"
    DYNAMIC_VOLATILITY = "DYNAMIC_VOLATILITY"


class RebalanceMode(str, Enum):
    """Destination weight policy when a tolerance band is breached."""

    FULL_TO_TARGET = "FULL_TO_TARGET"
    TO_BAND_BOUNDARY = "TO_BAND_BOUNDARY"


class BandBreachDirection(str, Enum):
    """Direction of tolerance corridor breach for an evaluated asset."""

    NONE = "NONE"
    UPPER = "UPPER"
    LOWER = "LOWER"


# ============================================================================
# Canonical Quantization & Validation Helpers
# ============================================================================
def _quantize(value: Decimal) -> Decimal:
    """
    Quantize a `Decimal` to 4 decimal places (`0.0001`, `ROUND_HALF_UP`)
    under a 50-digit precision context, normalizing `-0.0000` to `Decimal("0.0000")`.
    """
    with localcontext() as ctx:
        ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
        quantized = value.quantize(REBALANCE_QUANTIZE, rounding=ROUND_HALF_UP)
    if quantized == Decimal("0"):
        return Decimal("0.0000")
    return quantized


def _coerce_finite_decimal(value: Any, field_name: str) -> Decimal:
    """Validate and convert a value to a finite `Decimal`, strictly rejecting booleans."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Boolean or None is not permitted for '{field_name}'.")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float is not permitted for '{field_name}'.")
        dec = Decimal(str(value))
    elif isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 64:
            raise ValueError(f"Empty or oversized numeric string for '{field_name}'.")
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid Decimal string for '{field_name}'.") from exc
    else:
        raise ValueError(
            f"Unsupported type '{type(value).__name__}' for '{field_name}'."
        )

    if not dec.is_finite():
        raise ValueError(f"Non-finite Decimal is not permitted for '{field_name}'.")
    return dec


def _validate_clean_ticker(value: Any) -> str:
    """Normalize and validate ticker strings, rejecting control characters and booleans."""
    if not isinstance(value, str) or isinstance(value, bool):
        raise ValueError("ticker must be a valid string.")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("Control characters are not permitted in ticker.")
    cleaned = value.strip().upper()
    if not cleaned or len(cleaned) > 20:
        raise ValueError("ticker must be between 1 and 20 characters after trimming.")
    return cleaned


def _validate_clean_currency(value: Any) -> str:
    """Normalize and validate currency codes ('ARS' or 'USD')."""
    if not isinstance(value, str) or isinstance(value, bool):
        raise ValueError("base_currency must be a valid string.")
    cleaned = value.strip().upper()
    if cleaned not in ("ARS", "USD"):
        raise ValueError(
            f"Unsupported base_currency '{cleaned}': must be 'ARS' or 'USD'."
        )
    return cleaned


# ============================================================================
# Immutable DTO Contracts
# ============================================================================
class RebalancePositionInput(BaseSchema):
    """
    Immutable current holding position input for tolerance-band evaluation,
    optionally carrying `avg_cost_price` for realized PnL estimation on sales.
    """

    ticker: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(ge=Decimal("0"))
    market_price: Decimal = Field(gt=Decimal("0"))
    avg_cost_price: Decimal | None = Field(default=None, ge=Decimal("0"))

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator("quantity", "market_price", mode="before")
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator("avg_cost_price", mode="before")
    @classmethod
    def _validate_optional_avg_cost(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, "avg_cost_price")


class AssetTargetBandSpec(BaseSchema):
    """
    Immutable target weight and tolerance corridor specification for an asset.
    """

    ticker: str = Field(min_length=1, max_length=20)
    target_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    reference_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    absolute_tolerance_override: Decimal | None = Field(
        default=None, gt=Decimal("0"), le=Decimal("1.0000")
    )
    relative_tolerance_override: Decimal | None = Field(
        default=None, gt=Decimal("0"), le=Decimal("1.0000")
    )
    volatility_multiplier: Decimal = Field(
        default=Decimal("1.0000"), gt=Decimal("0"), le=Decimal("5.0000")
    )

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator("target_weight", "volatility_multiplier", mode="before")
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator(
        "reference_price",
        "absolute_tolerance_override",
        "relative_tolerance_override",
        mode="before",
    )
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, str(info.field_name))


class ToleranceBandRebalancerConfig(BaseSchema):
    """
    Immutable configuration governing tolerance corridor geometry, rebalance
    destination mode, transaction commissions, lot rounding, cash buffer, and
    excess-cash deployment.
    """

    band_type: BandType = BandType.RELATIVE
    default_absolute_tolerance: Decimal = Field(
        default=Decimal("0.0500"), gt=Decimal("0"), le=Decimal("0.5000")
    )
    default_relative_tolerance: Decimal = Field(
        default=Decimal("0.2000"), gt=Decimal("0"), le=Decimal("0.9000")
    )
    min_band_half_width: Decimal = Field(
        default=Decimal("0.0050"), gt=Decimal("0"), le=Decimal("0.2000")
    )
    max_band_half_width: Decimal = Field(
        default=Decimal("0.2500"), gt=Decimal("0"), le=Decimal("0.5000")
    )
    rebalance_mode: RebalanceMode = RebalanceMode.FULL_TO_TARGET
    commission_bps: Decimal = Field(
        default=Decimal("0.0000"), ge=Decimal("0"), le=Decimal("500.0000")
    )
    min_trade_notional: Decimal = Field(default=Decimal("1.0000"), ge=Decimal("0"))
    allow_fractional_shares: bool = True
    cash_buffer_weight: Decimal = Field(
        default=Decimal("0.0000"), ge=Decimal("0"), lt=Decimal("1.0000")
    )
    liquidate_unlisted_holdings: bool = True
    deploy_excess_cash_when_inside_bands: bool = False

    @field_validator(
        "default_absolute_tolerance",
        "default_relative_tolerance",
        "min_band_half_width",
        "max_band_half_width",
        "commission_bps",
        "min_trade_notional",
        "cash_buffer_weight",
        mode="before",
    )
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator(
        "allow_fractional_shares",
        "liquidate_unlisted_holdings",
        "deploy_excess_cash_when_inside_bands",
        mode="before",
    )
    @classmethod
    def _validate_strict_booleans(cls, v: Any, info: Any) -> bool:
        if not isinstance(v, bool):
            raise ValueError(f"'{info.field_name}' must be a strict boolean.")
        return v

    @model_validator(mode="after")
    def _enforce_half_width_ordering(self) -> ToleranceBandRebalancerConfig:
        if self.min_band_half_width > self.max_band_half_width:
            raise ValueError(
                f"min_band_half_width ({self.min_band_half_width}) cannot exceed "
                f"max_band_half_width ({self.max_band_half_width})."
            )
        return self


class AssetBandEvaluation(BaseSchema):
    """
    Immutable per-asset corridor evaluation, pre-trade drift measurement,
    destination weight, and projected post-trade state after rebalance execution.
    """

    ticker: str = Field(min_length=1, max_length=20)
    current_quantity: Decimal = Field(ge=Decimal("0"))
    market_price: Decimal = Field(gt=Decimal("0"))
    current_value: Decimal = Field(ge=Decimal("0"))
    current_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    target_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    lower_band: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    upper_band: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    drift_weight: Decimal
    is_breached: bool
    breach_direction: BandBreachDirection
    destination_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    post_trade_quantity: Decimal = Field(ge=Decimal("0"))
    post_trade_value: Decimal = Field(ge=Decimal("0"))
    post_trade_weight: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    post_trade_drift_weight: Decimal

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator(
        "current_quantity",
        "market_price",
        "current_value",
        "current_weight",
        "target_weight",
        "lower_band",
        "upper_band",
        "drift_weight",
        "destination_weight",
        "post_trade_quantity",
        "post_trade_value",
        "post_trade_weight",
        "post_trade_drift_weight",
        mode="before",
    )
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))


class RebalanceTradeOrder(BaseSchema):
    """
    Immutable rebalance trade order with gross notional, estimated commission,
    net cash impact, estimated realized PnL, and transactional `OrderFSMIntent`.
    """

    ticker: str = Field(min_length=1, max_length=20)
    side: Literal["SELL", "BUY"]
    quantity: Decimal = Field(gt=Decimal("0"))
    execution_price: Decimal = Field(gt=Decimal("0"))
    gross_amount: Decimal = Field(gt=Decimal("0"))
    estimated_commission: Decimal = Field(ge=Decimal("0"))
    net_cash_impact: Decimal
    estimated_realized_pnl: Decimal | None = None
    order_intent: OrderFSMIntent

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator(
        "quantity",
        "execution_price",
        "gross_amount",
        "estimated_commission",
        "net_cash_impact",
        mode="before",
    )
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator("estimated_realized_pnl", mode="before")
    @classmethod
    def _validate_optional_realized_pnl(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, "estimated_realized_pnl")

    @model_validator(mode="after")
    def _enforce_order_accounting_and_fsm_sync(self) -> RebalanceTradeOrder:
        if self.order_intent.ticker != self.ticker:
            raise ValueError(
                f"order_intent.ticker ('{self.order_intent.ticker}') must match "
                f"order ticker ('{self.ticker}')."
            )
        if self.order_intent.side != self.side:
            raise ValueError(
                f"order_intent.side ('{self.order_intent.side}') must match "
                f"order side ('{self.side}')."
            )
        if self.order_intent.reference_price != self.execution_price:
            raise ValueError(
                f"order_intent.reference_price ({self.order_intent.reference_price}) "
                f"must equal execution_price ({self.execution_price})."
            )

        if self.side == "SELL":
            expected_impact = self.gross_amount - self.estimated_commission
            if self.net_cash_impact != expected_impact:
                raise ValueError(
                    f"SELL net_cash_impact ({self.net_cash_impact}) must equal "
                    f"gross_amount - estimated_commission ({expected_impact})."
                )
        elif self.side == "BUY":
            expected_impact = -(self.gross_amount + self.estimated_commission)
            if self.net_cash_impact != expected_impact:
                raise ValueError(
                    f"BUY net_cash_impact ({self.net_cash_impact}) must equal "
                    f"-(gross_amount + estimated_commission) ({expected_impact})."
                )
            if self.estimated_realized_pnl is None:
                object.__setattr__(self, "estimated_realized_pnl", Decimal("0.0000"))
            elif self.estimated_realized_pnl != Decimal("0.0000"):
                raise ValueError(
                    f"BUY order estimated_realized_pnl must be 0.0000 (got {self.estimated_realized_pnl})."
                )
        return self


class ToleranceBandRebalanceReport(BaseSchema):
    """
    Immutable consolidated tolerance-band rebalancing report enforcing exact
    cash accounting closure, post-trade net worth identity, realized PnL
    aggregation, zero overdraft, and Sell-Before-Buy ordering.
    """

    portfolio_id: str | None = None
    as_of: datetime
    base_currency: str = Field(default="USD", pattern=r"^(ARS|USD)$")
    rebalance_mode: RebalanceMode
    band_type: BandType
    needs_rebalancing: bool
    breached_tickers: list[str] = Field(default_factory=list)
    total_portfolio_value: Decimal = Field(gt=Decimal("0"))
    projected_post_trade_portfolio_value: Decimal = Field(gt=Decimal("0"))
    initial_cash: Decimal = Field(ge=Decimal("0"))
    projected_ending_cash: Decimal = Field(ge=Decimal("0"))
    total_sell_gross: Decimal = Field(ge=Decimal("0"))
    total_buy_gross: Decimal = Field(ge=Decimal("0"))
    total_estimated_commissions: Decimal = Field(ge=Decimal("0"))
    total_estimated_realized_pnl: Decimal = Field(default=Decimal("0.0000"))
    portfolio_turnover: Decimal = Field(ge=Decimal("0"))
    evaluations: list[AssetBandEvaluation] = Field(default_factory=list)
    orders: list[RebalanceTradeOrder] = Field(default_factory=list)

    @field_validator("base_currency", mode="before")
    @classmethod
    def _normalize_base_currency(cls, v: Any) -> str:
        return _validate_clean_currency(v)

    @field_validator(
        "total_portfolio_value",
        "projected_post_trade_portfolio_value",
        "initial_cash",
        "projected_ending_cash",
        "total_sell_gross",
        "total_buy_gross",
        "total_estimated_commissions",
        "total_estimated_realized_pnl",
        "portfolio_turnover",
        mode="before",
    )
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_cash_closure_and_order_sequence(self) -> ToleranceBandRebalanceReport:
        expected_ending_cash = (
            self.initial_cash
            + self.total_sell_gross
            - self.total_buy_gross
            - self.total_estimated_commissions
        )
        if self.projected_ending_cash != expected_ending_cash:
            raise ValueError(
                f"Cash closure violated: projected_ending_cash ({self.projected_ending_cash}) "
                f"!= initial_cash ({self.initial_cash}) + total_sell_gross ({self.total_sell_gross}) "
                f"- total_buy_gross ({self.total_buy_gross}) - "
                f"total_estimated_commissions ({self.total_estimated_commissions}) = {expected_ending_cash}."
            )
        if self.projected_ending_cash < Decimal("0.0000"):
            raise ValueError(
                f"Overdraft violation: projected_ending_cash ({self.projected_ending_cash}) < 0."
            )

        expected_post_trade_val = (
            self.total_portfolio_value - self.total_estimated_commissions
        )
        if (
            abs(self.projected_post_trade_portfolio_value - expected_post_trade_val)
            > REBALANCE_QUANTIZE
        ):
            raise ValueError(
                f"Post-trade portfolio value closure violated: "
                f"projected_post_trade_portfolio_value ({self.projected_post_trade_portfolio_value}) "
                f"differs from total_portfolio_value - total_estimated_commissions ({expected_post_trade_val})."
            )

        expected_realized_pnl = sum(
            (
                o.estimated_realized_pnl
                for o in self.orders
                if o.side == "SELL" and o.estimated_realized_pnl is not None
            ),
            Decimal("0.0000"),
        )
        if self.total_estimated_realized_pnl != expected_realized_pnl:
            raise ValueError(
                f"Realized PnL aggregation violated: total_estimated_realized_pnl "
                f"({self.total_estimated_realized_pnl}) != sum of SELL order realized PnL ({expected_realized_pnl})."
            )

        seen_buy = False
        for order in self.orders:
            if order.side == "BUY":
                seen_buy = True
            elif order.side == "SELL" and seen_buy:
                raise ValueError(
                    "Order sequence violation: all 'SELL' orders must precede 'BUY' orders."
                )

        if not self.needs_rebalancing:
            if self.breached_tickers:
                raise ValueError(
                    "breached_tickers must be empty when needs_rebalancing is False."
                )
            if self.orders:
                raise ValueError(
                    "orders must be empty when needs_rebalancing is False."
                )

        return self


class RebalanceFSMOrderTicket(BaseSchema):
    """
    Immutable, idempotency-keyed execution ticket ready for two-phase submission
    into the transactional Order Finite State Machine (`PENDING` state).
    """

    sequence_number: int = Field(ge=1)
    execution_phase: Literal["LIQUIDATION_SELL", "ACQUISITION_BUY"]
    idempotency_key: str = Field(min_length=16, max_length=64)
    ticker: str = Field(min_length=1, max_length=20)
    side: Literal["SELL", "BUY"]
    quantity: Decimal = Field(gt=Decimal("0"))
    execution_price: Decimal = Field(gt=Decimal("0"))
    estimated_commission: Decimal = Field(ge=Decimal("0"))
    estimated_realized_pnl: Decimal | None = None
    order_payload: dict[str, Any]

    @field_validator("sequence_number", mode="before")
    @classmethod
    def _validate_strict_sequence_int(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("sequence_number must be a strict integer.")
        return v

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def _validate_idempotency_key(cls, v: Any) -> str:
        if not isinstance(v, str) or isinstance(v, bool):
            raise ValueError("idempotency_key must be a valid string.")
        if any(ord(ch) < 32 for ch in v):
            raise ValueError("Control characters are not permitted in idempotency_key.")
        cleaned = v.strip()
        if len(cleaned) < 16 or len(cleaned) > 64:
            raise ValueError("idempotency_key must be between 16 and 64 characters.")
        return cleaned

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator(
        "quantity", "execution_price", "estimated_commission", mode="before"
    )
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator("estimated_realized_pnl", mode="before")
    @classmethod
    def _validate_optional_pnl(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, "estimated_realized_pnl")

    @model_validator(mode="after")
    def _enforce_phase_and_payload_sync(self) -> RebalanceFSMOrderTicket:
        if self.side == "SELL" and self.execution_phase != "LIQUIDATION_SELL":
            raise ValueError(
                "SELL ticket must have execution_phase == 'LIQUIDATION_SELL'."
            )
        if self.side == "BUY" and self.execution_phase != "ACQUISITION_BUY":
            raise ValueError(
                "BUY ticket must have execution_phase == 'ACQUISITION_BUY'."
            )
        if self.side == "BUY":
            if self.estimated_realized_pnl is None:
                object.__setattr__(self, "estimated_realized_pnl", Decimal("0.0000"))
            elif self.estimated_realized_pnl != Decimal("0.0000"):
                raise ValueError("BUY ticket estimated_realized_pnl must be 0.0000.")
        return self


class RebalanceFSMExecutionBatch(BaseSchema):
    """
    Immutable two-phase (`LIQUIDATION_SELL` -> `ACQUISITION_BUY`) execution batch
    carrying deterministic batch and order idempotency keys for FSM persistence.
    """

    batch_id: str = Field(min_length=16, max_length=64)
    portfolio_id: str | None = None
    as_of: datetime
    base_currency: str = Field(default="USD", pattern=r"^(ARS|USD)$")
    total_orders: int = Field(ge=0)
    sell_orders_count: int = Field(ge=0)
    buy_orders_count: int = Field(ge=0)
    tickets: list[RebalanceFSMOrderTicket] = Field(default_factory=list)

    @field_validator("batch_id", mode="before")
    @classmethod
    def _validate_batch_id(cls, v: Any) -> str:
        if not isinstance(v, str) or isinstance(v, bool):
            raise ValueError("batch_id must be a valid string.")
        if any(ord(ch) < 32 for ch in v):
            raise ValueError("Control characters are not permitted in batch_id.")
        cleaned = v.strip()
        if len(cleaned) < 16 or len(cleaned) > 64:
            raise ValueError("batch_id must be between 16 and 64 characters.")
        return cleaned

    @field_validator("base_currency", mode="before")
    @classmethod
    def _normalize_base_currency(cls, v: Any) -> str:
        return _validate_clean_currency(v)

    @field_validator(
        "total_orders", "sell_orders_count", "buy_orders_count", mode="before"
    )
    @classmethod
    def _validate_strict_counts(cls, v: Any, info: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"'{info.field_name}' must be a strict integer.")
        return v

    @model_validator(mode="after")
    def _enforce_batch_integrity_and_phase_ordering(
        self,
    ) -> RebalanceFSMExecutionBatch:
        if self.total_orders != len(self.tickets):
            raise ValueError(
                f"total_orders ({self.total_orders}) must equal len(tickets) ({len(self.tickets)})."
            )
        actual_sells = sum(1 for t in self.tickets if t.side == "SELL")
        actual_buys = sum(1 for t in self.tickets if t.side == "BUY")
        if self.sell_orders_count != actual_sells:
            raise ValueError(
                f"sell_orders_count ({self.sell_orders_count}) != actual SELL tickets ({actual_sells})."
            )
        if self.buy_orders_count != actual_buys:
            raise ValueError(
                f"buy_orders_count ({self.buy_orders_count}) != actual BUY tickets ({actual_buys})."
            )
        if self.sell_orders_count + self.buy_orders_count != self.total_orders:
            raise ValueError(
                "sell_orders_count + buy_orders_count must equal total_orders."
            )

        expected_seq = list(range(1, len(self.tickets) + 1))
        actual_seq = [t.sequence_number for t in self.tickets]
        if actual_seq != expected_seq:
            raise ValueError(
                f"Ticket sequence_number values must be contiguous {expected_seq} (got {actual_seq})."
            )

        idem_keys = [t.idempotency_key for t in self.tickets]
        if len(set(idem_keys)) != len(idem_keys):
            raise ValueError("Duplicate idempotency_key detected in batch tickets.")

        seen_buy = False
        for ticket in self.tickets:
            if ticket.side == "BUY":
                seen_buy = True
            elif ticket.side == "SELL" and seen_buy:
                raise ValueError(
                    "Batch phase ordering violated: all 'LIQUIDATION_SELL' tickets must precede 'ACQUISITION_BUY' tickets."
                )

        return self


@dataclass
class _PositionAccumulator:
    """Internal accumulator for consolidating duplicate position lots."""

    ticker: str
    raw_qty: Decimal = Decimal("0")
    raw_val: Decimal = Decimal("0")
    raw_cost_val: Decimal = Decimal("0")
    has_any_cost: bool = False
    has_missing_cost: bool = False
    last_price: Decimal = Decimal("0")


# ============================================================================
# Tolerance-Band Rebalancer Domain Service
# ============================================================================
class ToleranceBandRebalancerService:
    """
    Stateless quantitative domain service monitoring portfolio drift against
    absolute, relative, or volatility-scaled tolerance bands, calibrating
    volatility multipliers from ATR snapshots, and generating self-financing
    rebalance trade orders and idempotent FSM execution batches.
    """

    def __init__(self, config: ToleranceBandRebalancerConfig | None = None) -> None:
        if config is None:
            self._config = ToleranceBandRebalancerConfig()
        elif isinstance(config, ToleranceBandRebalancerConfig):
            self._config = config
        else:
            raise InvalidToleranceBandConfigError(
                "config must be a ToleranceBandRebalancerConfig instance or None."
            )

    @property
    def config(self) -> ToleranceBandRebalancerConfig:
        """Return the active immutable rebalancer configuration."""
        return self._config

    def calibrate_specs_from_indicators(
        self,
        target_specs: Sequence[AssetTargetBandSpec],
        indicators_by_ticker: Mapping[str, TechnicalIndicatorsSnapshot],
        baseline_atr_pct: Decimal = Decimal("0.0200"),
        min_multiplier: Decimal = Decimal("0.5000"),
        max_multiplier: Decimal = Decimal("3.0000"),
    ) -> list[AssetTargetBandSpec]:
        """
        Dynamically calibrate each `AssetTargetBandSpec.volatility_multiplier`
        and fallback `reference_price` from `TechnicalIndicatorsSnapshot` (Module 7.1)
        based on normalized ATR volatility (`(atr_14 / close) / baseline_atr_pct`),
        clamped to `[min_multiplier, max_multiplier]`.
        """
        if (
            isinstance(target_specs, (str, bytes))
            or not isinstance(target_specs, Sequence)
            or len(target_specs) == 0
        ):
            raise InvalidTargetAllocationError(
                "target_specs must be a non-empty sequence of AssetTargetBandSpec instances."
            )
        if len(target_specs) > MAX_REBALANCE_ASSETS:
            raise InvalidTargetAllocationError(
                f"target_specs count ({len(target_specs)}) exceeds maximum allowed ({MAX_REBALANCE_ASSETS})."
            )

        if not isinstance(indicators_by_ticker, Mapping):
            raise InvalidToleranceBandConfigError(
                "indicators_by_ticker must be a mapping of ticker -> TechnicalIndicatorsSnapshot."
            )

        try:
            dec_baseline = _coerce_finite_decimal(baseline_atr_pct, "baseline_atr_pct")
            dec_min_mult = _coerce_finite_decimal(min_multiplier, "min_multiplier")
            dec_max_mult = _coerce_finite_decimal(max_multiplier, "max_multiplier")
        except ValueError as exc:
            raise InvalidToleranceBandConfigError(str(exc)) from exc

        if dec_baseline <= Decimal("0") or dec_baseline > Decimal("1.0000"):
            raise InvalidToleranceBandConfigError(
                f"baseline_atr_pct must be in (0, 1.0000] (got {dec_baseline})."
            )
        if (
            dec_min_mult <= Decimal("0")
            or dec_min_mult > dec_max_mult
            or dec_max_mult > Decimal("5.0000")
        ):
            raise InvalidToleranceBandConfigError(
                f"Multiplier bounds must satisfy 0 < min_multiplier ({dec_min_mult}) "
                f"<= max_multiplier ({dec_max_mult}) <= 5.0000."
            )

        normalized_snapshots: dict[str, TechnicalIndicatorsSnapshot] = {}
        for raw_key, snap in indicators_by_ticker.items():
            if not isinstance(raw_key, str) or isinstance(raw_key, bool):
                raise InvalidToleranceBandConfigError(
                    "indicators_by_ticker keys must be valid ticker strings."
                )
            if not isinstance(snap, TechnicalIndicatorsSnapshot):
                raise InvalidToleranceBandConfigError(
                    f"Value for ticker '{raw_key}' must be a TechnicalIndicatorsSnapshot instance."
                )
            clean_key = raw_key.strip().upper()
            if clean_key:
                normalized_snapshots[clean_key] = snap

        calibrated_specs: list[AssetTargetBandSpec] = []
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            for idx, spec in enumerate(target_specs):
                if not isinstance(spec, AssetTargetBandSpec):
                    raise InvalidTargetAllocationError(
                        f"Element at index {idx} in target_specs is not an AssetTargetBandSpec instance."
                    )
                alt_ticker = (
                    spec.ticker[:-3]
                    if spec.ticker.endswith(".BA")
                    else f"{spec.ticker}.BA"
                )
                snap = normalized_snapshots.get(
                    spec.ticker
                ) or normalized_snapshots.get(alt_ticker)

                if snap is None:
                    calibrated_specs.append(spec)
                    continue

                ref_price = (
                    spec.reference_price
                    if spec.reference_price is not None
                    else (_quantize(snap.close) if snap.close > Decimal("0") else None)
                )

                if (
                    snap.atr_14 is not None
                    and snap.atr_14 > Decimal("0")
                    and snap.close > Decimal("0")
                ):
                    atr_pct = snap.atr_14 / snap.close
                    raw_mult = atr_pct / dec_baseline
                    clamped_mult = _quantize(
                        min(dec_max_mult, max(dec_min_mult, raw_mult))
                    )
                    calibrated_specs.append(
                        AssetTargetBandSpec(
                            ticker=spec.ticker,
                            target_weight=spec.target_weight,
                            reference_price=ref_price,
                            absolute_tolerance_override=spec.absolute_tolerance_override,
                            relative_tolerance_override=spec.relative_tolerance_override,
                            volatility_multiplier=clamped_mult,
                        )
                    )
                else:
                    calibrated_specs.append(
                        AssetTargetBandSpec(
                            ticker=spec.ticker,
                            target_weight=spec.target_weight,
                            reference_price=ref_price,
                            absolute_tolerance_override=spec.absolute_tolerance_override,
                            relative_tolerance_override=spec.relative_tolerance_override,
                            volatility_multiplier=spec.volatility_multiplier,
                        )
                    )

        return calibrated_specs

    def _compute_band_bounds(
        self, spec: AssetTargetBandSpec
    ) -> tuple[Decimal, Decimal]:
        """Compute quantized `(lower_band, upper_band)` for a target asset specification."""
        if spec.target_weight == Decimal("0"):
            return Decimal("0.0000"), Decimal("0.0000")

        cfg = self._config
        if cfg.band_type == BandType.ABSOLUTE:
            base_half = (
                spec.absolute_tolerance_override
                if spec.absolute_tolerance_override is not None
                else cfg.default_absolute_tolerance
            )
            raw_half = (
                base_half * spec.volatility_multiplier
                if spec.volatility_multiplier != Decimal("1.0000")
                else base_half
            )
        elif cfg.band_type == BandType.RELATIVE:
            rel_tol = (
                spec.relative_tolerance_override
                if spec.relative_tolerance_override is not None
                else cfg.default_relative_tolerance
            )
            base_half = spec.target_weight * rel_tol
            raw_half = (
                base_half * spec.volatility_multiplier
                if spec.volatility_multiplier != Decimal("1.0000")
                else base_half
            )
        elif cfg.band_type == BandType.DYNAMIC_VOLATILITY:
            if spec.absolute_tolerance_override is not None:
                base_half = spec.absolute_tolerance_override
            else:
                rel_tol = (
                    spec.relative_tolerance_override
                    if spec.relative_tolerance_override is not None
                    else cfg.default_relative_tolerance
                )
                base_half = spec.target_weight * rel_tol
            raw_half = base_half * spec.volatility_multiplier
        else:
            raise InvalidToleranceBandConfigError(
                f"Unsupported band_type '{cfg.band_type}'."
            )

        clamped_half = min(
            cfg.max_band_half_width,
            max(cfg.min_band_half_width, raw_half),
        )
        lower_band = max(Decimal("0.0000"), _quantize(spec.target_weight - clamped_half))
        upper_band = min(Decimal("1.0000"), _quantize(spec.target_weight + clamped_half))
        return lower_band, upper_band

    @staticmethod
    def _resolve_external_price(
        ticker: str,
        spec: AssetTargetBandSpec | None,
        normalized_prices: Mapping[str, Any],
    ) -> Decimal:
        """Resolve spot price for an unheld target asset from `spec.reference_price` or `market_prices`."""
        if spec is not None and spec.reference_price is not None:
            return _quantize(spec.reference_price)

        alt_ticker = ticker[:-3] if ticker.endswith(".BA") else f"{ticker}.BA"
        raw_price: Any = None
        if ticker in normalized_prices:
            raw_price = normalized_prices[ticker]
        elif alt_ticker in normalized_prices:
            raw_price = normalized_prices[alt_ticker]
        else:
            raise MissingRebalancePriceError(
                f"Missing market price for target ticker '{ticker}'."
            )

        if isinstance(raw_price, bool) or raw_price is None:
            raise MissingRebalancePriceError(
                f"Invalid market price for target ticker '{ticker}': boolean or None is not permitted."
            )
        try:
            dec_price = _coerce_finite_decimal(raw_price, f"market_prices['{ticker}']")
        except ValueError as exc:
            raise MissingRebalancePriceError(
                f"Invalid market price for target ticker '{ticker}': {exc}"
            ) from exc

        if dec_price <= Decimal("0"):
            raise MissingRebalancePriceError(
                f"Market price for target ticker '{ticker}' must be > 0 (got {dec_price})."
            )
        q_price = _quantize(dec_price)
        if q_price <= Decimal("0"):
            raise MissingRebalancePriceError(
                f"Market price for target ticker '{ticker}' collapses to zero after quantization."
            )
        return q_price

    def evaluate_and_rebalance(
        self,
        positions: Sequence[RebalancePositionInput],
        target_specs: Sequence[AssetTargetBandSpec],
        initial_cash: Decimal = Decimal("0"),
        market_prices: Mapping[str, Decimal] | None = None,
        portfolio_id: str | None = None,
        base_currency: str = "USD",
        as_of: datetime | None = None,
    ) -> ToleranceBandRebalanceReport:
        """
        Evaluate portfolio drift against configured tolerance bands and generate
        optimal self-financing rebalance orders (`SELL` before `BUY`) if any
        asset breaches its corridor or if excess liquidity deployment is enabled.
        """
        try:
            clean_currency = _validate_clean_currency(base_currency)
        except ValueError as exc:
            raise InvalidToleranceBandConfigError(str(exc)) from exc

        if isinstance(initial_cash, bool) or initial_cash is None:
            raise InsufficientLiquidityForRebalanceError(
                "initial_cash cannot be boolean or None."
            )
        try:
            clean_initial_cash = _coerce_finite_decimal(initial_cash, "initial_cash")
        except ValueError as exc:
            raise InsufficientLiquidityForRebalanceError(str(exc)) from exc
        if clean_initial_cash < Decimal("0"):
            raise InsufficientLiquidityForRebalanceError(
                f"initial_cash must be >= 0 (got {clean_initial_cash})."
            )

        if (
            isinstance(target_specs, (str, bytes))
            or not isinstance(target_specs, Sequence)
            or len(target_specs) == 0
        ):
            raise InvalidTargetAllocationError(
                "target_specs must be a non-empty sequence of AssetTargetBandSpec instances."
            )
        if len(target_specs) > MAX_REBALANCE_ASSETS:
            raise InvalidTargetAllocationError(
                f"target_specs count ({len(target_specs)}) exceeds maximum allowed ({MAX_REBALANCE_ASSETS})."
            )

        if isinstance(positions, (str, bytes)) or not isinstance(positions, Sequence):
            raise InvalidTargetAllocationError(
                "positions must be a sequence of RebalancePositionInput instances."
            )
        if len(positions) > MAX_REBALANCE_ASSETS:
            raise InvalidTargetAllocationError(
                f"positions count ({len(positions)}) exceeds maximum allowed ({MAX_REBALANCE_ASSETS})."
            )

        effective_as_of = as_of if as_of is not None else datetime.now(timezone.utc)
        if not isinstance(effective_as_of, datetime) or isinstance(
            effective_as_of, bool
        ):
            raise InvalidToleranceBandConfigError(
                "as_of must be a valid datetime instance."
            )

        normalized_prices: dict[str, Any] = {}
        if market_prices is not None:
            if not isinstance(market_prices, Mapping):
                raise MissingRebalancePriceError(
                    "market_prices must be a mapping of ticker -> price."
                )
            for raw_k, raw_v in market_prices.items():
                if not isinstance(raw_k, str) or isinstance(raw_k, bool):
                    raise MissingRebalancePriceError(
                        "market_prices keys must be valid strings."
                    )
                clean_k = raw_k.strip().upper()
                if clean_k:
                    normalized_prices[clean_k] = raw_v

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION

            target_map: dict[str, AssetTargetBandSpec] = {}
            target_weight_sum = Decimal("0.0000")
            for idx, spec in enumerate(target_specs):
                if not isinstance(spec, AssetTargetBandSpec):
                    raise InvalidTargetAllocationError(
                        f"Element at index {idx} in target_specs is not an AssetTargetBandSpec instance."
                    )
                if spec.ticker in target_map:
                    raise InvalidTargetAllocationError(
                        f"Duplicate ticker '{spec.ticker}' in target_specs."
                    )
                target_map[spec.ticker] = spec
                target_weight_sum += _quantize(spec.target_weight)

            q_cash_buffer_weight = _quantize(self._config.cash_buffer_weight)
            total_allocation_weight = _quantize(target_weight_sum + q_cash_buffer_weight)
            if total_allocation_weight != Decimal("1.0000"):
                raise InvalidTargetAllocationError(
                    f"Sum of target_weight ({target_weight_sum}) + cash_buffer_weight "
                    f"({q_cash_buffer_weight}) must equal 1.0000 (got {total_allocation_weight})."
                )

            pos_map: dict[str, _PositionAccumulator] = {}
            for idx, pos in enumerate(positions):
                if not isinstance(pos, RebalancePositionInput):
                    raise InvalidTargetAllocationError(
                        f"Element at index {idx} in positions is not a RebalancePositionInput instance."
                    )
                if pos.market_price <= Decimal("0"):
                    raise MissingRebalancePriceError(
                        f"Position '{pos.ticker}' has a non-positive market_price ({pos.market_price})."
                    )
                acc = pos_map.get(pos.ticker)
                if acc is None:
                    acc = _PositionAccumulator(
                        ticker=pos.ticker,
                        last_price=pos.market_price,
                    )
                    pos_map[pos.ticker] = acc
                acc.raw_qty += pos.quantity
                acc.raw_val += pos.quantity * pos.market_price
                acc.last_price = pos.market_price
                if pos.quantity > Decimal("0"):
                    if pos.avg_cost_price is not None:
                        acc.raw_cost_val += pos.quantity * pos.avg_cost_price
                        acc.has_any_cost = True
                    else:
                        acc.has_missing_cost = True

            q_initial_cash = _quantize(clean_initial_cash)
            total_positions_val = sum(
                (_quantize(acc.raw_val) for acc in pos_map.values() if acc.raw_qty > Decimal("0")),
                Decimal("0.0000"),
            )
            total_portfolio_value = _quantize(total_positions_val + q_initial_cash)
            if total_portfolio_value <= Decimal("0"):
                raise InsufficientLiquidityForRebalanceError(
                    f"Total portfolio value must be strictly positive (got {total_portfolio_value})."
                )

            # Determine ordered universe of tickers: target_specs order first, then unlisted active holdings
            ordered_tickers: list[str] = list(target_map.keys())
            for ticker, acc in pos_map.items():
                if ticker not in target_map and acc.raw_qty > Decimal("0"):
                    ordered_tickers.append(ticker)

            # First pass: evaluate band corridors and breaches
            prelim_evals: list[dict[str, Any]] = []
            breached_tickers: list[str] = []

            for ticker in ordered_tickers:
                spec = target_map.get(ticker)
                acc = pos_map.get(ticker)

                if acc is not None and acc.raw_qty > Decimal("0"):
                    curr_qty = _quantize(acc.raw_qty)
                    mkt_price = _quantize(acc.raw_val / acc.raw_qty)
                    curr_val = _quantize(acc.raw_val)
                    avg_cost: Decimal | None = (
                        _quantize(acc.raw_cost_val / acc.raw_qty)
                        if (acc.has_any_cost and not acc.has_missing_cost)
                        else None
                    )
                else:
                    curr_qty = Decimal("0.0000")
                    mkt_price = self._resolve_external_price(
                        ticker, spec, normalized_prices
                    )
                    curr_val = Decimal("0.0000")
                    avg_cost = None

                curr_weight = _quantize(curr_val / total_portfolio_value)

                if spec is not None:
                    tgt_weight = _quantize(spec.target_weight)
                    lower_band, upper_band = self._compute_band_bounds(spec)
                    drift_weight = _quantize(curr_weight - tgt_weight)

                    if curr_weight > upper_band or (
                        tgt_weight == Decimal("0.0000") and curr_qty > Decimal("0")
                    ):
                        is_breached = True
                        breach_dir = BandBreachDirection.UPPER
                    elif curr_weight < lower_band:
                        is_breached = True
                        breach_dir = BandBreachDirection.LOWER
                    else:
                        is_breached = False
                        breach_dir = BandBreachDirection.NONE
                else:
                    # Unlisted holding not in target_specs
                    tgt_weight = Decimal("0.0000")
                    drift_weight = curr_weight
                    if self._config.liquidate_unlisted_holdings:
                        lower_band = Decimal("0.0000")
                        upper_band = Decimal("0.0000")
                        is_breached = True
                        breach_dir = BandBreachDirection.UPPER
                    else:
                        lower_band = Decimal("0.0000")
                        upper_band = Decimal("1.0000")
                        is_breached = False
                        breach_dir = BandBreachDirection.NONE

                if is_breached:
                    breached_tickers.append(ticker)

                prelim_evals.append(
                    {
                        "ticker": ticker,
                        "current_quantity": curr_qty,
                        "market_price": mkt_price,
                        "avg_cost_price": avg_cost,
                        "current_value": curr_val,
                        "current_weight": curr_weight,
                        "target_weight": tgt_weight,
                        "lower_band": lower_band,
                        "upper_band": upper_band,
                        "drift_weight": drift_weight,
                        "is_breached": is_breached,
                        "breach_direction": breach_dir,
                    }
                )

            initial_cash_weight = _quantize(q_initial_cash / total_portfolio_value)
            excess_cash_threshold = _quantize(
                q_cash_buffer_weight + _quantize(self._config.min_band_half_width)
            )
            triggered_by_excess_cash = (
                len(breached_tickers) == 0
                and self._config.deploy_excess_cash_when_inside_bands
                and initial_cash_weight > excess_cash_threshold
            )
            should_attempt_trades = (
                len(breached_tickers) > 0 or triggered_by_excess_cash
            )

            for item in prelim_evals:
                if not should_attempt_trades:
                    dest_weight = item["current_weight"]
                elif triggered_by_excess_cash:
                    # Allocate excess liquidity strictly into underweighted target assets without selling
                    if (
                        item["ticker"] in target_map
                        and item["current_weight"] < item["target_weight"]
                    ):
                        dest_weight = item["target_weight"]
                    else:
                        dest_weight = item["current_weight"]
                elif self._config.rebalance_mode == RebalanceMode.FULL_TO_TARGET:
                    if (
                        item["ticker"] not in target_map
                        and not self._config.liquidate_unlisted_holdings
                    ):
                        dest_weight = item["current_weight"]
                    else:
                        dest_weight = item["target_weight"]
                else:
                    # RebalanceMode.TO_BAND_BOUNDARY
                    if item["breach_direction"] == BandBreachDirection.UPPER:
                        dest_weight = item["upper_band"]
                    elif item["breach_direction"] == BandBreachDirection.LOWER:
                        dest_weight = item["lower_band"]
                    else:
                        dest_weight = item["current_weight"]

                item["destination_weight"] = dest_weight

            if not should_attempt_trades:
                no_trade_evals = [
                    AssetBandEvaluation(
                        ticker=item["ticker"],
                        current_quantity=item["current_quantity"],
                        market_price=item["market_price"],
                        current_value=item["current_value"],
                        current_weight=item["current_weight"],
                        target_weight=item["target_weight"],
                        lower_band=item["lower_band"],
                        upper_band=item["upper_band"],
                        drift_weight=item["drift_weight"],
                        is_breached=item["is_breached"],
                        breach_direction=item["breach_direction"],
                        destination_weight=item["destination_weight"],
                        post_trade_quantity=item["current_quantity"],
                        post_trade_value=item["current_value"],
                        post_trade_weight=item["current_weight"],
                        post_trade_drift_weight=item["drift_weight"],
                    )
                    for item in prelim_evals
                ]
                return ToleranceBandRebalanceReport(
                    portfolio_id=portfolio_id,
                    as_of=effective_as_of,
                    base_currency=clean_currency,
                    rebalance_mode=self._config.rebalance_mode,
                    band_type=self._config.band_type,
                    needs_rebalancing=False,
                    breached_tickers=[],
                    total_portfolio_value=total_portfolio_value,
                    projected_post_trade_portfolio_value=total_portfolio_value,
                    initial_cash=q_initial_cash,
                    projected_ending_cash=q_initial_cash,
                    total_sell_gross=Decimal("0.0000"),
                    total_buy_gross=Decimal("0.0000"),
                    total_estimated_commissions=Decimal("0.0000"),
                    total_estimated_realized_pnl=Decimal("0.0000"),
                    portfolio_turnover=Decimal("0.0000"),
                    evaluations=no_trade_evals,
                    orders=[],
                )

            # Self-Financing Liquidity Waterfall: Step 1 (SELL orders)
            qty_step = (
                REBALANCE_QUANTIZE
                if self._config.allow_fractional_shares
                else Decimal("1")
            )
            comm_rate = self._config.commission_bps / Decimal("10000")
            sell_orders: list[RebalanceTradeOrder] = []
            buy_candidates: list[tuple[Decimal, dict[str, Any]]] = []

            for item in prelim_evals:
                dest_value = total_portfolio_value * item["destination_weight"]
                curr_val = item["current_value"]
                curr_qty = item["current_quantity"]
                mkt_price = item["market_price"]
                avg_cost = item["avg_cost_price"]

                if curr_val > dest_value and curr_qty > Decimal("0"):
                    if item["destination_weight"] == Decimal("0.0000"):
                        if self._config.allow_fractional_shares:
                            sell_qty = curr_qty
                        else:
                            sell_qty = curr_qty.quantize(
                                qty_step, rounding=ROUND_FLOOR
                            )
                    else:
                        raw_sell_qty = (curr_val - dest_value) / mkt_price
                        floored_qty = raw_sell_qty.quantize(
                            qty_step, rounding=ROUND_FLOOR
                        )
                        sell_qty = min(curr_qty, floored_qty)

                    q_sell_qty = _quantize(sell_qty)
                    if q_sell_qty > Decimal("0"):
                        gross = _quantize(q_sell_qty * mkt_price)
                        if gross >= self._config.min_trade_notional:
                            commission = _quantize(gross * comm_rate)
                            net_impact = _quantize(gross - commission)
                            est_realized_pnl = (
                                _quantize(
                                    q_sell_qty * (mkt_price - avg_cost) - commission
                                )
                                if avg_cost is not None
                                else None
                            )
                            conviction = min(
                                Decimal("1.0000"),
                                max(
                                    Decimal("0.0001"),
                                    _quantize(abs(item["drift_weight"])),
                                ),
                            )
                            intent = OrderFSMIntent(
                                ticker=item["ticker"],
                                side="SELL",
                                target_status="PENDING",
                                reference_price=mkt_price,
                                signal_conviction=conviction,
                            )
                            sell_orders.append(
                                RebalanceTradeOrder(
                                    ticker=item["ticker"],
                                    side="SELL",
                                    quantity=q_sell_qty,
                                    execution_price=mkt_price,
                                    gross_amount=gross,
                                    estimated_commission=commission,
                                    net_cash_impact=net_impact,
                                    estimated_realized_pnl=est_realized_pnl,
                                    order_intent=intent,
                                )
                            )
                elif dest_value > curr_val:
                    deficit = dest_value - curr_val
                    if deficit > Decimal("0"):
                        buy_candidates.append((deficit, item))

            # Sort SELL orders deterministically by (-gross_amount, ticker)
            sell_orders.sort(key=lambda o: (-o.gross_amount, o.ticker))

            # Step 2: Compute available cash pool for BUY orders after cash buffer reserve
            net_sell_proceeds = sum(
                (o.net_cash_impact for o in sell_orders), Decimal("0.0000")
            )
            total_cash_after_sells = _quantize(q_initial_cash + net_sell_proceeds)
            if total_cash_after_sells < Decimal("0.0000"):
                raise InsufficientLiquidityForRebalanceError(
                    f"Projected cash after sells is negative ({total_cash_after_sells})."
                )

            target_cash_reserve = _quantize(
                total_portfolio_value * q_cash_buffer_weight
            )
            available_cash_for_buys = max(
                Decimal("0.0000"),
                total_cash_after_sells - target_cash_reserve,
            )

            # Step 3: Proportional & Commission-Aware BUY sizing
            buy_orders: list[RebalanceTradeOrder] = []
            total_required_cash = sum(
                (deficit * (Decimal("1") + comm_rate) for deficit, _ in buy_candidates),
                Decimal("0"),
            )

            if (
                total_required_cash > Decimal("0")
                and available_cash_for_buys > Decimal("0")
            ):
                scale = min(
                    Decimal("1"),
                    available_cash_for_buys / total_required_cash,
                )
                remaining_cash = available_cash_for_buys

                # Deterministic priority: largest deficit first, then ticker alphabetically
                buy_candidates.sort(key=lambda pair: (-pair[0], pair[1]["ticker"]))

                for deficit, item in buy_candidates:
                    if remaining_cash <= Decimal("0"):
                        break
                    allocated_gross_budget = min(
                        deficit * scale,
                        remaining_cash / (Decimal("1") + comm_rate),
                    )
                    if allocated_gross_budget <= Decimal("0"):
                        continue

                    mkt_price = item["market_price"]
                    raw_buy_qty = allocated_gross_budget / mkt_price
                    buy_qty = raw_buy_qty.quantize(qty_step, rounding=ROUND_FLOOR)

                    gross = Decimal("0.0000")
                    commission = Decimal("0.0000")
                    while buy_qty > Decimal("0"):
                        gross = _quantize(buy_qty * mkt_price)
                        commission = _quantize(gross * comm_rate)
                        if gross + commission <= remaining_cash:
                            break
                        buy_qty = (buy_qty - qty_step).quantize(
                            qty_step, rounding=ROUND_FLOOR
                        )

                    q_buy_qty = _quantize(buy_qty)
                    if (
                        q_buy_qty > Decimal("0")
                        and gross >= self._config.min_trade_notional
                    ):
                        total_outflow = _quantize(gross + commission)
                        remaining_cash = _quantize(remaining_cash - total_outflow)
                        conviction = min(
                            Decimal("1.0000"),
                            max(
                                Decimal("0.0001"),
                                _quantize(abs(item["drift_weight"])),
                            ),
                        )
                        intent = OrderFSMIntent(
                            ticker=item["ticker"],
                            side="BUY",
                            target_status="PENDING",
                            reference_price=mkt_price,
                            signal_conviction=conviction,
                        )
                        buy_orders.append(
                            RebalanceTradeOrder(
                                ticker=item["ticker"],
                                side="BUY",
                                quantity=q_buy_qty,
                                execution_price=mkt_price,
                                gross_amount=gross,
                                estimated_commission=commission,
                                net_cash_impact=-total_outflow,
                                estimated_realized_pnl=Decimal("0.0000"),
                                order_intent=intent,
                            )
                        )

            buy_orders.sort(key=lambda o: (-o.gross_amount, o.ticker))
            all_orders = sell_orders + buy_orders

            needs_rebalancing = (
                True if len(breached_tickers) > 0 else (len(all_orders) > 0)
            )
            if not needs_rebalancing:
                for item in prelim_evals:
                    item["destination_weight"] = item["current_weight"]

            total_sell_gross = sum(
                (o.gross_amount for o in sell_orders), Decimal("0.0000")
            )
            total_buy_gross = sum(
                (o.gross_amount for o in buy_orders), Decimal("0.0000")
            )
            total_commissions = sum(
                (o.estimated_commission for o in all_orders), Decimal("0.0000")
            )
            total_estimated_realized_pnl = _quantize(
                sum(
                    (
                        o.estimated_realized_pnl
                        for o in sell_orders
                        if o.estimated_realized_pnl is not None
                    ),
                    Decimal("0.0000"),
                )
            )
            projected_ending_cash = _quantize(
                q_initial_cash
                + total_sell_gross
                - total_buy_gross
                - total_commissions
            )
            projected_post_trade_portfolio_value = _quantize(
                total_portfolio_value - total_commissions
            )
            if projected_post_trade_portfolio_value <= Decimal("0"):
                raise InsufficientLiquidityForRebalanceError(
                    f"Projected post-trade portfolio value must be > 0 (got {projected_post_trade_portfolio_value})."
                )

            portfolio_turnover = _quantize(
                (total_sell_gross + total_buy_gross)
                / (Decimal("2") * total_portfolio_value)
            )

            # Build per-asset post-trade evaluation snapshots
            sell_by_ticker = {o.ticker: o for o in sell_orders}
            buy_by_ticker = {o.ticker: o for o in buy_orders}
            evaluations: list[AssetBandEvaluation] = []

            for item in prelim_evals:
                ticker = item["ticker"]
                s_ord = sell_by_ticker.get(ticker)
                b_ord = buy_by_ticker.get(ticker)

                sold_qty = s_ord.quantity if s_ord is not None else Decimal("0.0000")
                bought_qty = b_ord.quantity if b_ord is not None else Decimal("0.0000")
                sell_gross = (
                    s_ord.gross_amount if s_ord is not None else Decimal("0.0000")
                )
                buy_gross = (
                    b_ord.gross_amount if b_ord is not None else Decimal("0.0000")
                )

                post_qty = _quantize(
                    item["current_quantity"] - sold_qty + bought_qty
                )
                post_val = _quantize(
                    item["current_value"] - sell_gross + buy_gross
                )
                raw_post_weight = _quantize(
                    post_val / projected_post_trade_portfolio_value
                )
                post_weight = min(
                    Decimal("1.0000"), max(Decimal("0.0000"), raw_post_weight)
                )
                post_drift = _quantize(post_weight - item["target_weight"])

                evaluations.append(
                    AssetBandEvaluation(
                        ticker=ticker,
                        current_quantity=item["current_quantity"],
                        market_price=item["market_price"],
                        current_value=item["current_value"],
                        current_weight=item["current_weight"],
                        target_weight=item["target_weight"],
                        lower_band=item["lower_band"],
                        upper_band=item["upper_band"],
                        drift_weight=item["drift_weight"],
                        is_breached=item["is_breached"],
                        breach_direction=item["breach_direction"],
                        destination_weight=item["destination_weight"],
                        post_trade_quantity=post_qty,
                        post_trade_value=post_val,
                        post_trade_weight=post_weight,
                        post_trade_drift_weight=post_drift,
                    )
                )

        return ToleranceBandRebalanceReport(
            portfolio_id=portfolio_id,
            as_of=effective_as_of,
            base_currency=clean_currency,
            rebalance_mode=self._config.rebalance_mode,
            band_type=self._config.band_type,
            needs_rebalancing=needs_rebalancing,
            breached_tickers=breached_tickers,
            total_portfolio_value=total_portfolio_value,
            projected_post_trade_portfolio_value=projected_post_trade_portfolio_value,
            initial_cash=q_initial_cash,
            projected_ending_cash=projected_ending_cash,
            total_sell_gross=total_sell_gross,
            total_buy_gross=total_buy_gross,
            total_estimated_commissions=total_commissions,
            total_estimated_realized_pnl=total_estimated_realized_pnl,
            portfolio_turnover=portfolio_turnover,
            evaluations=evaluations,
            orders=all_orders,
        )

    def rebalance_from_mtm_report(
        self,
        mtm_report: PortfolioMarkToMarketReport,
        target_specs: Sequence[AssetTargetBandSpec],
        extra_market_prices: Mapping[str, Decimal] | None = None,
        base_currency: str = "USD",
    ) -> ToleranceBandRebalanceReport:
        """
        Evaluate tolerance bands and generate self-financing rebalance orders
        directly from a consolidated `PortfolioMarkToMarketReport` (Module 7.2)
        in either `'USD'` or `'ARS'` base currency, propagating unit cost basis
        for realized PnL estimation on partial or full sales.
        """
        if not isinstance(mtm_report, PortfolioMarkToMarketReport):
            raise InvalidTargetAllocationError(
                "mtm_report must be a PortfolioMarkToMarketReport instance."
            )
        try:
            clean_currency = _validate_clean_currency(base_currency)
        except ValueError as exc:
            raise InvalidToleranceBandConfigError(str(exc)) from exc

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            rebalance_positions: list[RebalancePositionInput] = []

            for pos in mtm_report.positions:
                if clean_currency == "USD":
                    unit_price = _quantize(pos.market_value_usd / pos.quantity)
                    unit_cost = _quantize(pos.cost_basis_usd / pos.quantity)
                else:
                    unit_price = _quantize(pos.market_value_ars / pos.quantity)
                    unit_cost = _quantize(pos.cost_basis_ars / pos.quantity)

                rebalance_positions.append(
                    RebalancePositionInput(
                        ticker=pos.ticker,
                        quantity=pos.quantity,
                        market_price=unit_price,
                        avg_cost_price=unit_cost,
                    )
                )

            if clean_currency == "USD":
                consolidated_cash = _quantize(
                    mtm_report.cash_balance_usd
                    + (mtm_report.cash_balance_ars / mtm_report.fx_rate_ars_per_usd)
                )
            else:
                consolidated_cash = _quantize(
                    mtm_report.cash_balance_ars
                    + (mtm_report.cash_balance_usd * mtm_report.fx_rate_ars_per_usd)
                )

        return self.evaluate_and_rebalance(
            positions=rebalance_positions,
            target_specs=target_specs,
            initial_cash=consolidated_cash,
            market_prices=extra_market_prices,
            portfolio_id=mtm_report.portfolio_id,
            base_currency=clean_currency,
            as_of=mtm_report.as_of,
        )

    def build_fsm_execution_batch(
        self,
        report: ToleranceBandRebalanceReport,
        portfolio_id: str | None = None,
    ) -> RebalanceFSMExecutionBatch:
        """
        Transform a `ToleranceBandRebalanceReport` into a deterministic,
        idempotency-keyed two-phase execution batch (`LIQUIDATION_SELL` followed
        by `ACQUISITION_BUY`) ready for Order FSM persistence (`PENDING` state).
        """
        if not isinstance(report, ToleranceBandRebalanceReport):
            raise InvalidToleranceBandConfigError(
                "report must be a ToleranceBandRebalanceReport instance."
            )

        raw_pid = portfolio_id if portfolio_id is not None else report.portfolio_id
        effective_portfolio_id: str | None = None
        if raw_pid is not None:
            if (
                not isinstance(raw_pid, str)
                or isinstance(raw_pid, bool)
                or any(ord(ch) < 32 for ch in raw_pid)
            ):
                raise InvalidToleranceBandConfigError(
                    "portfolio_id must be a valid string without control characters."
                )
            cleaned_pid = raw_pid.strip()
            if not cleaned_pid:
                raise InvalidToleranceBandConfigError(
                    "portfolio_id cannot be empty or whitespace."
                )
            effective_portfolio_id = cleaned_pid

        orders_fingerprint = "|".join(
            f"{o.ticker}:{o.side}:{o.quantity}:{o.execution_price}"
            for o in report.orders
        )
        batch_seed = (
            f"{effective_portfolio_id or 'default'}|"
            f"{report.as_of.isoformat()}|"
            f"{report.base_currency}|"
            f"{report.rebalance_mode.value}|"
            f"{len(report.orders)}|"
            f"{orders_fingerprint}"
        )
        batch_id = (
            "reb-batch-"
            + hashlib.sha256(batch_seed.encode("utf-8")).hexdigest()[:32]
        )

        tickets: list[RebalanceFSMOrderTicket] = []
        for idx, order in enumerate(report.orders, start=1):
            phase: Literal["LIQUIDATION_SELL", "ACQUISITION_BUY"] = (
                "LIQUIDATION_SELL" if order.side == "SELL" else "ACQUISITION_BUY"
            )
            idem_seed = (
                f"{batch_id}:{idx}:{order.ticker}:{order.side}:"
                f"{order.quantity}:{order.execution_price}"
            )
            idempotency_key = (
                "reb-ord-"
                + hashlib.sha256(idem_seed.encode("utf-8")).hexdigest()[:32]
            )
            payload = order.order_intent.to_order_payload(
                quantity=order.quantity,
                portfolio_id=effective_portfolio_id,
            )
            tickets.append(
                RebalanceFSMOrderTicket(
                    sequence_number=idx,
                    execution_phase=phase,
                    idempotency_key=idempotency_key,
                    ticker=order.ticker,
                    side=order.side,
                    quantity=order.quantity,
                    execution_price=order.execution_price,
                    estimated_commission=order.estimated_commission,
                    estimated_realized_pnl=order.estimated_realized_pnl,
                    order_payload=payload,
                )
            )

        sell_count = sum(1 for t in tickets if t.side == "SELL")
        buy_count = sum(1 for t in tickets if t.side == "BUY")

        return RebalanceFSMExecutionBatch(
            batch_id=batch_id,
            portfolio_id=effective_portfolio_id,
            as_of=report.as_of,
            base_currency=report.base_currency,
            total_orders=len(tickets),
            sell_orders_count=sell_count,
            buy_orders_count=buy_count,
            tickets=tickets,
        )

