"""
Dynamic Tolerance-Band Portfolio Rebalancing Engine (Module 7.3 - Phase 1).

Implements:
- Absolute, Relative, and Dynamic Volatility-Scaled tolerance corridors
  ($w_i^* \\pm \\theta_i$) with configurable minimum/maximum half-width bounds.
- Full-to-Target (`FULL_TO_TARGET`) and Minimum-Turnover Band-Boundary
  (`TO_BAND_BOUNDARY`) rebalancing modes.
- Self-Financing Liquidity Waterfall (Sell-Before-Buy) guaranteeing zero cash
  overdraft (`projected_ending_cash >= 0`) after transaction commissions and
  target cash buffer reserves.
- Direct integration with `PortfolioMarkToMarketReport` (Module 7.2) and
  `OrderFSMIntent` (Module 7.1 / Module 1.3).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from enum import Enum
import math
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from app.domain.services.portfolio_valuation_service import PortfolioMarkToMarketReport
from app.domain.services.signal_generator import OrderFSMIntent
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
    Immutable current holding position input for tolerance-band evaluation.
    """

    ticker: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(ge=Decimal("0"))
    market_price: Decimal = Field(gt=Decimal("0"))

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator("quantity", "market_price", mode="before")
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))


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
    destination mode, transaction commissions, lot rounding, and cash buffer.
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

    @field_validator("allow_fractional_shares", "liquidate_unlisted_holdings", mode="before")
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
    Immutable per-asset corridor evaluation, drift measurement, and destination weight.
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
        mode="before",
    )
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))


class RebalanceTradeOrder(BaseSchema):
    """
    Immutable rebalance trade order with gross notional, estimated commission,
    net cash impact, and transactional `OrderFSMIntent`.
    """

    ticker: str = Field(min_length=1, max_length=20)
    side: Literal["SELL", "BUY"]
    quantity: Decimal = Field(gt=Decimal("0"))
    execution_price: Decimal = Field(gt=Decimal("0"))
    gross_amount: Decimal = Field(gt=Decimal("0"))
    estimated_commission: Decimal = Field(ge=Decimal("0"))
    net_cash_impact: Decimal
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
        return self


class ToleranceBandRebalanceReport(BaseSchema):
    """
    Immutable consolidated tolerance-band rebalancing report enforcing exact
    cash accounting closure, zero overdraft, and Sell-Before-Buy ordering.
    """

    portfolio_id: str | None = None
    as_of: datetime
    base_currency: str = Field(default="USD", pattern=r"^(ARS|USD)$")
    rebalance_mode: RebalanceMode
    band_type: BandType
    needs_rebalancing: bool
    breached_tickers: list[str] = Field(default_factory=list)
    total_portfolio_value: Decimal = Field(gt=Decimal("0"))
    initial_cash: Decimal = Field(ge=Decimal("0"))
    projected_ending_cash: Decimal = Field(ge=Decimal("0"))
    total_sell_gross: Decimal = Field(ge=Decimal("0"))
    total_buy_gross: Decimal = Field(ge=Decimal("0"))
    total_estimated_commissions: Decimal = Field(ge=Decimal("0"))
    portfolio_turnover: Decimal = Field(ge=Decimal("0"))
    evaluations: list[AssetBandEvaluation] = Field(default_factory=list)
    orders: list[RebalanceTradeOrder] = Field(default_factory=list)

    @field_validator("base_currency", mode="before")
    @classmethod
    def _normalize_base_currency(cls, v: Any) -> str:
        return _validate_clean_currency(v)

    @field_validator(
        "total_portfolio_value",
        "initial_cash",
        "projected_ending_cash",
        "total_sell_gross",
        "total_buy_gross",
        "total_estimated_commissions",
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


@dataclass
class _PositionAccumulator:
    """Internal accumulator for consolidating duplicate position lots."""

    ticker: str
    raw_qty: Decimal = Decimal("0")
    raw_val: Decimal = Decimal("0")
    last_price: Decimal = Decimal("0")


# ============================================================================
# Tolerance-Band Rebalancer Domain Service
# ============================================================================
class ToleranceBandRebalancerService:
    """
    Stateless quantitative domain service monitoring portfolio drift against
    absolute, relative, or volatility-scaled tolerance bands and generating
    self-financing rebalance trade orders.
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
        asset breaches its corridor.
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
                else:
                    curr_qty = Decimal("0.0000")
                    mkt_price = self._resolve_external_price(
                        ticker, spec, normalized_prices
                    )
                    curr_val = Decimal("0.0000")

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

            needs_rebalancing = len(breached_tickers) > 0
            evaluations: list[AssetBandEvaluation] = []

            for item in prelim_evals:
                if not needs_rebalancing:
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

                evaluations.append(
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
                        destination_weight=dest_weight,
                    )
                )

            if not needs_rebalancing:
                return ToleranceBandRebalanceReport(
                    portfolio_id=portfolio_id,
                    as_of=effective_as_of,
                    base_currency=clean_currency,
                    rebalance_mode=self._config.rebalance_mode,
                    band_type=self._config.band_type,
                    needs_rebalancing=False,
                    breached_tickers=[],
                    total_portfolio_value=total_portfolio_value,
                    initial_cash=q_initial_cash,
                    projected_ending_cash=q_initial_cash,
                    total_sell_gross=Decimal("0.0000"),
                    total_buy_gross=Decimal("0.0000"),
                    total_estimated_commissions=Decimal("0.0000"),
                    portfolio_turnover=Decimal("0.0000"),
                    evaluations=evaluations,
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
            buy_candidates: list[tuple[Decimal, AssetBandEvaluation]] = []

            for ev in evaluations:
                dest_value = total_portfolio_value * ev.destination_weight
                if ev.current_value > dest_value and ev.current_quantity > Decimal("0"):
                    if ev.destination_weight == Decimal("0.0000"):
                        if self._config.allow_fractional_shares:
                            sell_qty = ev.current_quantity
                        else:
                            sell_qty = ev.current_quantity.quantize(
                                qty_step, rounding=ROUND_FLOOR
                            )
                    else:
                        raw_sell_qty = (ev.current_value - dest_value) / ev.market_price
                        floored_qty = raw_sell_qty.quantize(
                            qty_step, rounding=ROUND_FLOOR
                        )
                        sell_qty = min(ev.current_quantity, floored_qty)

                    q_sell_qty = _quantize(sell_qty)
                    if q_sell_qty > Decimal("0"):
                        gross = _quantize(q_sell_qty * ev.market_price)
                        if gross >= self._config.min_trade_notional:
                            commission = _quantize(gross * comm_rate)
                            net_impact = _quantize(gross - commission)
                            conviction = min(
                                Decimal("1.0000"),
                                max(Decimal("0.0001"), _quantize(abs(ev.drift_weight))),
                            )
                            intent = OrderFSMIntent(
                                ticker=ev.ticker,
                                side="SELL",
                                target_status="PENDING",
                                reference_price=ev.market_price,
                                signal_conviction=conviction,
                            )
                            sell_orders.append(
                                RebalanceTradeOrder(
                                    ticker=ev.ticker,
                                    side="SELL",
                                    quantity=q_sell_qty,
                                    execution_price=ev.market_price,
                                    gross_amount=gross,
                                    estimated_commission=commission,
                                    net_cash_impact=net_impact,
                                    order_intent=intent,
                                )
                            )
                elif dest_value > ev.current_value:
                    deficit = dest_value - ev.current_value
                    if deficit > Decimal("0"):
                        buy_candidates.append((deficit, ev))

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
                buy_candidates.sort(key=lambda item: (-item[0], item[1].ticker))

                for deficit, ev in buy_candidates:
                    if remaining_cash <= Decimal("0"):
                        break
                    allocated_gross_budget = min(
                        deficit * scale,
                        remaining_cash / (Decimal("1") + comm_rate),
                    )
                    if allocated_gross_budget <= Decimal("0"):
                        continue

                    raw_buy_qty = allocated_gross_budget / ev.market_price
                    buy_qty = raw_buy_qty.quantize(qty_step, rounding=ROUND_FLOOR)

                    gross = Decimal("0.0000")
                    commission = Decimal("0.0000")
                    while buy_qty > Decimal("0"):
                        gross = _quantize(buy_qty * ev.market_price)
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
                            max(Decimal("0.0001"), _quantize(abs(ev.drift_weight))),
                        )
                        intent = OrderFSMIntent(
                            ticker=ev.ticker,
                            side="BUY",
                            target_status="PENDING",
                            reference_price=ev.market_price,
                            signal_conviction=conviction,
                        )
                        buy_orders.append(
                            RebalanceTradeOrder(
                                ticker=ev.ticker,
                                side="BUY",
                                quantity=q_buy_qty,
                                execution_price=ev.market_price,
                                gross_amount=gross,
                                estimated_commission=commission,
                                net_cash_impact=-total_outflow,
                                order_intent=intent,
                            )
                        )

            buy_orders.sort(key=lambda o: (-o.gross_amount, o.ticker))
            all_orders = sell_orders + buy_orders

            total_sell_gross = sum(
                (o.gross_amount for o in sell_orders), Decimal("0.0000")
            )
            total_buy_gross = sum(
                (o.gross_amount for o in buy_orders), Decimal("0.0000")
            )
            total_commissions = sum(
                (o.estimated_commission for o in all_orders), Decimal("0.0000")
            )
            projected_ending_cash = _quantize(
                q_initial_cash
                + total_sell_gross
                - total_buy_gross
                - total_commissions
            )
            portfolio_turnover = _quantize(
                (total_sell_gross + total_buy_gross)
                / (Decimal("2") * total_portfolio_value)
            )

        return ToleranceBandRebalanceReport(
            portfolio_id=portfolio_id,
            as_of=effective_as_of,
            base_currency=clean_currency,
            rebalance_mode=self._config.rebalance_mode,
            band_type=self._config.band_type,
            needs_rebalancing=True,
            breached_tickers=breached_tickers,
            total_portfolio_value=total_portfolio_value,
            initial_cash=q_initial_cash,
            projected_ending_cash=projected_ending_cash,
            total_sell_gross=total_sell_gross,
            total_buy_gross=total_buy_gross,
            total_estimated_commissions=total_commissions,
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
        in either `'USD'` or `'ARS'` base currency.
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
                else:
                    unit_price = _quantize(pos.market_value_ars / pos.quantity)

                rebalance_positions.append(
                    RebalancePositionInput(
                        ticker=pos.ticker,
                        quantity=pos.quantity,
                        market_price=unit_price,
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
