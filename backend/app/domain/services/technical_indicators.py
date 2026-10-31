"""
Vectorized numerical technical indicators library (Module 7.1 - Phase 1).

Implements Simple Moving Average (SMA), Exponential Moving Average (EMA),
Wilder's Relative Strength Index (RSI), Bollinger Bands (%B and Bandwidth),
and Wilder's Average True Range (ATR) in pure arbitrary-precision `Decimal`
arithmetic with zero heavy external dependencies and deterministic 4-decimal
(`ROUND_HALF_UP`) quantization.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import math
from typing import Any, TypeVar

from pydantic import Field, field_validator, model_validator

from app.schemas.envelope import BaseSchema
from app.schemas.market_data import MarketBarDTO

T = TypeVar("T")

# ============================================================================
# Quantitative Constants & Defensive Security Boundaries
# ============================================================================
INDICATOR_QUANTIZE: Decimal = Decimal("0.0001")
INTERMEDIATE_DECIMAL_PRECISION: int = 50
MAX_BARS_SERIES_LENGTH: int = 50_000
MAX_VALID_BAR_PRICE: Decimal = Decimal("1000000000000")  # 10^12 ceiling


# ============================================================================
# Typed Domain Exception Hierarchy
# ============================================================================
class TechnicalIndicatorError(Exception):
    """Base domain exception for technical indicator calculations."""


class InsufficientMarketDataError(TechnicalIndicatorError):
    """Raised when a price or bar series has fewer observations than required by the window."""


class InvalidIndicatorParameterError(TechnicalIndicatorError):
    """Raised when a window period, standard deviation multiplier, or ddof parameter is invalid."""


class InvalidMarketBarSequenceError(TechnicalIndicatorError):
    """Raised when market bars violate OHLC invariants, contain non-finite prices, or duplicate timestamps."""


# ============================================================================
# Canonical Quantization & Coercion Helpers
# ============================================================================
def _quantize(value: Decimal) -> Decimal:
    """
    Quantize a `Decimal` to 4 decimal places (`0.0001`, `ROUND_HALF_UP`)
    under a 50-digit intermediate precision context, normalizing negative zero
    (`-0.0000`) to positive `Decimal("0.0000")`.
    """
    with localcontext() as ctx:
        ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
        quantized = value.quantize(INDICATOR_QUANTIZE, rounding=ROUND_HALF_UP)
    if quantized == Decimal("0"):
        return Decimal("0.0000")
    return quantized


def _coerce_finite_decimal_field(value: Any, field_name: str) -> Decimal:
    """Validate and convert a DTO field value to a finite `Decimal`, rejecting booleans."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Boolean or None is not permitted for '{field_name}'")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float is not permitted for '{field_name}'")
        dec = Decimal(str(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid Decimal string for '{field_name}'") from exc
    else:
        raise ValueError(
            f"Unsupported type '{type(value).__name__}' for '{field_name}'"
        )

    if not dec.is_finite():
        raise ValueError(f"Non-finite Decimal is not permitted for '{field_name}'")
    return dec


def _normalize_timestamp_for_sort(ts: datetime) -> datetime:
    """Normalize a timestamp to UTC for deterministic chronological comparison."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ============================================================================
# Immutable DTO Contracts
# ============================================================================
class BollingerBandsPoint(BaseSchema):
    """
    Immutable single-observation output for Bollinger Bands, including
    Upper Band, Middle Band (SMA), Lower Band, Bandwidth, and %B.
    """

    timestamp: datetime | None = None
    upper_band: Decimal
    middle_band: Decimal = Field(gt=Decimal("0"))
    lower_band: Decimal
    bandwidth: Decimal = Field(ge=Decimal("0"))
    percent_b: Decimal

    @field_validator(
        "upper_band",
        "middle_band",
        "lower_band",
        "bandwidth",
        "percent_b",
        mode="before",
    )
    @classmethod
    def _validate_decimal_fields(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_band_ordering(self) -> BollingerBandsPoint:
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            for name in (
                "upper_band",
                "middle_band",
                "lower_band",
                "bandwidth",
                "percent_b",
            ):
                val = getattr(self, name)
                if not isinstance(val, Decimal) or not val.is_finite():
                    raise ValueError(f"Field '{name}' must be a finite Decimal")

            if self.upper_band < self.middle_band or self.middle_band < self.lower_band:
                raise ValueError(
                    f"Bollinger Bands ordering invariant violated: "
                    f"upper_band ({self.upper_band}) >= middle_band ({self.middle_band}) "
                    f">= lower_band ({self.lower_band}) must hold."
                )
        return self


class TechnicalIndicatorsSnapshot(BaseSchema):
    """
    Immutable point-in-time snapshot of technical indicators for a financial asset,
    carrying both latest (`[-1]`) and immediately preceding (`[-2]`) values to
    support crossover and regime detection in `SignalGenerator` (Phase 2).
    """

    ticker: str | None = Field(default=None, min_length=1, max_length=20)
    as_of: datetime
    close: Decimal = Field(gt=Decimal("0"))
    previous_close: Decimal | None = Field(default=None, gt=Decimal("0"))
    sma_20: Decimal | None = None
    prev_sma_20: Decimal | None = None
    sma_50: Decimal | None = None
    prev_sma_50: Decimal | None = None
    ema_12: Decimal | None = None
    prev_ema_12: Decimal | None = None
    ema_26: Decimal | None = None
    prev_ema_26: Decimal | None = None
    rsi_14: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    prev_rsi_14: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    bollinger_20_2: BollingerBandsPoint | None = None
    prev_bollinger_20_2: BollingerBandsPoint | None = None
    atr_14: Decimal | None = Field(default=None, ge=Decimal("0"))
    prev_atr_14: Decimal | None = Field(default=None, ge=Decimal("0"))

    @field_validator("ticker", mode="before")
    @classmethod
    def _validate_and_normalize_ticker(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or isinstance(v, bool):
            raise ValueError("ticker must be a string or None")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
            raise ValueError("Control characters are not permitted in ticker")
        cleaned = v.strip().upper()
        if not cleaned or len(cleaned) > 20:
            raise ValueError("ticker must be between 1 and 20 characters")
        if not all(ch.isalnum() or ch in "._-" for ch in cleaned) or not cleaned[0].isalnum():
            raise ValueError(f"Invalid ticker format '{cleaned}'")
        return cleaned

    @field_validator("close", mode="before")
    @classmethod
    def _validate_close(cls, v: Any) -> Decimal:
        return _coerce_finite_decimal_field(v, "close")

    @field_validator(
        "previous_close",
        "sma_20",
        "prev_sma_20",
        "sma_50",
        "prev_sma_50",
        "ema_12",
        "prev_ema_12",
        "ema_26",
        "prev_ema_26",
        "rsi_14",
        "prev_rsi_14",
        "atr_14",
        "prev_atr_14",
        mode="before",
    )
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal_field(v, str(info.field_name))


# ============================================================================
# Vectorized Technical Indicators Domain Service
# ============================================================================
class TechnicalIndicatorsService:
    """
    Pure, stateless quantitative domain service computing moving averages,
    Wilder's RSI, Bollinger Bands, and Wilder's ATR over `MarketBarDTO` or
    scalar price sequences.
    """

    @staticmethod
    def _quantize(value: Decimal) -> Decimal:
        """Quantize a `Decimal` to 4 decimal places (`0.0001`, `ROUND_HALF_UP`)."""
        return _quantize(value)

    @staticmethod
    def _validate_period(period: int, min_period: int = 1) -> int:
        """Validate window period parameter against boolean traps and DoS bounds."""
        if (
            isinstance(period, bool)
            or not isinstance(period, int)
            or period < min_period
            or period > MAX_BARS_SERIES_LENGTH
        ):
            raise InvalidIndicatorParameterError(
                f"Invalid indicator period '{period}': must be an integer in "
                f"[{min_period}, {MAX_BARS_SERIES_LENGTH}]."
            )
        return period

    @staticmethod
    def _to_positive_decimal(value: Any, field_name: str = "price") -> Decimal:
        """
        Convert a numeric or string price into a finite positive `Decimal`
        bounded by `MAX_VALID_BAR_PRICE`.
        """
        if isinstance(value, bool) or value is None:
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: boolean or None values are not permitted."
            )
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, int):
            dec = Decimal(value)
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidMarketBarSequenceError(
                    f"Invalid {field_name}: non-finite float '{value}'."
                )
            dec = Decimal(str(value))
        elif isinstance(value, str):
            cleaned = value.strip()
            if not cleaned or len(cleaned) > 64:
                raise InvalidMarketBarSequenceError(
                    f"Invalid {field_name}: empty or oversized numeric string."
                )
            try:
                dec = Decimal(cleaned)
            except InvalidOperation as exc:
                raise InvalidMarketBarSequenceError(
                    f"Invalid {field_name}: cannot parse '{value}' as Decimal."
                ) from exc
        else:
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: unsupported type '{type(value).__name__}'."
            )

        if not dec.is_finite():
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: non-finite Decimal '{dec}'."
            )
        if dec <= Decimal("0"):
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: must be strictly positive (got {dec})."
            )
        if dec > MAX_VALID_BAR_PRICE:
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: {dec} exceeds maximum valid bar price "
                f"({MAX_VALID_BAR_PRICE})."
            )
        return dec

    @staticmethod
    def _to_non_negative_decimal(value: Any, field_name: str = "volume") -> Decimal:
        """Convert volume to a finite non-negative `Decimal`."""
        if isinstance(value, bool) or value is None:
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: boolean or None values are not permitted."
            )
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, int):
            dec = Decimal(value)
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidMarketBarSequenceError(
                    f"Invalid {field_name}: non-finite float '{value}'."
                )
            dec = Decimal(str(value))
        elif isinstance(value, str):
            try:
                dec = Decimal(value.strip())
            except InvalidOperation as exc:
                raise InvalidMarketBarSequenceError(
                    f"Invalid {field_name}: cannot parse '{value}' as Decimal."
                ) from exc
        else:
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: unsupported type '{type(value).__name__}'."
            )

        if not dec.is_finite() or dec < Decimal("0"):
            raise InvalidMarketBarSequenceError(
                f"Invalid {field_name}: must be finite and >= 0 (got {dec})."
            )
        return dec

    def validate_and_sort_bars(
        self, bars: Sequence[MarketBarDTO]
    ) -> list[MarketBarDTO]:
        """
        Validate OHLCV invariants on every bar (including instances built via
        `model_construct`), sort chronologically ascending by timestamp, and
        reject duplicate timestamps.
        """
        if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
            raise InvalidMarketBarSequenceError(
                "bars must be a sequence of MarketBarDTO instances."
            )
        if len(bars) == 0:
            raise InsufficientMarketDataError("Market bar sequence cannot be empty.")
        if len(bars) > MAX_BARS_SERIES_LENGTH:
            raise InvalidIndicatorParameterError(
                f"Market bar sequence length ({len(bars)}) exceeds maximum limit "
                f"({MAX_BARS_SERIES_LENGTH})."
            )

        decorated: list[tuple[datetime, int, MarketBarDTO]] = []
        for idx, bar in enumerate(bars):
            if not isinstance(bar, MarketBarDTO):
                raise InvalidMarketBarSequenceError(
                    f"Element at index {idx} is not a MarketBarDTO instance "
                    f"(got {type(bar).__name__})."
                )
            ts = getattr(bar, "timestamp", None)
            if not isinstance(ts, datetime) or isinstance(ts, bool):
                raise InvalidMarketBarSequenceError(
                    f"Bar at index {idx} has an invalid timestamp."
                )

            open_p = self._to_positive_decimal(getattr(bar, "open", None), "open")
            high_p = self._to_positive_decimal(getattr(bar, "high", None), "high")
            low_p = self._to_positive_decimal(getattr(bar, "low", None), "low")
            close_p = self._to_positive_decimal(getattr(bar, "close", None), "close")

            if high_p < max(open_p, close_p, low_p):
                raise InvalidMarketBarSequenceError(
                    f"Bar at index {idx} violates OHLC invariant: "
                    f"high ({high_p}) < max(open={open_p}, close={close_p}, low={low_p})."
                )
            if low_p > min(open_p, close_p, high_p):
                raise InvalidMarketBarSequenceError(
                    f"Bar at index {idx} violates OHLC invariant: "
                    f"low ({low_p}) > min(open={open_p}, close={close_p}, high={high_p})."
                )

            vol = getattr(bar, "volume", Decimal("0"))
            if vol is not None:
                self._to_non_negative_decimal(vol, "volume")

            decorated.append((_normalize_timestamp_for_sort(ts), idx, bar))

        decorated.sort(key=lambda item: (item[0], item[1]))

        for i in range(1, len(decorated)):
            if decorated[i][0] == decorated[i - 1][0]:
                raise InvalidMarketBarSequenceError(
                    f"Duplicate bar timestamp detected: {decorated[i][2].timestamp.isoformat()}"
                )

        return [item[2] for item in decorated]

    def _extract_closes_and_timestamps(
        self,
        series: Sequence[MarketBarDTO | Decimal | int | float | str],
    ) -> tuple[list[Decimal], list[datetime | None]]:
        """
        Extract validated positive `Decimal` close prices and optional timestamps
        from either a `MarketBarDTO` sequence or a scalar numeric sequence.
        """
        if isinstance(series, (str, bytes)) or not isinstance(series, Sequence):
            raise InvalidMarketBarSequenceError(
                "Input series must be a sequence of MarketBarDTO or numeric values."
            )
        if len(series) == 0:
            raise InsufficientMarketDataError("Input price series cannot be empty.")
        if len(series) > MAX_BARS_SERIES_LENGTH:
            raise InvalidIndicatorParameterError(
                f"Series length ({len(series)}) exceeds maximum limit "
                f"({MAX_BARS_SERIES_LENGTH})."
            )

        first = series[0]
        if isinstance(first, MarketBarDTO):
            sorted_bars = self.validate_and_sort_bars(series)  # type: ignore[arg-type]
            closes = [
                self._to_positive_decimal(b.close, "close") for b in sorted_bars
            ]
            timestamps: list[datetime | None] = [b.timestamp for b in sorted_bars]
            return closes, timestamps

        closes = []
        for idx, item in enumerate(series):
            if isinstance(item, MarketBarDTO):
                raise InvalidMarketBarSequenceError(
                    f"Mixed MarketBarDTO and scalar elements at index {idx}."
                )
            closes.append(self._to_positive_decimal(item, f"series[{idx}]"))

        return closes, [None] * len(closes)

    def calculate_sma(
        self,
        series: Sequence[MarketBarDTO | Decimal | int | float | str],
        period: int = 20,
    ) -> list[Decimal]:
        """
        Compute the Simple Moving Average (SMA) in $O(N)$ using a sliding window sum:

        $$\\text{SMA}_t(n) = \\frac{1}{n} \\sum_{i=0}^{n-1} P_{t-i}$$
        """
        self._validate_period(period, min_period=1)
        closes, _ = self._extract_closes_and_timestamps(series)

        if len(closes) < period:
            raise InsufficientMarketDataError(
                f"SMA({period}) requires at least {period} observations, "
                f"got {len(closes)}."
            )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            period_dec = Decimal(period)
            window_sum = sum(closes[:period], Decimal("0"))
            sma_values: list[Decimal] = [self._quantize(window_sum / period_dec)]

            for idx in range(period, len(closes)):
                window_sum += closes[idx] - closes[idx - period]
                sma_values.append(self._quantize(window_sum / period_dec))

        return sma_values

    def calculate_ema(
        self,
        series: Sequence[MarketBarDTO | Decimal | int | float | str],
        period: int = 20,
    ) -> list[Decimal]:
        """
        Compute the Exponential Moving Average (EMA) seeded with the initial
        Simple Moving Average of the first `period` observations:

        $$\\alpha = \\frac{2}{n + 1}, \\quad \\text{EMA}_t = (P_t - \\text{EMA}_{t-1}) \\cdot \\alpha + \\text{EMA}_{t-1}$$
        """
        self._validate_period(period, min_period=1)
        closes, _ = self._extract_closes_and_timestamps(series)

        if len(closes) < period:
            raise InsufficientMarketDataError(
                f"EMA({period}) requires at least {period} observations, "
                f"got {len(closes)}."
            )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            period_dec = Decimal(period)
            alpha = Decimal("2") / Decimal(period + 1)

            ema = sum(closes[:period], Decimal("0")) / period_dec
            ema_values: list[Decimal] = [self._quantize(ema)]

            for price in closes[period:]:
                ema = (price - ema) * alpha + ema
                ema_values.append(self._quantize(ema))

        return ema_values

    def calculate_wilder_rsi(
        self,
        series: Sequence[MarketBarDTO | Decimal | int | float | str],
        period: int = 14,
    ) -> list[Decimal]:
        """
        Compute J. Welles Wilder Jr.'s Relative Strength Index (RSI) with
        recursive Wilder smoothing ($\\alpha_W = 1 / n$):

        - Requires at least `period + 1` close prices ($n$ price differences).
        - Handles zero-loss ($\\text{RSI} = 100.0000$), zero-gain ($\\text{RSI} = 0.0000$),
          and completely flat ($\\text{AvgGain} = \\text{AvgLoss} = 0 \\implies \\text{RSI} = 50.0000$)
          regimes without `ZeroDivisionError`.
        """
        self._validate_period(period, min_period=1)
        closes, _ = self._extract_closes_and_timestamps(series)

        min_required = period + 1
        if len(closes) < min_required:
            raise InsufficientMarketDataError(
                f"Wilder RSI({period}) requires at least {min_required} observations "
                f"({period} price changes), got {len(closes)}."
            )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            deltas: list[Decimal] = [
                closes[i] - closes[i - 1] for i in range(1, len(closes))
            ]
            period_dec = Decimal(period)
            prev_weight = Decimal(period - 1)

            avg_gain = (
                sum((max(d, Decimal("0")) for d in deltas[:period]), Decimal("0"))
                / period_dec
            )
            avg_loss = (
                sum((max(-d, Decimal("0")) for d in deltas[:period]), Decimal("0"))
                / period_dec
            )

            rsi_values: list[Decimal] = [
                self._compute_rsi_from_averages(avg_gain, avg_loss)
            ]

            for delta in deltas[period:]:
                gain = max(delta, Decimal("0"))
                loss = max(-delta, Decimal("0"))
                avg_gain = (avg_gain * prev_weight + gain) / period_dec
                avg_loss = (avg_loss * prev_weight + loss) / period_dec
                rsi_values.append(self._compute_rsi_from_averages(avg_gain, avg_loss))

        return rsi_values

    @classmethod
    def _compute_rsi_from_averages(
        cls, avg_gain: Decimal, avg_loss: Decimal
    ) -> Decimal:
        """Evaluate Wilder RSI from smoothed average gain and average loss."""
        if avg_loss == Decimal("0") and avg_gain == Decimal("0"):
            return Decimal("50.0000")
        if avg_loss == Decimal("0"):
            return Decimal("100.0000")
        if avg_gain == Decimal("0"):
            return Decimal("0.0000")

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            rs = avg_gain / avg_loss
            raw_rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
            quantized = cls._quantize(raw_rsi)
        if quantized < Decimal("0.0000"):
            return Decimal("0.0000")
        if quantized > Decimal("100.0000"):
            return Decimal("100.0000")
        return quantized

    def calculate_bollinger_bands(
        self,
        series: Sequence[MarketBarDTO | Decimal | int | float | str],
        period: int = 20,
        num_std_dev: Decimal | int | float = Decimal("2"),
        ddof: int = 0,
    ) -> list[BollingerBandsPoint]:
        """
        Compute Bollinger Bands (Upper, Middle, Lower, Bandwidth, and %B)
        using exact `Decimal.sqrt()` standard deviation over each sliding window.
        """
        self._validate_period(period, min_period=1)

        if isinstance(ddof, bool) or not isinstance(ddof, int) or ddof not in (0, 1):
            raise InvalidIndicatorParameterError(
                f"Invalid ddof '{ddof}': must be 0 (population) or 1 (sample)."
            )
        if period - ddof < 1:
            raise InvalidIndicatorParameterError(
                f"Bollinger Bands with ddof={ddof} requires period >= {ddof + 1}, "
                f"got period={period}."
            )

        if isinstance(num_std_dev, bool) or num_std_dev is None:
            raise InvalidIndicatorParameterError(
                "num_std_dev cannot be a boolean or None."
            )
        if isinstance(num_std_dev, Decimal):
            k_mult = num_std_dev
        elif isinstance(num_std_dev, int):
            k_mult = Decimal(num_std_dev)
        elif isinstance(num_std_dev, float):
            if not math.isfinite(num_std_dev):
                raise InvalidIndicatorParameterError(
                    "num_std_dev must be a finite number."
                )
            k_mult = Decimal(str(num_std_dev))
        else:
            raise InvalidIndicatorParameterError(
                f"Unsupported type '{type(num_std_dev).__name__}' for num_std_dev."
            )

        if not k_mult.is_finite() or k_mult <= Decimal("0") or k_mult > Decimal("100"):
            raise InvalidIndicatorParameterError(
                f"num_std_dev must be in (0, 100], got {k_mult}."
            )

        closes, timestamps = self._extract_closes_and_timestamps(series)
        if len(closes) < period:
            raise InsufficientMarketDataError(
                f"Bollinger Bands({period}) requires at least {period} observations, "
                f"got {len(closes)}."
            )

        period_dec = Decimal(period)
        denom_dec = Decimal(period - ddof)
        points: list[BollingerBandsPoint] = []

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            for start_idx in range(len(closes) - period + 1):
                end_idx = start_idx + period - 1
                window = closes[start_idx : start_idx + period]
                mean = sum(window, Decimal("0")) / period_dec
                variance = (
                    sum(((x - mean) ** 2 for x in window), Decimal("0")) / denom_dec
                )
                std_dev = variance.sqrt()

                middle_band = self._quantize(mean)
                upper_band = self._quantize(mean + k_mult * std_dev)
                lower_band = self._quantize(mean - k_mult * std_dev)

                # Guard sub-pip rounding ties
                if upper_band < middle_band:
                    upper_band = middle_band
                if lower_band > middle_band:
                    lower_band = middle_band

                band_span = upper_band - lower_band
                if band_span == Decimal("0"):
                    bandwidth = Decimal("0.0000")
                    percent_b = Decimal("0.5000")
                else:
                    bandwidth = self._quantize(band_span / middle_band)
                    percent_b = self._quantize((window[-1] - lower_band) / band_span)

                points.append(
                    BollingerBandsPoint(
                        timestamp=timestamps[end_idx],
                        upper_band=upper_band,
                        middle_band=middle_band,
                        lower_band=lower_band,
                        bandwidth=bandwidth,
                        percent_b=percent_b,
                    )
                )

        return points

    def calculate_atr(
        self,
        bars: Sequence[MarketBarDTO],
        period: int = 14,
    ) -> list[Decimal]:
        """
        Compute J. Welles Wilder Jr.'s Average True Range (ATR) capturing both
        intraday ranges and overnight gaps:

        - $\\text{TR}_0 = H_0 - L_0$
        - $\\text{TR}_t = \\max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)$ for $t \\ge 1$
        - Seeded with the simple average of the first `period` True Ranges, followed
          by Wilder recursive smoothing: $\\text{ATR}_t = \\frac{\\text{ATR}_{t-1} \\cdot (n - 1) + \\text{TR}_t}{n}$
        """
        self._validate_period(period, min_period=1)
        sorted_bars = self.validate_and_sort_bars(bars)

        if len(sorted_bars) < period:
            raise InsufficientMarketDataError(
                f"ATR({period}) requires at least {period} bars, "
                f"got {len(sorted_bars)}."
            )

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            true_ranges: list[Decimal] = []
            first_high = self._to_positive_decimal(sorted_bars[0].high, "high")
            first_low = self._to_positive_decimal(sorted_bars[0].low, "low")
            prev_close = self._to_positive_decimal(sorted_bars[0].close, "close")
            true_ranges.append(first_high - first_low)

            for bar in sorted_bars[1:]:
                high_p = self._to_positive_decimal(bar.high, "high")
                low_p = self._to_positive_decimal(bar.low, "low")
                close_p = self._to_positive_decimal(bar.close, "close")

                tr = max(
                    high_p - low_p,
                    abs(high_p - prev_close),
                    abs(low_p - prev_close),
                )
                true_ranges.append(tr)
                prev_close = close_p

            period_dec = Decimal(period)
            prev_weight = Decimal(period - 1)

            atr = sum(true_ranges[:period], Decimal("0")) / period_dec
            atr_values: list[Decimal] = [self._quantize(atr)]

            for tr_val in true_ranges[period:]:
                atr = (atr * prev_weight + tr_val) / period_dec
                atr_values.append(self._quantize(atr))

        return atr_values

    @staticmethod
    def _latest_and_prev(values: Sequence[T]) -> tuple[T | None, T | None]:
        """Extract `(-1, -2)` elements from a non-empty indicator series."""
        if not values:
            return None, None
        latest = values[-1]
        prev = values[-2] if len(values) >= 2 else None
        return latest, prev

    def compute_snapshot(
        self,
        bars: Sequence[MarketBarDTO],
        ticker: str | None = None,
    ) -> TechnicalIndicatorsSnapshot:
        """
        Compute a consolidated `TechnicalIndicatorsSnapshot` over `bars` in a
        single pass, populating current (`[-1]`) and previous (`[-2]`) values
        for every indicator whose minimum window requirement is met.
        """
        sorted_bars = self.validate_and_sort_bars(bars)
        n_bars = len(sorted_bars)

        latest_bar = sorted_bars[-1]
        latest_close = self._quantize(
            self._to_positive_decimal(latest_bar.close, "close")
        )
        prev_close = (
            self._quantize(
                self._to_positive_decimal(sorted_bars[-2].close, "close")
            )
            if n_bars >= 2
            else None
        )

        sma_20, prev_sma_20 = (
            self._latest_and_prev(self.calculate_sma(sorted_bars, period=20))
            if n_bars >= 20
            else (None, None)
        )
        sma_50, prev_sma_50 = (
            self._latest_and_prev(self.calculate_sma(sorted_bars, period=50))
            if n_bars >= 50
            else (None, None)
        )
        ema_12, prev_ema_12 = (
            self._latest_and_prev(self.calculate_ema(sorted_bars, period=12))
            if n_bars >= 12
            else (None, None)
        )
        ema_26, prev_ema_26 = (
            self._latest_and_prev(self.calculate_ema(sorted_bars, period=26))
            if n_bars >= 26
            else (None, None)
        )
        rsi_14, prev_rsi_14 = (
            self._latest_and_prev(self.calculate_wilder_rsi(sorted_bars, period=14))
            if n_bars >= 15
            else (None, None)
        )
        bollinger_20_2, prev_bollinger_20_2 = (
            self._latest_and_prev(
                self.calculate_bollinger_bands(
                    sorted_bars, period=20, num_std_dev=Decimal("2"), ddof=0
                )
            )
            if n_bars >= 20
            else (None, None)
        )
        atr_14, prev_atr_14 = (
            self._latest_and_prev(self.calculate_atr(sorted_bars, period=14))
            if n_bars >= 14
            else (None, None)
        )

        return TechnicalIndicatorsSnapshot(
            ticker=ticker,
            as_of=latest_bar.timestamp,
            close=latest_close,
            previous_close=prev_close,
            sma_20=sma_20,
            prev_sma_20=prev_sma_20,
            sma_50=sma_50,
            prev_sma_50=prev_sma_50,
            ema_12=ema_12,
            prev_ema_12=prev_ema_12,
            ema_26=ema_26,
            prev_ema_26=prev_ema_26,
            rsi_14=rsi_14,
            prev_rsi_14=prev_rsi_14,
            bollinger_20_2=bollinger_20_2,
            prev_bollinger_20_2=prev_bollinger_20_2,
            atr_14=atr_14,
            prev_atr_14=prev_atr_14,
        )

