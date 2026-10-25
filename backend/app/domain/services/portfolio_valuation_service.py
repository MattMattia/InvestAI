"""
Dynamic Mark-to-Market Bimonetary Portfolio Valuation & Performance Attribution Engine
(Module 7.2 - Phase 1).

Implements:
- Bimonetary (ARS / USD) Mark-to-Market position consolidation and valuation.
- Multiplicative Karnosky-Singer currency vs. local asset return decomposition
  with exact horizontal and vertical accounting closure.
- Largest Remainder Method weight allocation guaranteeing zero rounding drift.
- GIPS-compliant Time-Weighted Return (TWR) with geometric sub-period chaining.
- Money-Weighted Return (MWR) via both Modified Dietz and an exact non-linear
  Internal Rate of Return (IRR) solver in arbitrary-precision `Decimal`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.envelope import BaseSchema

# ============================================================================
# Quantitative Constants & Defensive Boundaries
# ============================================================================
VALUATION_QUANTIZE: Decimal = Decimal("0.0001")
INTERMEDIATE_DECIMAL_PRECISION: int = 50
MAX_VALUATION_POSITIONS: int = 10_000


# ============================================================================
# Typed Domain Exception Hierarchy
# ============================================================================
class PortfolioValuationError(Exception):
    """Base domain exception for portfolio valuation and return calculations."""


class InvalidValuationInputError(PortfolioValuationError):
    """Raised when position inputs, quantities, cost basis, or cash balances are invalid."""


class MissingMarketPriceError(PortfolioValuationError):
    """Raised when a required market price is missing or non-positive."""


class InvalidFXRateError(PortfolioValuationError):
    """Raised when an exchange rate is missing, non-finite, or non-positive."""


class InvalidCashFlowPeriodError(PortfolioValuationError):
    """Raised when sub-period slices, cash flow timings, or capital bases are invalid."""


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
        quantized = value.quantize(VALUATION_QUANTIZE, rounding=ROUND_HALF_UP)
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
        raise ValueError("currency must be a valid string.")
    cleaned = value.strip().upper()
    if cleaned not in ("ARS", "USD"):
        raise ValueError(f"Unsupported currency '{cleaned}': must be 'ARS' or 'USD'.")
    return cleaned


def _allocate_largest_remainder_weights(values: Sequence[Decimal]) -> list[Decimal]:
    """
    Compute 4-decimal weights (`0.0001` resolution) that sum to `Decimal("1.0000")`
    exactly using the Largest Remainder Method (Hamilton apportionment).
    """
    if not values:
        return []

    with localcontext() as ctx:
        ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
        total = sum(values, Decimal("0"))
        if total <= Decimal("0"):
            raise InvalidValuationInputError(
                "Total market value for weight allocation must be strictly positive."
            )

        scale = Decimal(10_000)
        exact_shares = [(v / total) * scale for v in values]
        floors = [int(s // Decimal(1)) for s in exact_shares]
        remainders = [exact_shares[i] - Decimal(floors[i]) for i in range(len(values))]

        deficit = 10_000 - sum(floors)
        if deficit > 0:
            ranked_indices = sorted(
                range(len(values)),
                key=lambda idx: (-remainders[idx], idx),
            )
            for idx in ranked_indices[:deficit]:
                floors[idx] += 1
        elif deficit < 0:
            ranked_indices = sorted(
                range(len(values)),
                key=lambda idx: (remainders[idx], -idx),
            )
            for idx in ranked_indices[: abs(deficit)]:
                floors[idx] -= 1

    return [_quantize(Decimal(f) * VALUATION_QUANTIZE) for f in floors]


# ============================================================================
# Immutable DTO Contracts
# ============================================================================
class PositionValuationInput(BaseSchema):
    """
    Immutable input contract representing a single holding or tax lot to be
    valued Mark-to-Market in both ARS and USD.
    """

    ticker: str = Field(min_length=1, max_length=20)
    quantity: Decimal = Field(gt=Decimal("0"))
    avg_cost_price: Decimal = Field(ge=Decimal("0"))
    market_price: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="ARS", pattern=r"^(ARS|USD)$")
    entry_fx_rate: Decimal | None = Field(default=None, gt=Decimal("0"))

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, v: Any) -> str:
        return _validate_clean_currency(v)

    @field_validator("quantity", "avg_cost_price", "market_price", mode="before")
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator("entry_fx_rate", mode="before")
    @classmethod
    def _validate_optional_entry_fx(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, "entry_fx_rate")


class ValuedPositionBreakdown(BaseSchema):
    """
    Immutable Mark-to-Market valuation and Karnosky-Singer return decomposition
    for a consolidated asset position.
    """

    ticker: str = Field(min_length=1, max_length=20)
    native_currency: str = Field(pattern=r"^(ARS|USD)$")
    quantity: Decimal = Field(gt=Decimal("0"))
    avg_cost_price_native: Decimal = Field(ge=Decimal("0"))
    market_price_native: Decimal = Field(gt=Decimal("0"))
    cost_basis_ars: Decimal = Field(ge=Decimal("0"))
    cost_basis_usd: Decimal = Field(ge=Decimal("0"))
    market_value_ars: Decimal = Field(gt=Decimal("0"))
    market_value_usd: Decimal = Field(gt=Decimal("0"))
    unrealized_pnl_ars: Decimal
    unrealized_pnl_usd: Decimal
    unrealized_pnl_pct_ars: Decimal | None = None
    unrealized_pnl_pct_usd: Decimal | None = None
    fx_return_component: Decimal | None = None
    interaction_return_component: Decimal | None = None
    weight_in_positions: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))
    weight_in_net_worth: Decimal = Field(ge=Decimal("0"), le=Decimal("1.0000"))

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker(v)

    @field_validator("native_currency", mode="before")
    @classmethod
    def _normalize_native_currency(cls, v: Any) -> str:
        return _validate_clean_currency(v)

    @field_validator(
        "quantity",
        "avg_cost_price_native",
        "market_price_native",
        "cost_basis_ars",
        "cost_basis_usd",
        "market_value_ars",
        "market_value_usd",
        "unrealized_pnl_ars",
        "unrealized_pnl_usd",
        "weight_in_positions",
        "weight_in_net_worth",
        mode="before",
    )
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator(
        "unrealized_pnl_pct_ars",
        "unrealized_pnl_pct_usd",
        "fx_return_component",
        "interaction_return_component",
        mode="before",
    )
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_horizontal_accounting_and_karnosky_singer_closure(
        self,
    ) -> ValuedPositionBreakdown:
        expected_pnl_ars = self.market_value_ars - self.cost_basis_ars
        if self.unrealized_pnl_ars != expected_pnl_ars:
            raise ValueError(
                f"Horizontal ARS PnL closure violated for '{self.ticker}': "
                f"unrealized_pnl_ars ({self.unrealized_pnl_ars}) != "
                f"market_value_ars ({self.market_value_ars}) - cost_basis_ars ({self.cost_basis_ars})."
            )

        expected_pnl_usd = self.market_value_usd - self.cost_basis_usd
        if self.unrealized_pnl_usd != expected_pnl_usd:
            raise ValueError(
                f"Horizontal USD PnL closure violated for '{self.ticker}': "
                f"unrealized_pnl_usd ({self.unrealized_pnl_usd}) != "
                f"market_value_usd ({self.market_value_usd}) - cost_basis_usd ({self.cost_basis_usd})."
            )

        attribution_fields = (
            self.unrealized_pnl_pct_ars,
            self.unrealized_pnl_pct_usd,
            self.fx_return_component,
            self.interaction_return_component,
        )
        none_count = sum(1 for item in attribution_fields if item is None)
        if none_count not in (0, 4):
            raise ValueError(
                "Percentage attribution fields (unrealized_pnl_pct_ars, "
                "unrealized_pnl_pct_usd, fx_return_component, interaction_return_component) "
                "must either be all None or all finite Decimal values."
            )

        if none_count == 0:
            assert self.unrealized_pnl_pct_ars is not None
            assert self.unrealized_pnl_pct_usd is not None
            assert self.fx_return_component is not None
            assert self.interaction_return_component is not None
            decomposed_sum = (
                self.unrealized_pnl_pct_usd
                + self.fx_return_component
                + self.interaction_return_component
            )
            if decomposed_sum != self.unrealized_pnl_pct_ars:
                raise ValueError(
                    f"Karnosky-Singer additive closure violated for '{self.ticker}': "
                    f"r_usd ({self.unrealized_pnl_pct_usd}) + r_fx ({self.fx_return_component}) "
                    f"+ r_inter ({self.interaction_return_component}) = {decomposed_sum} "
                    f"!= r_ars ({self.unrealized_pnl_pct_ars})."
                )

        return self


class PortfolioMarkToMarketReport(BaseSchema):
    """
    Immutable consolidated Mark-to-Market valuation report in ARS and USD,
    enforcing vertical accounting closure and weight normalization invariants.
    """

    portfolio_id: str | None = None
    as_of: datetime
    fx_rate_ars_per_usd: Decimal = Field(gt=Decimal("0"))
    cash_balance_ars: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    cash_balance_usd: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    total_cost_basis_ars: Decimal = Field(ge=Decimal("0"))
    total_cost_basis_usd: Decimal = Field(ge=Decimal("0"))
    total_positions_value_ars: Decimal = Field(ge=Decimal("0"))
    total_positions_value_usd: Decimal = Field(ge=Decimal("0"))
    total_net_worth_ars: Decimal = Field(ge=Decimal("0"))
    total_net_worth_usd: Decimal = Field(ge=Decimal("0"))
    total_unrealized_pnl_ars: Decimal
    total_unrealized_pnl_usd: Decimal
    total_unrealized_pnl_pct_ars: Decimal | None = None
    total_unrealized_pnl_pct_usd: Decimal | None = None
    positions: list[ValuedPositionBreakdown] = Field(default_factory=list)

    @field_validator(
        "fx_rate_ars_per_usd",
        "cash_balance_ars",
        "cash_balance_usd",
        "total_cost_basis_ars",
        "total_cost_basis_usd",
        "total_positions_value_ars",
        "total_positions_value_usd",
        "total_net_worth_ars",
        "total_net_worth_usd",
        "total_unrealized_pnl_ars",
        "total_unrealized_pnl_usd",
        mode="before",
    )
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator(
        "total_unrealized_pnl_pct_ars",
        "total_unrealized_pnl_pct_usd",
        mode="before",
    )
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_vertical_accounting_and_weights(self) -> PortfolioMarkToMarketReport:
        sum_cost_ars = sum(
            (p.cost_basis_ars for p in self.positions), Decimal("0.0000")
        )
        sum_cost_usd = sum(
            (p.cost_basis_usd for p in self.positions), Decimal("0.0000")
        )
        sum_mkt_ars = sum(
            (p.market_value_ars for p in self.positions), Decimal("0.0000")
        )
        sum_mkt_usd = sum(
            (p.market_value_usd for p in self.positions), Decimal("0.0000")
        )

        if self.total_cost_basis_ars != sum_cost_ars:
            raise ValueError(
                f"Vertical closure error: total_cost_basis_ars ({self.total_cost_basis_ars}) "
                f"!= sum of positions ({sum_cost_ars})."
            )
        if self.total_cost_basis_usd != sum_cost_usd:
            raise ValueError(
                f"Vertical closure error: total_cost_basis_usd ({self.total_cost_basis_usd}) "
                f"!= sum of positions ({sum_cost_usd})."
            )
        if self.total_positions_value_ars != sum_mkt_ars:
            raise ValueError(
                f"Vertical closure error: total_positions_value_ars ({self.total_positions_value_ars}) "
                f"!= sum of positions ({sum_mkt_ars})."
            )
        if self.total_positions_value_usd != sum_mkt_usd:
            raise ValueError(
                f"Vertical closure error: total_positions_value_usd ({self.total_positions_value_usd}) "
                f"!= sum of positions ({sum_mkt_usd})."
            )

        if (
            self.total_unrealized_pnl_ars
            != self.total_positions_value_ars - self.total_cost_basis_ars
        ):
            raise ValueError(
                "total_unrealized_pnl_ars must equal total_positions_value_ars - total_cost_basis_ars."
            )
        if (
            self.total_unrealized_pnl_usd
            != self.total_positions_value_usd - self.total_cost_basis_usd
        ):
            raise ValueError(
                "total_unrealized_pnl_usd must equal total_positions_value_usd - total_cost_basis_usd."
            )

        if self.positions:
            sum_w_pos = sum(
                (p.weight_in_positions for p in self.positions), Decimal("0.0000")
            )
            if sum_w_pos != Decimal("1.0000"):
                raise ValueError(
                    f"Positions weight sum must equal 1.0000 (got {sum_w_pos})."
                )
            sum_w_nw = sum(
                (p.weight_in_net_worth for p in self.positions), Decimal("0.0000")
            )
            if sum_w_nw > Decimal("1.0000"):
                raise ValueError(
                    f"Net worth weight sum cannot exceed 1.0000 (got {sum_w_nw})."
                )

        return self


class SubPeriodValuationSlice(BaseSchema):
    """
    Immutable sub-period valuation slice for GIPS-compliant Time-Weighted Return (TWR).
    """

    start_value: Decimal = Field(gt=Decimal("0"))
    end_value: Decimal = Field(ge=Decimal("0"))
    net_cash_flow: Decimal = Field(default=Decimal("0.0000"))
    cash_flow_timing: Literal["START", "END"] = "END"

    @field_validator("start_value", "end_value", "net_cash_flow", mode="before")
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))


class DatedCashFlowEvent(BaseSchema):
    """
    Immutable dated external cash flow event for Modified Dietz and Exact IRR.
    `amount > 0` represents a capital contribution; `amount < 0` represents a withdrawal.
    """

    day_offset: int = Field(ge=0)
    amount: Decimal

    @field_validator("day_offset", mode="before")
    @classmethod
    def _validate_day_offset(cls, v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("day_offset must be an integer (boolean is not permitted).")
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _validate_amount(cls, v: Any) -> Decimal:
        return _coerce_finite_decimal(v, "amount")


class PerformanceReturnReport(BaseSchema):
    """
    Immutable performance attribution report combining Time-Weighted Return (TWR),
    Money-Weighted Return via Modified Dietz, Exact Non-Linear IRR, annualized
    metrics, and real USD purchasing-power return adjusted for FX devaluation.
    """

    twr: Decimal
    twr_pct: Decimal
    mwr_dietz: Decimal
    mwr_dietz_pct: Decimal
    mwr_irr: Decimal
    mwr_irr_pct: Decimal
    annualized_twr: Decimal | None = None
    annualized_mwr_irr: Decimal | None = None
    fx_devaluation_return: Decimal | None = None
    real_usd_twr: Decimal | None = None

    @field_validator(
        "twr",
        "twr_pct",
        "mwr_dietz",
        "mwr_dietz_pct",
        "mwr_irr",
        "mwr_irr_pct",
        mode="before",
    )
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator(
        "annualized_twr",
        "annualized_mwr_irr",
        "fx_devaluation_return",
        "real_usd_twr",
        mode="before",
    )
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal(v, str(info.field_name))


@dataclass
class _ConsolidatedPositionAccumulator:
    """Internal high-precision accumulator for multi-lot position consolidation."""

    ticker: str
    native_currency: str
    raw_qty: Decimal = Decimal("0")
    raw_cost_ars: Decimal = Decimal("0")
    raw_cost_usd: Decimal = Decimal("0")
    raw_mkt_ars: Decimal = Decimal("0")
    raw_mkt_usd: Decimal = Decimal("0")


# ============================================================================
# Portfolio Valuation & Performance Attribution Domain Service
# ============================================================================
class PortfolioValuationService:
    """
    Stateless quantitative domain service computing Mark-to-Market bimonetary
    valuations, Karnosky-Singer currency/asset attribution, GIPS Time-Weighted
    Return (TWR), Modified Dietz MWR, and Exact Non-Linear IRR.
    """

    @staticmethod
    def _validate_fx_rate(fx_rate: Any, name: str = "fx_rate_ars_per_usd") -> Decimal:
        if isinstance(fx_rate, bool) or fx_rate is None:
            raise InvalidFXRateError(f"{name} cannot be a boolean or None.")
        try:
            dec = _coerce_finite_decimal(fx_rate, name)
        except ValueError as exc:
            raise InvalidFXRateError(str(exc)) from exc
        if dec <= Decimal("0"):
            raise InvalidFXRateError(f"{name} must be strictly positive (got {dec}).")
        return dec

    @staticmethod
    def _validate_non_negative_input(value: Any, name: str) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise InvalidValuationInputError(f"{name} cannot be a boolean or None.")
        try:
            dec = _coerce_finite_decimal(value, name)
        except ValueError as exc:
            raise InvalidValuationInputError(str(exc)) from exc
        if dec < Decimal("0"):
            raise InvalidValuationInputError(f"{name} must be >= 0 (got {dec}).")
        return dec

    @staticmethod
    def _validate_non_negative_period_value(value: Any, name: str) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise InvalidCashFlowPeriodError(f"{name} cannot be a boolean or None.")
        try:
            dec = _coerce_finite_decimal(value, name)
        except ValueError as exc:
            raise InvalidCashFlowPeriodError(str(exc)) from exc
        if dec < Decimal("0"):
            raise InvalidCashFlowPeriodError(f"{name} must be >= 0 (got {dec}).")
        return dec

    def value_portfolio_mark_to_market(
        self,
        positions: Sequence[PositionValuationInput],
        fx_rate_ars_per_usd: Decimal,
        cash_balance_ars: Decimal = Decimal("0"),
        cash_balance_usd: Decimal = Decimal("0"),
        portfolio_id: str | None = None,
        as_of: datetime | None = None,
    ) -> PortfolioMarkToMarketReport:
        """
        Value a portfolio of positions and cash balances Mark-to-Market in both
        ARS and USD, consolidating multiple tax lots per ticker, decomposing
        Karnosky-Singer currency vs. local asset returns, and allocating exact
        weights via the Largest Remainder Method.
        """
        fx_rate = self._validate_fx_rate(fx_rate_ars_per_usd, "fx_rate_ars_per_usd")
        clean_cash_ars = self._validate_non_negative_input(
            cash_balance_ars, "cash_balance_ars"
        )
        clean_cash_usd = self._validate_non_negative_input(
            cash_balance_usd, "cash_balance_usd"
        )

        if isinstance(positions, (str, bytes)) or not isinstance(positions, Sequence):
            raise InvalidValuationInputError(
                "positions must be a sequence of PositionValuationInput instances."
            )
        if len(positions) > MAX_VALUATION_POSITIONS:
            raise InvalidValuationInputError(
                f"positions count ({len(positions)}) exceeds maximum allowed ({MAX_VALUATION_POSITIONS})."
            )

        effective_as_of = as_of if as_of is not None else datetime.now(timezone.utc)
        if not isinstance(effective_as_of, datetime) or isinstance(
            effective_as_of, bool
        ):
            raise InvalidValuationInputError("as_of must be a valid datetime instance.")

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            consolidated_map: dict[str, _ConsolidatedPositionAccumulator] = {}

            for idx, pos in enumerate(positions):
                if not isinstance(pos, PositionValuationInput):
                    raise InvalidValuationInputError(
                        f"Element at index {idx} is not a PositionValuationInput instance."
                    )
                if pos.market_price <= Decimal("0"):
                    raise MissingMarketPriceError(
                        f"Position '{pos.ticker}' has a non-positive market price ({pos.market_price})."
                    )

                lot_entry_fx = (
                    pos.entry_fx_rate if pos.entry_fx_rate is not None else fx_rate
                )
                if lot_entry_fx <= Decimal("0"):
                    raise InvalidFXRateError(
                        f"Position '{pos.ticker}' has a non-positive entry_fx_rate ({lot_entry_fx})."
                    )

                if pos.currency == "ARS":
                    lot_cost_ars = pos.quantity * pos.avg_cost_price
                    lot_cost_usd = lot_cost_ars / lot_entry_fx
                    lot_mkt_ars = pos.quantity * pos.market_price
                    lot_mkt_usd = lot_mkt_ars / fx_rate
                else:
                    lot_cost_usd = pos.quantity * pos.avg_cost_price
                    lot_cost_ars = lot_cost_usd * lot_entry_fx
                    lot_mkt_usd = pos.quantity * pos.market_price
                    lot_mkt_ars = lot_mkt_usd * fx_rate

                acc = consolidated_map.get(pos.ticker)
                if acc is None:
                    acc = _ConsolidatedPositionAccumulator(
                        ticker=pos.ticker,
                        native_currency=pos.currency,
                    )
                    consolidated_map[pos.ticker] = acc

                acc.raw_qty += pos.quantity
                acc.raw_cost_ars += lot_cost_ars
                acc.raw_cost_usd += lot_cost_usd
                acc.raw_mkt_ars += lot_mkt_ars
                acc.raw_mkt_usd += lot_mkt_usd

            consolidated_list = list(consolidated_map.values())

            if consolidated_list:
                pos_weights = _allocate_largest_remainder_weights(
                    [item.raw_mkt_usd for item in consolidated_list]
                )
                raw_total_cash_usd = clean_cash_usd + (clean_cash_ars / fx_rate)
                if raw_total_cash_usd == Decimal("0"):
                    nw_weights = list(pos_weights)
                else:
                    nw_all_weights = _allocate_largest_remainder_weights(
                        [item.raw_mkt_usd for item in consolidated_list]
                        + [raw_total_cash_usd]
                    )
                    nw_weights = nw_all_weights[: len(consolidated_list)]
            else:
                pos_weights = []
                nw_weights = []

            valued_positions: list[ValuedPositionBreakdown] = []
            for idx, item in enumerate(consolidated_list):
                q_qty = _quantize(item.raw_qty)
                if q_qty < VALUATION_QUANTIZE:
                    raise InvalidValuationInputError(
                        f"Consolidated quantity for '{item.ticker}' collapses to zero after quantization."
                    )

                if item.native_currency == "ARS":
                    avg_cost_native = _quantize(item.raw_cost_ars / item.raw_qty)
                    mkt_price_native = _quantize(item.raw_mkt_ars / item.raw_qty)
                else:
                    avg_cost_native = _quantize(item.raw_cost_usd / item.raw_qty)
                    mkt_price_native = _quantize(item.raw_mkt_usd / item.raw_qty)

                if mkt_price_native < VALUATION_QUANTIZE:
                    raise InvalidValuationInputError(
                        f"Consolidated market_price_native for '{item.ticker}' collapses to zero."
                    )

                cost_ars = _quantize(item.raw_cost_ars)
                cost_usd = _quantize(item.raw_cost_usd)
                mkt_ars = _quantize(item.raw_mkt_ars)
                mkt_usd = _quantize(item.raw_mkt_usd)

                if mkt_ars < VALUATION_QUANTIZE or mkt_usd < VALUATION_QUANTIZE:
                    raise InvalidValuationInputError(
                        f"Market value for '{item.ticker}' collapses to zero after quantization."
                    )

                pnl_ars = _quantize(mkt_ars - cost_ars)
                pnl_usd = _quantize(mkt_usd - cost_usd)

                if item.raw_cost_ars > Decimal("0") and item.raw_cost_usd > Decimal("0"):
                    r_ars_q = _quantize(
                        (item.raw_mkt_ars - item.raw_cost_ars) / item.raw_cost_ars
                    )
                    r_usd_q = _quantize(
                        (item.raw_mkt_usd - item.raw_cost_usd) / item.raw_cost_usd
                    )
                    effective_entry_fx = item.raw_cost_ars / item.raw_cost_usd
                    r_fx_q = _quantize((fx_rate / effective_entry_fx) - Decimal("1"))
                    r_inter_q = _quantize(r_ars_q - r_usd_q - r_fx_q)
                else:
                    r_ars_q = None
                    r_usd_q = None
                    r_fx_q = None
                    r_inter_q = None

                valued_positions.append(
                    ValuedPositionBreakdown(
                        ticker=item.ticker,
                        native_currency=item.native_currency,
                        quantity=q_qty,
                        avg_cost_price_native=avg_cost_native,
                        market_price_native=mkt_price_native,
                        cost_basis_ars=cost_ars,
                        cost_basis_usd=cost_usd,
                        market_value_ars=mkt_ars,
                        market_value_usd=mkt_usd,
                        unrealized_pnl_ars=pnl_ars,
                        unrealized_pnl_usd=pnl_usd,
                        unrealized_pnl_pct_ars=r_ars_q,
                        unrealized_pnl_pct_usd=r_usd_q,
                        fx_return_component=r_fx_q,
                        interaction_return_component=r_inter_q,
                        weight_in_positions=pos_weights[idx],
                        weight_in_net_worth=nw_weights[idx],
                    )
                )

            total_cost_ars = sum(
                (p.cost_basis_ars for p in valued_positions), Decimal("0.0000")
            )
            total_cost_usd = sum(
                (p.cost_basis_usd for p in valued_positions), Decimal("0.0000")
            )
            total_pos_ars = sum(
                (p.market_value_ars for p in valued_positions), Decimal("0.0000")
            )
            total_pos_usd = sum(
                (p.market_value_usd for p in valued_positions), Decimal("0.0000")
            )

            q_cash_ars = _quantize(clean_cash_ars)
            q_cash_usd = _quantize(clean_cash_usd)

            total_nw_ars = _quantize(
                total_pos_ars + q_cash_ars + (q_cash_usd * fx_rate)
            )
            total_nw_usd = _quantize(
                total_pos_usd + q_cash_usd + (q_cash_ars / fx_rate)
            )

            total_pnl_ars = _quantize(total_pos_ars - total_cost_ars)
            total_pnl_usd = _quantize(total_pos_usd - total_cost_usd)

            total_pnl_pct_ars = (
                _quantize(total_pnl_ars / total_cost_ars)
                if total_cost_ars > Decimal("0")
                else None
            )
            total_pnl_pct_usd = (
                _quantize(total_pnl_usd / total_cost_usd)
                if total_cost_usd > Decimal("0")
                else None
            )

        return PortfolioMarkToMarketReport(
            portfolio_id=portfolio_id,
            as_of=effective_as_of,
            fx_rate_ars_per_usd=_quantize(fx_rate),
            cash_balance_ars=q_cash_ars,
            cash_balance_usd=q_cash_usd,
            total_cost_basis_ars=total_cost_ars,
            total_cost_basis_usd=total_cost_usd,
            total_positions_value_ars=total_pos_ars,
            total_positions_value_usd=total_pos_usd,
            total_net_worth_ars=total_nw_ars,
            total_net_worth_usd=total_nw_usd,
            total_unrealized_pnl_ars=total_pnl_ars,
            total_unrealized_pnl_usd=total_pnl_usd,
            total_unrealized_pnl_pct_ars=total_pnl_pct_ars,
            total_unrealized_pnl_pct_usd=total_pnl_pct_usd,
            positions=valued_positions,
        )

    def calculate_twr(self, slices: Sequence[SubPeriodValuationSlice]) -> Decimal:
        """
        Compute GIPS-compliant Time-Weighted Return (TWR) by geometrically
        linking sub-period returns isolated from external cash flows:

        $$1 + R_{\\text{TWR}} = \\prod_{t=1}^{K} (1 + r_t)$$
        """
        if (
            isinstance(slices, (str, bytes))
            or not isinstance(slices, Sequence)
            or len(slices) == 0
        ):
            raise InvalidCashFlowPeriodError(
                "slices must be a non-empty sequence of SubPeriodValuationSlice."
            )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            growth_factor = Decimal("1")

            for idx, sl in enumerate(slices):
                if not isinstance(sl, SubPeriodValuationSlice):
                    raise InvalidCashFlowPeriodError(
                        f"Slice at index {idx} is not a SubPeriodValuationSlice instance."
                    )
                if sl.start_value <= Decimal("0"):
                    raise InvalidCashFlowPeriodError(
                        f"Slice at index {idx} has non-positive start_value ({sl.start_value})."
                    )

                if sl.cash_flow_timing == "END":
                    r_t = (
                        sl.end_value - sl.net_cash_flow - sl.start_value
                    ) / sl.start_value
                elif sl.cash_flow_timing == "START":
                    capital_base = sl.start_value + sl.net_cash_flow
                    if capital_base <= Decimal("0"):
                        raise InvalidCashFlowPeriodError(
                            f"Slice at index {idx} has non-positive adjusted start capital base ({capital_base})."
                        )
                    r_t = (sl.end_value - capital_base) / capital_base
                else:
                    raise InvalidCashFlowPeriodError(
                        f"Unsupported cash_flow_timing '{sl.cash_flow_timing}' at index {idx}."
                    )

                sub_factor = Decimal("1") + r_t
                if sub_factor < Decimal("0"):
                    raise InvalidCashFlowPeriodError(
                        f"Sub-period {idx} return ({r_t}) implies > 100% loss (1 + r_t < 0)."
                    )
                growth_factor *= sub_factor

            return _quantize(growth_factor - Decimal("1"))

    def calculate_mwr_modified_dietz(
        self,
        start_value: Decimal,
        end_value: Decimal,
        total_days: int,
        cash_flows: Sequence[DatedCashFlowEvent] = (),
    ) -> Decimal:
        """
        Compute Money-Weighted Return (MWR) via the Modified Dietz method:

        $$R_{\\text{Dietz}} = \\frac{V_{\\text{end}} - V_{\\text{start}} - \\sum CF_j}{V_{\\text{start}} + \\sum w_j CF_j}, \\quad w_j = \\frac{T - t_j}{T}$$
        """
        v_start = self._validate_non_negative_period_value(start_value, "start_value")
        v_end = self._validate_non_negative_period_value(end_value, "end_value")

        if isinstance(total_days, bool) or not isinstance(total_days, int) or total_days < 1:
            raise InvalidCashFlowPeriodError(
                f"total_days must be an integer >= 1 (got {total_days})."
            )
        if isinstance(cash_flows, (str, bytes)) or not isinstance(cash_flows, Sequence):
            raise InvalidCashFlowPeriodError(
                "cash_flows must be a sequence of DatedCashFlowEvent instances."
            )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            t_dec = Decimal(total_days)
            total_cf = Decimal("0")
            weighted_cf = Decimal("0")

            for idx, cf in enumerate(cash_flows):
                if not isinstance(cf, DatedCashFlowEvent):
                    raise InvalidCashFlowPeriodError(
                        f"Cash flow at index {idx} is not a DatedCashFlowEvent instance."
                    )
                if cf.day_offset < 0 or cf.day_offset > total_days:
                    raise InvalidCashFlowPeriodError(
                        f"Cash flow day_offset ({cf.day_offset}) at index {idx} must be in [0, {total_days}]."
                    )
                w_j = Decimal(total_days - cf.day_offset) / t_dec
                total_cf += cf.amount
                weighted_cf += w_j * cf.amount

            weighted_capital = v_start + weighted_cf
            if weighted_capital <= Decimal("0"):
                raise InvalidCashFlowPeriodError(
                    f"Modified Dietz weighted capital base must be strictly positive (got {weighted_capital})."
                )

            raw_dietz = (v_end - v_start - total_cf) / weighted_capital
            return _quantize(raw_dietz)

    def calculate_mwr_irr(
        self,
        start_value: Decimal,
        end_value: Decimal,
        total_days: int,
        cash_flows: Sequence[DatedCashFlowEvent] = (),
    ) -> Decimal:
        """
        Compute the exact non-linear Money-Weighted Return (Internal Rate of Return)
        over the period by solving $\\text{NPV}(r) = 0$ in 50-digit `Decimal` precision:

        $$V_{\\text{start}}(1 + r) + \\sum_{j} CF_j (1 + r)^{w_j} - V_{\\text{end}} = 0, \\quad w_j = \\frac{T - t_j}{T}$$
        """
        dietz_return = self.calculate_mwr_modified_dietz(
            start_value=start_value,
            end_value=end_value,
            total_days=total_days,
            cash_flows=cash_flows,
        )
        v_start = self._validate_non_negative_period_value(start_value, "start_value")
        v_end = self._validate_non_negative_period_value(end_value, "end_value")

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            t_dec = Decimal(total_days)

            # Group cash flows by day_offset
            grouped_cf: dict[int, Decimal] = {}
            for cf in cash_flows:
                grouped_cf[cf.day_offset] = (
                    grouped_cf.get(cf.day_offset, Decimal("0")) + cf.amount
                )

            cf_start = grouped_cf.pop(0, Decimal("0"))
            cf_end = grouped_cf.pop(total_days, Decimal("0"))
            interior_terms: list[tuple[Decimal, Decimal]] = [
                (Decimal(total_days - day) / t_dec, amt)
                for day, amt in sorted(grouped_cf.items())
                if amt != Decimal("0")
            ]

            effective_start = v_start + cf_start
            effective_end = v_end - cf_end

            # Linear exact reduction when no interior cash flows exist (all w_j in {0, 1})
            if not interior_terms:
                if effective_start <= Decimal("0"):
                    return dietz_return
                exact_linear = (effective_end / effective_start) - Decimal("1")
                return _quantize(exact_linear)

            # Total loss boundary check: V_end == 0, CF_end == 0, and all earlier flows >= 0
            if (
                effective_end == Decimal("0")
                and effective_start >= Decimal("0")
                and all(amt >= Decimal("0") for _, amt in interior_terms)
            ):
                return Decimal("-1.0000")

            def _eval_f_and_df(u: Decimal) -> tuple[Decimal, Decimal]:
                """Evaluate f(u) and f'(u) where u = 1 + r > 0."""
                ln_u = u.ln()
                f_val = effective_start * u - effective_end
                df_val = effective_start
                for w_j, amt in interior_terms:
                    u_pow_w = (w_j * ln_u).exp()
                    f_val += amt * u_pow_w
                    df_val += amt * w_j * (u_pow_w / u)
                return f_val, df_val

            u_guess = max(Decimal("0.0001"), Decimal("1") + dietz_return)
            grid = sorted(
                {
                    Decimal("0.000001"),
                    Decimal("0.001"),
                    Decimal("0.01"),
                    Decimal("0.1"),
                    Decimal("0.25"),
                    Decimal("0.5"),
                    Decimal("0.75"),
                    Decimal("1.0"),
                    u_guess,
                    Decimal("1.25"),
                    Decimal("1.5"),
                    Decimal("2.0"),
                    Decimal("5.0"),
                    Decimal("10.0"),
                    Decimal("50.0"),
                    Decimal("200.0"),
                }
            )

            bracket_low: Decimal | None = None
            bracket_high: Decimal | None = None
            f_low = Decimal("0")
            f_high = Decimal("0")

            prev_u = grid[0]
            prev_f, _ = _eval_f_and_df(prev_u)
            if abs(prev_f) <= Decimal("1e-12"):
                return _quantize(prev_u - Decimal("1"))

            for cand_u in grid[1:]:
                cand_f, _ = _eval_f_and_df(cand_u)
                if abs(cand_f) <= Decimal("1e-12"):
                    return _quantize(cand_u - Decimal("1"))
                if (prev_f < Decimal("0") < cand_f) or (
                    prev_f > Decimal("0") > cand_f
                ):
                    bracket_low = prev_u
                    bracket_high = cand_u
                    f_low = prev_f
                    f_high = cand_f
                    break
                prev_u = cand_u
                prev_f = cand_f

            if bracket_low is None or bracket_high is None:
                return dietz_return

            u_curr = (
                u_guess
                if bracket_low < u_guess < bracket_high
                else (bracket_low + bracket_high) / Decimal("2")
            )
            tol = Decimal("1e-12")

            for _ in range(80):
                f_curr, df_curr = _eval_f_and_df(u_curr)
                if abs(f_curr) <= tol or abs(bracket_high - bracket_low) <= Decimal(
                    "1e-14"
                ):
                    break

                if (f_low < Decimal("0") and f_curr < Decimal("0")) or (
                    f_low > Decimal("0") and f_curr > Decimal("0")
                ):
                    bracket_low = u_curr
                    f_low = f_curr
                else:
                    bracket_high = u_curr
                    f_high = f_curr

                if df_curr != Decimal("0"):
                    newton_u = u_curr - (f_curr / df_curr)
                else:
                    newton_u = bracket_low

                if bracket_low < newton_u < bracket_high:
                    u_curr = newton_u
                else:
                    u_curr = (bracket_low + bracket_high) / Decimal("2")

            return _quantize(u_curr - Decimal("1"))

    @staticmethod
    def _annualize_return(period_return: Decimal, total_days: int) -> Decimal | None:
        """
        Compound a period return over `365 / total_days`:
        $$(1 + R)^{365 / D} - 1$$
        Returns `None` if `1 + R < 0` or if `365 / total_days > 20` (short-window overflow guard).
        """
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            exponent = Decimal(365) / Decimal(total_days)
            if exponent > Decimal(20):
                return None

            base = Decimal("1") + period_return
            if base < Decimal("0"):
                return None
            if base == Decimal("0"):
                return Decimal("-1.0000")

            annualized = (exponent * base.ln()).exp() - Decimal("1")
            return _quantize(annualized)

    def evaluate_performance_metrics(
        self,
        slices: Sequence[SubPeriodValuationSlice],
        start_value: Decimal,
        end_value: Decimal,
        total_days: int,
        cash_flows: Sequence[DatedCashFlowEvent] = (),
        start_fx_rate: Decimal | None = None,
        end_fx_rate: Decimal | None = None,
    ) -> PerformanceReturnReport:
        """
        Compute a consolidated `PerformanceReturnReport` with TWR, Modified Dietz MWR,
        Exact Non-Linear IRR, compounded annualized returns, and real USD return
        adjusted for ARS/USD exchange rate devaluation.
        """
        if (start_fx_rate is None) ^ (end_fx_rate is None):
            raise InvalidFXRateError(
                "Both start_fx_rate and end_fx_rate must be provided together, or both omitted."
            )

        clean_start_fx: Decimal | None = None
        clean_end_fx: Decimal | None = None
        if start_fx_rate is not None and end_fx_rate is not None:
            clean_start_fx = self._validate_fx_rate(start_fx_rate, "start_fx_rate")
            clean_end_fx = self._validate_fx_rate(end_fx_rate, "end_fx_rate")

        twr = self.calculate_twr(slices)
        mwr_dietz = self.calculate_mwr_modified_dietz(
            start_value=start_value,
            end_value=end_value,
            total_days=total_days,
            cash_flows=cash_flows,
        )
        mwr_irr = self.calculate_mwr_irr(
            start_value=start_value,
            end_value=end_value,
            total_days=total_days,
            cash_flows=cash_flows,
        )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            twr_pct = _quantize(twr * Decimal("100"))
            mwr_dietz_pct = _quantize(mwr_dietz * Decimal("100"))
            mwr_irr_pct = _quantize(mwr_irr * Decimal("100"))

            ann_twr = self._annualize_return(twr, total_days)
            ann_irr = self._annualize_return(mwr_irr, total_days)

            fx_deval: Decimal | None = None
            real_usd_twr: Decimal | None = None
            if clean_start_fx is not None and clean_end_fx is not None:
                fx_ratio = clean_end_fx / clean_start_fx
                fx_deval = _quantize(fx_ratio - Decimal("1"))
                real_usd_twr = _quantize(
                    ((Decimal("1") + twr) / (Decimal("1") + fx_deval)) - Decimal("1")
                )

        return PerformanceReturnReport(
            twr=twr,
            twr_pct=twr_pct,
            mwr_dietz=mwr_dietz,
            mwr_dietz_pct=mwr_dietz_pct,
            mwr_irr=mwr_irr,
            mwr_irr_pct=mwr_irr_pct,
            annualized_twr=ann_twr,
            annualized_mwr_irr=ann_irr,
            fx_devaluation_return=fx_deval,
            real_usd_twr=real_usd_twr,
        )
