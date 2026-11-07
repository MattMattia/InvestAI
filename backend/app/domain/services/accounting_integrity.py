"""
Accounting integrity service and fundamental ratio evaluation engine
(Module 6.2 - Phase 2).

Implements deterministic labeling of pathological financial multiples
(EPS <= 0, negative book value, currency mismatches, delisted assets, and
micro-denominator overflows) as `INDETERMINATE` without division-by-zero traps.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.schemas.envelope import BaseSchema

# ============================================================================
# Quantitative & Numerical Stability Constants
# ============================================================================
RATIO_QUANTIZE_EXP: Decimal = Decimal("0.0001")
MAX_RATIONAL_PE: Decimal = Decimal("1000.0000")
MAX_COMPUTABLE_RATIO: Decimal = Decimal("1000000000.0000")  # 10^9 ceiling


class RatioStatus(str, Enum):
    """Canonical validity status for a fundamental financial ratio."""

    VALID = "VALID"
    INDETERMINATE = "INDETERMINATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AccountingRiskFlag(str, Enum):
    """Taxonomic risk flags emitted when accounting anomalies are detected."""

    ZERO_EARNINGS = "ZERO_EARNINGS"
    NEGATIVE_EARNINGS = "NEGATIVE_EARNINGS"
    EXTREME_PE_OUTLIER = "EXTREME_PE_OUTLIER"
    NEGATIVE_BOOK_VALUE = "NEGATIVE_BOOK_VALUE"
    NON_POSITIVE_GROWTH = "NON_POSITIVE_GROWTH"
    NEGATIVE_DIVIDEND = "NEGATIVE_DIVIDEND"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    DELISTED_OR_INVALID_PRICE = "DELISTED_OR_INVALID_PRICE"


_RISK_FLAG_WARNING_MESSAGES: dict[AccountingRiskFlag, str] = {
    AccountingRiskFlag.ZERO_EARNINGS: (
        "Earnings are zero (EPS = 0 or Net Income = 0); earnings-based multiples are indeterminate."
    ),
    AccountingRiskFlag.NEGATIVE_EARNINGS: (
        "Company reported negative earnings (EPS < 0 or Net Income < 0); P/E and PEG are indeterminate."
    ),
    AccountingRiskFlag.EXTREME_PE_OUTLIER: (
        "P/E multiple exceeds rational valuation bounds (> 1000x) due to near-zero earnings."
    ),
    AccountingRiskFlag.NEGATIVE_BOOK_VALUE: (
        "Shareholders' equity or book value per share is non-positive (<= 0); P/B and ROE are indeterminate."
    ),
    AccountingRiskFlag.NON_POSITIVE_GROWTH: (
        "Projected EPS growth rate is non-positive (<= 0%); PEG ratio is indeterminate."
    ),
    AccountingRiskFlag.NEGATIVE_DIVIDEND: (
        "Reported dividends per share are negative (< 0); dividend yield is indeterminate."
    ),
    AccountingRiskFlag.CURRENCY_MISMATCH: (
        "Currency mismatch between market price and financial statements without a valid FX rate."
    ),
    AccountingRiskFlag.DELISTED_OR_INVALID_PRICE: (
        "Instrument is delisted or has a non-positive market price; price-based ratios are indeterminate."
    ),
}


class RatioValue(BaseSchema):
    """
    Immutable representation of a single fundamental ratio and its semantic status.
    """

    value: Decimal | None = None
    status: RatioStatus
    reason: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _reject_bool_and_non_finite_value(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError("Boolean values are not permitted for RatioValue.value")
        if isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError("Non-finite float is not permitted")
            v = Decimal(str(v))
        elif isinstance(v, int):
            v = Decimal(v)
        if isinstance(v, Decimal):
            if not v.is_finite():
                raise ValueError("RatioValue.value must be finite")
            return v
        raise ValueError(f"Unsupported type for RatioValue.value: {type(v).__name__}")

    @model_validator(mode="after")
    def _enforce_status_value_consistency(self) -> RatioValue:
        if self.status == RatioStatus.VALID:
            if self.value is None or not self.value.is_finite():
                raise ValueError(
                    "RatioValue with status=VALID must have a finite non-null Decimal value"
                )
        else:
            if self.value is not None:
                raise ValueError(f"RatioValue with status={self.status.value} must have value=None")
        return self


def _coerce_finite_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Boolean value is not permitted for '{field_name}'")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float is not permitted for '{field_name}'")
        dec = Decimal(str(value))
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, Decimal):
        dec = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            dec = Decimal(stripped)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid Decimal string for '{field_name}'") from exc
    else:
        raise ValueError(f"Unsupported type '{type(value).__name__}' for '{field_name}'")

    if not dec.is_finite():
        raise ValueError(f"Non-finite Decimal is not permitted for '{field_name}'")
    return dec


class FundamentalInputs(BaseSchema):
    """
    Immutable fundamental accounting and market price inputs for a single company.
    """

    ticker: str = Field(min_length=1, max_length=20)
    price: Decimal | None = None
    eps: Decimal | None = None
    bvps: Decimal | None = None
    eps_growth_pct: Decimal | None = None
    dividends_per_share: Decimal | None = None
    net_income: Decimal | None = None
    shareholders_equity: Decimal | None = None
    price_currency: str = Field(default="ARS", pattern=r"^(ARS|USD)$")
    financials_currency: str = Field(default="ARS", pattern=r"^(ARS|USD)$")
    fx_rate: Decimal | None = None
    conversion_ratio: Decimal = Field(default=Decimal("1"), gt=0)
    is_delisted: bool = False

    @field_validator("ticker", mode="before")
    @classmethod
    def _validate_ticker(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("ticker must be a string")
        if any(ctrl in v for ctrl in ("\r", "\n", "\t", "\x00")):
            raise ValueError("Control characters are not permitted in ticker")
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("ticker cannot be empty")
        return cleaned

    @field_validator(
        "price",
        "eps",
        "bvps",
        "eps_growth_pct",
        "dividends_per_share",
        "net_income",
        "shareholders_equity",
        "fx_rate",
        mode="before",
    )
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        return _coerce_finite_decimal(v, str(info.field_name))

    @field_validator("conversion_ratio", mode="before")
    @classmethod
    def _validate_conversion_ratio(cls, v: Any) -> Decimal:
        dec = _coerce_finite_decimal(v, "conversion_ratio")
        if dec is None:
            raise ValueError("conversion_ratio cannot be None")
        return dec


class FinancialMetricsReport(BaseSchema):
    """
    Immutable fundamental evaluation report for an instrument, containing all
    computed ratios, accounting risk flags, and human-readable warnings.
    """

    ticker: str
    pe_ratio: RatioValue
    pb_ratio: RatioValue
    peg_ratio: RatioValue
    dividend_yield: RatioValue
    roe: RatioValue
    risk_flags: list[AccountingRiskFlag] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def has_accounting_anomalies(self) -> bool:
        """Return True if any accounting or valuation anomaly flag was triggered."""
        return len(self.risk_flags) > 0


class AccountingIntegrityService:
    """
    Pure domain service evaluating fundamental valuation and profitability
    multiples with defensive protection against non-positive denominators,
    negative book equity, currency mismatches, and near-zero EPS overflows.
    """

    @staticmethod
    def _safe_quantize_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
        """
        Safely divide `numerator / denominator` and quantize to 4 decimal places.
        Returns `None` if denominator is zero, result is non-finite, or magnitude
        exceeds `MAX_COMPUTABLE_RATIO` (preventing `decimal.InvalidOperation`).
        Normalizes `-0.0000` to positive `0.0000`.
        """
        if denominator == Decimal("0"):
            return None
        try:
            raw_ratio = numerator / denominator
            if not raw_ratio.is_finite():
                return None
            if abs(raw_ratio) > MAX_COMPUTABLE_RATIO:
                return None
            quantized = raw_ratio.quantize(RATIO_QUANTIZE_EXP, rounding=ROUND_HALF_UP)
            if quantized == Decimal("0"):
                return Decimal("0.0000")
            return quantized
        except (InvalidOperation, DivisionByZero, OverflowError):
            return None

    @staticmethod
    def _resolve_effective_price(
        inputs: FundamentalInputs,
    ) -> tuple[Decimal | None, str | None, list[AccountingRiskFlag]]:
        """
        Validate market price, apply ADR/CEDEAR `conversion_ratio`, and homogenize
        into `financials_currency` using `fx_rate` when currencies differ.
        """
        if inputs.is_delisted or inputs.price is None or inputs.price <= Decimal("0"):
            return (
                None,
                "Asset is delisted or has a non-positive market price",
                [AccountingRiskFlag.DELISTED_OR_INVALID_PRICE],
            )

        if inputs.price_currency != inputs.financials_currency:
            if inputs.fx_rate is None or inputs.fx_rate <= Decimal("0"):
                return (
                    None,
                    "Currency mismatch between price and financials without valid FX rate",
                    [AccountingRiskFlag.CURRENCY_MISMATCH],
                )

        try:
            adjusted_price = inputs.price * inputs.conversion_ratio
            if inputs.price_currency == inputs.financials_currency:
                effective_price = adjusted_price
            elif inputs.price_currency == "ARS" and inputs.financials_currency == "USD":
                assert inputs.fx_rate is not None
                effective_price = adjusted_price / inputs.fx_rate
            else:
                assert inputs.fx_rate is not None
                effective_price = adjusted_price * inputs.fx_rate
        except (InvalidOperation, DivisionByZero, OverflowError):
            return (
                None,
                "Effective market price calculation overflowed or failed",
                [AccountingRiskFlag.DELISTED_OR_INVALID_PRICE],
            )

        if not effective_price.is_finite() or effective_price <= Decimal("0"):
            return (
                None,
                "Effective market price collapsed to non-positive or non-finite value",
                [AccountingRiskFlag.DELISTED_OR_INVALID_PRICE],
            )

        return effective_price, None, []

    @classmethod
    def calculate_pe_ratio(
        cls,
        effective_price: Decimal,
        eps: Decimal | None,
    ) -> tuple[RatioValue, list[AccountingRiskFlag]]:
        """
        Compute Price-to-Earnings (P/E) ratio.
        Labels `eps <= 0` as `INDETERMINATE` and flags extreme micro-EPS outliers.
        """
        if eps is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.NOT_APPLICABLE,
                    reason="EPS not provided",
                ),
                [],
            )

        if eps == Decimal("0"):
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Zero earnings per share (EPS = 0)",
                ),
                [AccountingRiskFlag.ZERO_EARNINGS],
            )

        if eps < Decimal("0"):
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Negative earnings per share (EPS < 0)",
                ),
                [AccountingRiskFlag.NEGATIVE_EARNINGS],
            )

        quantized = cls._safe_quantize_ratio(effective_price, eps)
        if quantized is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="P/E overflow due to infinitesimal positive EPS",
                ),
                [AccountingRiskFlag.EXTREME_PE_OUTLIER],
            )

        flags: list[AccountingRiskFlag] = []
        reason: str | None = None
        if quantized > MAX_RATIONAL_PE:
            flags.append(AccountingRiskFlag.EXTREME_PE_OUTLIER)
            reason = f"Extreme P/E multiple ({quantized}) exceeds {MAX_RATIONAL_PE}"

        return (
            RatioValue(
                value=quantized,
                status=RatioStatus.VALID,
                reason=reason,
            ),
            flags,
        )

    @classmethod
    def calculate_pb_ratio(
        cls,
        effective_price: Decimal,
        bvps: Decimal | None,
    ) -> tuple[RatioValue, list[AccountingRiskFlag]]:
        """
        Compute Price-to-Book (P/B) ratio.
        Labels non-positive book value (`bvps <= 0`) as `INDETERMINATE`.
        """
        if bvps is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.NOT_APPLICABLE,
                    reason="Book value per share (BVPS) not provided",
                ),
                [],
            )

        if bvps <= Decimal("0"):
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Non-positive book value per share (BVPS <= 0)",
                ),
                [AccountingRiskFlag.NEGATIVE_BOOK_VALUE],
            )

        quantized = cls._safe_quantize_ratio(effective_price, bvps)
        if quantized is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="P/B overflow due to infinitesimal BVPS",
                ),
                [AccountingRiskFlag.NEGATIVE_BOOK_VALUE],
            )

        return (
            RatioValue(value=quantized, status=RatioStatus.VALID, reason=None),
            [],
        )

    @classmethod
    def calculate_peg_ratio(
        cls,
        pe_ratio: RatioValue,
        eps_growth_pct: Decimal | None,
    ) -> tuple[RatioValue, list[AccountingRiskFlag]]:
        """
        Compute Price/Earnings-to-Growth (PEG) ratio.
        Requires a `VALID` P/E ratio and strictly positive `eps_growth_pct > 0`.
        """
        if pe_ratio.status != RatioStatus.VALID or pe_ratio.value is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="PEG cannot be computed because P/E is indeterminate or unavailable",
                ),
                [],
            )

        if eps_growth_pct is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.NOT_APPLICABLE,
                    reason="Projected EPS growth rate not provided",
                ),
                [],
            )

        if eps_growth_pct <= Decimal("0"):
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Non-positive projected EPS growth rate (<= 0%)",
                ),
                [AccountingRiskFlag.NON_POSITIVE_GROWTH],
            )

        quantized = cls._safe_quantize_ratio(pe_ratio.value, eps_growth_pct)
        if quantized is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="PEG overflow due to near-zero EPS growth rate",
                ),
                [AccountingRiskFlag.NON_POSITIVE_GROWTH],
            )

        return (
            RatioValue(value=quantized, status=RatioStatus.VALID, reason=None),
            [],
        )

    @classmethod
    def calculate_dividend_yield(
        cls,
        effective_price: Decimal,
        dps: Decimal | None,
    ) -> tuple[RatioValue, list[AccountingRiskFlag]]:
        """
        Compute Dividend Yield (`dps / effective_price`).
        Labels negative dividends (`dps < 0`) as `INDETERMINATE`.
        """
        if dps is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.NOT_APPLICABLE,
                    reason="Dividends per share not provided",
                ),
                [],
            )

        if dps < Decimal("0"):
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Negative dividends per share (DPS < 0)",
                ),
                [AccountingRiskFlag.NEGATIVE_DIVIDEND],
            )

        quantized = cls._safe_quantize_ratio(dps, effective_price)
        if quantized is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Dividend yield overflow",
                ),
                [],
            )

        return (
            RatioValue(value=quantized, status=RatioStatus.VALID, reason=None),
            [],
        )

    @classmethod
    def calculate_roe(
        cls,
        net_income: Decimal | None,
        equity: Decimal | None,
    ) -> tuple[RatioValue, list[AccountingRiskFlag]]:
        """
        Compute Return on Equity (`net_income / shareholders_equity`).
        Blocks the pathological double-negative trap (`net_income < 0` and `equity < 0`)
        by labeling any `equity <= 0` as `INDETERMINATE`.
        """
        if net_income is None or equity is None:
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.NOT_APPLICABLE,
                    reason="Net income or shareholders' equity not provided",
                ),
                [],
            )

        flags: list[AccountingRiskFlag] = []
        if net_income < Decimal("0"):
            flags.append(AccountingRiskFlag.NEGATIVE_EARNINGS)
        elif net_income == Decimal("0"):
            flags.append(AccountingRiskFlag.ZERO_EARNINGS)

        if equity <= Decimal("0"):
            flags.append(AccountingRiskFlag.NEGATIVE_BOOK_VALUE)
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="Non-positive shareholders' equity (<= 0)",
                ),
                flags,
            )

        quantized = cls._safe_quantize_ratio(net_income, equity)
        if quantized is None:
            flags.append(AccountingRiskFlag.NEGATIVE_BOOK_VALUE)
            return (
                RatioValue(
                    value=None,
                    status=RatioStatus.INDETERMINATE,
                    reason="ROE overflow due to near-zero shareholders' equity",
                ),
                flags,
            )

        return (
            RatioValue(value=quantized, status=RatioStatus.VALID, reason=None),
            flags,
        )

    def evaluate_company_metrics(self, inputs: FundamentalInputs) -> FinancialMetricsReport:
        """
        Evaluate all fundamental ratios for a company and consolidate risk flags
        and warnings deterministically.
        """
        collected_flags: list[AccountingRiskFlag] = []

        effective_price, price_error_reason, price_flags = self._resolve_effective_price(inputs)
        collected_flags.extend(price_flags)

        if effective_price is None:
            indeterminate_price_ratio = RatioValue(
                value=None,
                status=RatioStatus.INDETERMINATE,
                reason=price_error_reason,
            )
            pe_ratio = indeterminate_price_ratio
            pb_ratio = indeterminate_price_ratio
            peg_ratio = indeterminate_price_ratio
            dividend_yield = indeterminate_price_ratio

            # Still inspect EPS and BVPS so negative earnings/equity flags are surfaced
            if inputs.eps is not None:
                if inputs.eps == Decimal("0"):
                    collected_flags.append(AccountingRiskFlag.ZERO_EARNINGS)
                elif inputs.eps < Decimal("0"):
                    collected_flags.append(AccountingRiskFlag.NEGATIVE_EARNINGS)
            if inputs.bvps is not None and inputs.bvps <= Decimal("0"):
                collected_flags.append(AccountingRiskFlag.NEGATIVE_BOOK_VALUE)
        else:
            pe_ratio, pe_flags = self.calculate_pe_ratio(effective_price, inputs.eps)
            collected_flags.extend(pe_flags)

            pb_ratio, pb_flags = self.calculate_pb_ratio(effective_price, inputs.bvps)
            collected_flags.extend(pb_flags)

            peg_ratio, peg_flags = self.calculate_peg_ratio(pe_ratio, inputs.eps_growth_pct)
            collected_flags.extend(peg_flags)

            dividend_yield, div_flags = self.calculate_dividend_yield(
                effective_price, inputs.dividends_per_share
            )
            collected_flags.extend(div_flags)

        roe, roe_flags = self.calculate_roe(inputs.net_income, inputs.shareholders_equity)
        collected_flags.extend(roe_flags)

        deduped_flags: list[AccountingRiskFlag] = list(dict.fromkeys(collected_flags))
        warnings: list[str] = [
            f"{inputs.ticker}: {_RISK_FLAG_WARNING_MESSAGES[flag]}" for flag in deduped_flags
        ]

        return FinancialMetricsReport(
            ticker=inputs.ticker,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            peg_ratio=peg_ratio,
            dividend_yield=dividend_yield,
            roe=roe,
            risk_flags=deduped_flags,
            warnings=warnings,
        )

    def evaluate_portfolio_fundamentals(
        self, items: Sequence[FundamentalInputs]
    ) -> list[FinancialMetricsReport]:
        """Evaluate fundamental metrics for a sequence of portfolio instruments."""
        return [self.evaluate_company_metrics(item) for item in items]

    def summarize_portfolio_anomalies(
        self, reports: Sequence[FinancialMetricsReport]
    ) -> dict[str, list[AccountingRiskFlag]]:
        """
        Return a mapping `{ticker: list(risk_flags)}` restricted strictly to
        instruments where `has_accounting_anomalies` is True.
        """
        return {
            report.ticker: list(report.risk_flags)
            for report in reports
            if report.has_accounting_anomalies
        }
