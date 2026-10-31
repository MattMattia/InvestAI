"""
Quantitative trading signal generation engine (Module 7.1 - Phase 2).

Evaluates convergence and divergence across multi-factor technical indicators
(`EMA_CROSSOVER`, `SMA_TREND`, `RSI_REGIME`, `VOLATILITY_BOLLINGER`), sizes
volatility-adjusted stop-loss and take-profit levels via Wilder's ATR, and
emits structured `OrderFSMIntent` contracts for the transactional order FSM.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal, localcontext
from enum import Enum
import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.domain.services.technical_indicators import (
    INDICATOR_QUANTIZE,
    INTERMEDIATE_DECIMAL_PRECISION,
    TechnicalIndicatorError,
    TechnicalIndicatorsService,
    TechnicalIndicatorsSnapshot,
    _coerce_finite_decimal_field,
    _quantize,
)
from app.schemas.envelope import BaseSchema
from app.schemas.market_data import MarketBarDTO

# ============================================================================
# Canonical Rule Weights
# ============================================================================
WEIGHT_EMA_CROSSOVER: Decimal = Decimal("0.3000")
WEIGHT_SMA_TREND: Decimal = Decimal("0.2500")
WEIGHT_RSI_REGIME: Decimal = Decimal("0.2500")
WEIGHT_VOLATILITY_BOLLINGER: Decimal = Decimal("0.2000")


# ============================================================================
# Typed Domain Exception Hierarchy
# ============================================================================
class SignalGenerationError(TechnicalIndicatorError):
    """Base domain exception for trading signal generation failures."""


class InvalidSignalParametersError(SignalGenerationError):
    """Raised when signal generator configuration, ticker, or order sizing inputs are invalid."""


# ============================================================================
# Canonical Enums
# ============================================================================
class SignalAction(str, Enum):
    """Actionable directional recommendation emitted by the signal engine."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalRuleType(str, Enum):
    """Quantitative rule families evaluated in the multi-factor signal model."""

    EMA_CROSSOVER = "EMA_CROSSOVER"
    SMA_TREND = "SMA_TREND"
    RSI_REGIME = "RSI_REGIME"
    VOLATILITY_BOLLINGER = "VOLATILITY_BOLLINGER"


def _validate_clean_ticker_field(v: Any) -> str:
    """Validate and normalize a required ticker string on DTO contracts."""
    if not isinstance(v, str) or isinstance(v, bool):
        raise ValueError("ticker must be a string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
        raise ValueError("Control characters are not permitted in ticker")
    cleaned = v.strip().upper()
    if not cleaned or len(cleaned) > 20:
        raise ValueError("ticker must be between 1 and 20 characters")
    if not all(ch.isalnum() or ch in "._-" for ch in cleaned) or not cleaned[0].isalnum():
        raise ValueError(f"Invalid ticker format '{cleaned}'")
    return cleaned


# ============================================================================
# Immutable DTO Contracts
# ============================================================================
class SignalGeneratorConfig(BaseSchema):
    """
    Immutable parameterization for multi-factor signal thresholds, Bollinger
    breakout expansion, ATR risk-reward multipliers, and minimum conviction.
    """

    rsi_oversold: Decimal = Field(
        default=Decimal("30.0000"), gt=Decimal("0"), lt=Decimal("100")
    )
    rsi_overbought: Decimal = Field(
        default=Decimal("70.0000"), gt=Decimal("0"), lt=Decimal("100")
    )
    bollinger_lower_percent_b: Decimal = Field(default=Decimal("0.0500"))
    bollinger_upper_percent_b: Decimal = Field(default=Decimal("0.9500"))
    bollinger_breakout_expansion_ratio: Decimal = Field(
        default=Decimal("1.1500"), gt=Decimal("1.0000"), le=Decimal("10.0000")
    )
    atr_stop_loss_multiplier: Decimal = Field(
        default=Decimal("2.0000"), gt=Decimal("0"), le=Decimal("100.0000")
    )
    atr_take_profit_multiplier: Decimal = Field(
        default=Decimal("3.0000"), gt=Decimal("0"), le=Decimal("100.0000")
    )
    min_conviction_threshold: Decimal = Field(
        default=Decimal("0.2500"), gt=Decimal("0"), le=Decimal("1.0000")
    )

    @field_validator(
        "rsi_oversold",
        "rsi_overbought",
        "bollinger_lower_percent_b",
        "bollinger_upper_percent_b",
        "bollinger_breakout_expansion_ratio",
        "atr_stop_loss_multiplier",
        "atr_take_profit_multiplier",
        "min_conviction_threshold",
        mode="before",
    )
    @classmethod
    def _validate_decimal_params(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_threshold_ordering(self) -> SignalGeneratorConfig:
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            if self.rsi_oversold >= self.rsi_overbought:
                raise ValueError(
                    f"rsi_oversold ({self.rsi_oversold}) must be strictly less than "
                    f"rsi_overbought ({self.rsi_overbought})."
                )
            if self.bollinger_lower_percent_b >= self.bollinger_upper_percent_b:
                raise ValueError(
                    f"bollinger_lower_percent_b ({self.bollinger_lower_percent_b}) must be "
                    f"strictly less than bollinger_upper_percent_b ({self.bollinger_upper_percent_b})."
                )
        return self


class SignalComponentEvaluation(BaseSchema):
    """
    Immutable evaluation record for an individual quantitative signal rule.
    """

    rule: SignalRuleType
    action: SignalAction
    score: Decimal = Field(ge=Decimal("-1.0000"), le=Decimal("1.0000"))
    weight: Decimal = Field(gt=Decimal("0"), le=Decimal("1.0000"))
    rationale: str = Field(min_length=1)

    @field_validator("score", "weight", mode="before")
    @classmethod
    def _validate_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_action_score_coherence(self) -> SignalComponentEvaluation:
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            if self.action == SignalAction.BUY and self.score <= Decimal("0"):
                raise ValueError(
                    f"BUY component requires score > 0 (got {self.score})."
                )
            if self.action == SignalAction.SELL and self.score >= Decimal("0"):
                raise ValueError(
                    f"SELL component requires score < 0 (got {self.score})."
                )
            if self.action == SignalAction.HOLD and self.score != Decimal("0"):
                raise ValueError(
                    f"HOLD component requires score == 0 (got {self.score})."
                )
        return self


class OrderFSMIntent(BaseSchema):
    """
    Immutable trade intent emitted when composite conviction meets or exceeds
    `min_conviction_threshold`, bridging `SignalGeneratorService` directly to
    the transactional order FSM (`PENDING`).
    """

    ticker: str = Field(min_length=1, max_length=20)
    side: Literal["BUY", "SELL"]
    target_status: str = Field(default="PENDING")
    reference_price: Decimal = Field(gt=Decimal("0"))
    suggested_stop_loss: Decimal | None = Field(default=None, gt=Decimal("0"))
    suggested_take_profit: Decimal | None = Field(default=None, gt=Decimal("0"))
    signal_conviction: Decimal = Field(ge=Decimal("0.0000"), le=Decimal("1.0000"))

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker_field(v)

    @field_validator("reference_price", "signal_conviction", mode="before")
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @field_validator("suggested_stop_loss", "suggested_take_profit", mode="before")
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_fsm_and_bracket_invariants(self) -> OrderFSMIntent:
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            if self.target_status != "PENDING":
                raise ValueError(
                    f"OrderFSMIntent target_status must be 'PENDING' (got '{self.target_status}')."
                )

            if self.side == "BUY":
                if (
                    self.suggested_stop_loss is not None
                    and self.suggested_stop_loss >= self.reference_price
                ):
                    raise ValueError(
                        f"BUY stop-loss ({self.suggested_stop_loss}) must be strictly "
                        f"below reference_price ({self.reference_price})."
                    )
                if (
                    self.suggested_take_profit is not None
                    and self.suggested_take_profit <= self.reference_price
                ):
                    raise ValueError(
                        f"BUY take-profit ({self.suggested_take_profit}) must be strictly "
                        f"above reference_price ({self.reference_price})."
                    )
            elif self.side == "SELL":
                if (
                    self.suggested_stop_loss is not None
                    and self.suggested_stop_loss <= self.reference_price
                ):
                    raise ValueError(
                        f"SELL stop-loss ({self.suggested_stop_loss}) must be strictly "
                        f"above reference_price ({self.reference_price})."
                    )
                if (
                    self.suggested_take_profit is not None
                    and self.suggested_take_profit >= self.reference_price
                ):
                    raise ValueError(
                        f"SELL take-profit ({self.suggested_take_profit}) must be strictly "
                        f"below reference_price ({self.reference_price})."
                    )

        return self

    def to_order_payload(
        self,
        quantity: Decimal | int | float,
        portfolio_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert this `OrderFSMIntent` into a validated dictionary payload ready
        for transactional order persistence in `PENDING` state.
        """
        if isinstance(quantity, bool) or quantity is None:
            raise InvalidSignalParametersError(
                "Order quantity cannot be a boolean or None."
            )
        if isinstance(quantity, Decimal):
            raw_qty = quantity
        elif isinstance(quantity, int):
            raw_qty = Decimal(quantity)
        elif isinstance(quantity, float):
            if not math.isfinite(quantity):
                raise InvalidSignalParametersError(
                    "Order quantity must be a finite number."
                )
            raw_qty = Decimal(str(quantity))
        else:
            raise InvalidSignalParametersError(
                f"Unsupported quantity type '{type(quantity).__name__}'."
            )

        if not raw_qty.is_finite() or raw_qty <= Decimal("0"):
            raise InvalidSignalParametersError(
                f"Order quantity must be strictly positive (got {raw_qty})."
            )

        quantized_qty = _quantize(raw_qty)
        if quantized_qty <= Decimal("0.0000"):
            raise InvalidSignalParametersError(
                f"Order quantity {raw_qty} collapses to zero after 4-decimal quantization."
            )

        payload: dict[str, Any] = {
            "ticker": self.ticker,
            "side": self.side,
            "quantity": quantized_qty,
            "price": self.reference_price,
            "status": self.target_status,
        }

        if portfolio_id is not None:
            if not isinstance(portfolio_id, str) or any(
                ord(ch) < 32 for ch in portfolio_id
            ):
                raise InvalidSignalParametersError(
                    "portfolio_id must be a valid string without control characters."
                )
            clean_pid = portfolio_id.strip()
            if not clean_pid:
                raise InvalidSignalParametersError("portfolio_id cannot be empty.")
            payload["portfolio_id"] = clean_pid

        return payload


class TradingSignalReport(BaseSchema):
    """
    Immutable consolidated report returned by `SignalGeneratorService`,
    coupling the directional action, composite score, conviction, ATR risk
    brackets, rule evaluations, `OrderFSMIntent`, and underlying indicator snapshot.
    """

    ticker: str = Field(min_length=1, max_length=20)
    as_of: datetime
    action: SignalAction
    conviction: Decimal = Field(ge=Decimal("0.0000"), le=Decimal("1.0000"))
    composite_score: Decimal = Field(ge=Decimal("-1.0000"), le=Decimal("1.0000"))
    reference_price: Decimal = Field(gt=Decimal("0"))
    stop_loss_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    take_profit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    components: list[SignalComponentEvaluation] = Field(default_factory=list)
    order_intent: OrderFSMIntent | None = None
    indicators: TechnicalIndicatorsSnapshot

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: Any) -> str:
        return _validate_clean_ticker_field(v)

    @field_validator(
        "conviction",
        "composite_score",
        "reference_price",
        mode="before",
    )
    @classmethod
    def _validate_required_decimals(cls, v: Any, info: Any) -> Decimal:
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @field_validator("stop_loss_price", "take_profit_price", mode="before")
    @classmethod
    def _validate_optional_decimals(cls, v: Any, info: Any) -> Decimal | None:
        if v is None:
            return None
        return _coerce_finite_decimal_field(v, str(info.field_name))

    @model_validator(mode="after")
    def _enforce_report_invariants(self) -> TradingSignalReport:
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            expected_conviction = abs(self.composite_score)
            if self.conviction != expected_conviction:
                raise ValueError(
                    f"conviction ({self.conviction}) must equal abs(composite_score) "
                    f"({expected_conviction})."
                )
            if self.reference_price != self.indicators.close:
                raise ValueError(
                    f"reference_price ({self.reference_price}) must equal "
                    f"indicators.close ({self.indicators.close})."
                )
            if self.as_of != self.indicators.as_of:
                raise ValueError(
                    "TradingSignalReport.as_of must match indicators.as_of."
                )

            if self.action == SignalAction.HOLD:
                if (
                    self.order_intent is not None
                    or self.stop_loss_price is not None
                    or self.take_profit_price is not None
                ):
                    raise ValueError(
                        "HOLD signal must not carry order_intent, stop_loss_price, or take_profit_price."
                    )
            elif self.action == SignalAction.BUY:
                if self.composite_score <= Decimal("0"):
                    raise ValueError(
                        f"BUY signal requires composite_score > 0 (got {self.composite_score})."
                    )
                if self.order_intent is None or self.order_intent.side != "BUY":
                    raise ValueError(
                        "BUY signal requires an OrderFSMIntent with side='BUY'."
                    )
            elif self.action == SignalAction.SELL:
                if self.composite_score >= Decimal("0"):
                    raise ValueError(
                        f"SELL signal requires composite_score < 0 (got {self.composite_score})."
                    )
                if self.order_intent is None or self.order_intent.side != "SELL":
                    raise ValueError(
                        "SELL signal requires an OrderFSMIntent with side='SELL'."
                    )

            if self.order_intent is not None:
                if self.order_intent.ticker != self.ticker:
                    raise ValueError("order_intent.ticker must match report ticker.")
                if self.order_intent.reference_price != self.reference_price:
                    raise ValueError(
                        "order_intent.reference_price must match report reference_price."
                    )
                if self.order_intent.suggested_stop_loss != self.stop_loss_price:
                    raise ValueError(
                        "order_intent.suggested_stop_loss must match report stop_loss_price."
                    )
                if self.order_intent.suggested_take_profit != self.take_profit_price:
                    raise ValueError(
                        "order_intent.suggested_take_profit must match report take_profit_price."
                    )
                if self.order_intent.signal_conviction != self.conviction:
                    raise ValueError(
                        "order_intent.signal_conviction must match report conviction."
                    )

        return self


# ============================================================================
# Multi-Factor Signal Generator Domain Service
# ============================================================================
class SignalGeneratorService:
    """
    Pure, deterministic quantitative domain service that evaluates convergence
    across moving averages, Wilder's RSI, Bollinger Bands, and Wilder's ATR to
    produce auditable trading signals and `OrderFSMIntent` contracts.
    """

    def __init__(
        self,
        config: SignalGeneratorConfig | None = None,
        indicators_service: TechnicalIndicatorsService | None = None,
    ) -> None:
        if config is not None and not isinstance(config, SignalGeneratorConfig):
            raise InvalidSignalParametersError(
                "config must be an instance of SignalGeneratorConfig."
            )
        if indicators_service is not None and not isinstance(
            indicators_service, TechnicalIndicatorsService
        ):
            raise InvalidSignalParametersError(
                "indicators_service must be an instance of TechnicalIndicatorsService."
            )
        self._config: SignalGeneratorConfig = config or SignalGeneratorConfig()
        self._indicators_service: TechnicalIndicatorsService = (
            indicators_service or TechnicalIndicatorsService()
        )

    @property
    def config(self) -> SignalGeneratorConfig:
        """Return the immutable `SignalGeneratorConfig` governing this service."""
        return self._config

    @staticmethod
    def _validate_ticker(ticker: str | None) -> str:
        """Validate and normalize a ticker symbol or raise `InvalidSignalParametersError`."""
        if not isinstance(ticker, str) or isinstance(ticker, bool):
            raise InvalidSignalParametersError(
                "A valid non-empty ticker string is required to generate a signal."
            )
        if any(ord(ch) < 32 for ch in ticker):
            raise InvalidSignalParametersError(
                "Control characters are not permitted in ticker."
            )
        cleaned = ticker.strip().upper()
        if not cleaned or len(cleaned) > 20:
            raise InvalidSignalParametersError(
                "Ticker must be between 1 and 20 characters after trimming."
            )
        return cleaned

    def evaluate_from_snapshot(
        self,
        snapshot: TechnicalIndicatorsSnapshot,
        ticker: str | None = None,
    ) -> TradingSignalReport:
        """
        Evaluate all available indicator rule families on a `TechnicalIndicatorsSnapshot`
        and return an immutable `TradingSignalReport`.
        """
        if not isinstance(snapshot, TechnicalIndicatorsSnapshot):
            raise InvalidSignalParametersError(
                "snapshot must be a TechnicalIndicatorsSnapshot instance."
            )

        effective_ticker = self._validate_ticker(
            ticker if ticker is not None else snapshot.ticker
        )

        components: list[SignalComponentEvaluation] = []

        ema_comp = self._evaluate_ema_crossover(snapshot)
        if ema_comp is not None:
            components.append(ema_comp)

        sma_comp = self._evaluate_sma_trend(snapshot)
        if sma_comp is not None:
            components.append(sma_comp)

        rsi_comp = self._evaluate_rsi_regime(snapshot)
        if rsi_comp is not None:
            components.append(rsi_comp)

        bb_comp = self._evaluate_volatility_bollinger(snapshot)
        if bb_comp is not None:
            components.append(bb_comp)

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            if components:
                total_weight = sum((c.weight for c in components), Decimal("0"))
                weighted_sum = sum(
                    (c.score * c.weight for c in components), Decimal("0")
                )
                raw_score = weighted_sum / total_weight
            else:
                raw_score = Decimal("0.0000")

            composite_score = _quantize(raw_score)
            if composite_score > Decimal("1.0000"):
                composite_score = Decimal("1.0000")
            elif composite_score < Decimal("-1.0000"):
                composite_score = Decimal("-1.0000")

            conviction = abs(composite_score)

        if composite_score >= self._config.min_conviction_threshold:
            action = SignalAction.BUY
        elif composite_score <= -self._config.min_conviction_threshold:
            action = SignalAction.SELL
        else:
            action = SignalAction.HOLD

        stop_loss_price: Decimal | None = None
        take_profit_price: Decimal | None = None
        order_intent: OrderFSMIntent | None = None

        if action in (SignalAction.BUY, SignalAction.SELL):
            stop_loss_price, take_profit_price = self._compute_atr_brackets(
                action=action,
                close=snapshot.close,
                atr_14=snapshot.atr_14,
            )
            order_intent = OrderFSMIntent(
                ticker=effective_ticker,
                side="BUY" if action == SignalAction.BUY else "SELL",
                target_status="PENDING",
                reference_price=snapshot.close,
                suggested_stop_loss=stop_loss_price,
                suggested_take_profit=take_profit_price,
                signal_conviction=conviction,
            )

        return TradingSignalReport(
            ticker=effective_ticker,
            as_of=snapshot.as_of,
            action=action,
            conviction=conviction,
            composite_score=composite_score,
            reference_price=snapshot.close,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            components=components,
            order_intent=order_intent,
            indicators=snapshot,
        )

    def generate_signal(
        self,
        bars: Sequence[MarketBarDTO],
        ticker: str,
    ) -> TradingSignalReport:
        """
        Compute the technical indicator snapshot over `bars` and evaluate the
        multi-factor trading signal in a single pipeline call.
        """
        valid_ticker = self._validate_ticker(ticker)
        snapshot = self._indicators_service.compute_snapshot(
            bars=bars, ticker=valid_ticker
        )
        return self.evaluate_from_snapshot(snapshot=snapshot, ticker=valid_ticker)

    # ========================================================================
    # Quantitative Rule Evaluators
    # ========================================================================
    @staticmethod
    def _evaluate_ema_crossover(
        snapshot: TechnicalIndicatorsSnapshot,
    ) -> SignalComponentEvaluation | None:
        if snapshot.ema_12 is None or snapshot.ema_26 is None:
            return None

        ema_12 = snapshot.ema_12
        ema_26 = snapshot.ema_26
        prev_12 = snapshot.prev_ema_12
        prev_26 = snapshot.prev_ema_26

        if prev_12 is not None and prev_26 is not None:
            if prev_12 <= prev_26 and ema_12 > ema_26:
                return SignalComponentEvaluation(
                    rule=SignalRuleType.EMA_CROSSOVER,
                    action=SignalAction.BUY,
                    score=Decimal("1.0000"),
                    weight=WEIGHT_EMA_CROSSOVER,
                    rationale=(
                        f"Bullish EMA(12/26) crossover: EMA12 ({ema_12}) crossed "
                        f"above EMA26 ({ema_26})."
                    ),
                )
            if prev_12 >= prev_26 and ema_12 < ema_26:
                return SignalComponentEvaluation(
                    rule=SignalRuleType.EMA_CROSSOVER,
                    action=SignalAction.SELL,
                    score=Decimal("-1.0000"),
                    weight=WEIGHT_EMA_CROSSOVER,
                    rationale=(
                        f"Bearish EMA(12/26) crossover: EMA12 ({ema_12}) crossed "
                        f"below EMA26 ({ema_26})."
                    ),
                )

        if ema_12 > ema_26:
            return SignalComponentEvaluation(
                rule=SignalRuleType.EMA_CROSSOVER,
                action=SignalAction.BUY,
                score=Decimal("0.4000"),
                weight=WEIGHT_EMA_CROSSOVER,
                rationale=(
                    f"Positive short-term momentum: EMA12 ({ema_12}) > EMA26 ({ema_26})."
                ),
            )
        if ema_12 < ema_26:
            return SignalComponentEvaluation(
                rule=SignalRuleType.EMA_CROSSOVER,
                action=SignalAction.SELL,
                score=Decimal("-0.4000"),
                weight=WEIGHT_EMA_CROSSOVER,
                rationale=(
                    f"Negative short-term momentum: EMA12 ({ema_12}) < EMA26 ({ema_26})."
                ),
            )

        return SignalComponentEvaluation(
            rule=SignalRuleType.EMA_CROSSOVER,
            action=SignalAction.HOLD,
            score=Decimal("0.0000"),
            weight=WEIGHT_EMA_CROSSOVER,
            rationale=f"Neutral EMA alignment: EMA12 ({ema_12}) == EMA26 ({ema_26}).",
        )

    @staticmethod
    def _evaluate_sma_trend(
        snapshot: TechnicalIndicatorsSnapshot,
    ) -> SignalComponentEvaluation | None:
        if snapshot.sma_20 is None:
            return None

        close = snapshot.close
        sma_20 = snapshot.sma_20
        sma_50 = snapshot.sma_50

        if sma_50 is not None:
            prev_20 = snapshot.prev_sma_20
            prev_50 = snapshot.prev_sma_50
            if prev_20 is not None and prev_50 is not None:
                if prev_20 <= prev_50 and sma_20 > sma_50:
                    return SignalComponentEvaluation(
                        rule=SignalRuleType.SMA_TREND,
                        action=SignalAction.BUY,
                        score=Decimal("1.0000"),
                        weight=WEIGHT_SMA_TREND,
                        rationale=(
                            f"Golden Cross detected: SMA20 ({sma_20}) crossed above "
                            f"SMA50 ({sma_50})."
                        ),
                    )
                if prev_20 >= prev_50 and sma_20 < sma_50:
                    return SignalComponentEvaluation(
                        rule=SignalRuleType.SMA_TREND,
                        action=SignalAction.SELL,
                        score=Decimal("-1.0000"),
                        weight=WEIGHT_SMA_TREND,
                        rationale=(
                            f"Death Cross detected: SMA20 ({sma_20}) crossed below "
                            f"SMA50 ({sma_50})."
                        ),
                    )

            if close > sma_20 > sma_50:
                return SignalComponentEvaluation(
                    rule=SignalRuleType.SMA_TREND,
                    action=SignalAction.BUY,
                    score=Decimal("0.6000"),
                    weight=WEIGHT_SMA_TREND,
                    rationale=(
                        f"Bullish trend alignment: Close ({close}) > SMA20 ({sma_20}) "
                        f"> SMA50 ({sma_50})."
                    ),
                )
            if close < sma_20 < sma_50:
                return SignalComponentEvaluation(
                    rule=SignalRuleType.SMA_TREND,
                    action=SignalAction.SELL,
                    score=Decimal("-0.6000"),
                    weight=WEIGHT_SMA_TREND,
                    rationale=(
                        f"Bearish trend alignment: Close ({close}) < SMA20 ({sma_20}) "
                        f"< SMA50 ({sma_50})."
                    ),
                )

            return SignalComponentEvaluation(
                rule=SignalRuleType.SMA_TREND,
                action=SignalAction.HOLD,
                score=Decimal("0.0000"),
                weight=WEIGHT_SMA_TREND,
                rationale=(
                    f"Mixed SMA(20/50) structure: Close={close}, SMA20={sma_20}, "
                    f"SMA50={sma_50}."
                ),
            )

        # Partial window fallback: only SMA(20) is available
        if close > sma_20:
            return SignalComponentEvaluation(
                rule=SignalRuleType.SMA_TREND,
                action=SignalAction.BUY,
                score=Decimal("0.3500"),
                weight=WEIGHT_SMA_TREND,
                rationale=f"Price ({close}) trading above SMA20 ({sma_20}).",
            )
        if close < sma_20:
            return SignalComponentEvaluation(
                rule=SignalRuleType.SMA_TREND,
                action=SignalAction.SELL,
                score=Decimal("-0.3500"),
                weight=WEIGHT_SMA_TREND,
                rationale=f"Price ({close}) trading below SMA20 ({sma_20}).",
            )

        return SignalComponentEvaluation(
            rule=SignalRuleType.SMA_TREND,
            action=SignalAction.HOLD,
            score=Decimal("0.0000"),
            weight=WEIGHT_SMA_TREND,
            rationale=f"Price ({close}) equal to SMA20 ({sma_20}).",
        )

    def _evaluate_rsi_regime(
        self,
        snapshot: TechnicalIndicatorsSnapshot,
    ) -> SignalComponentEvaluation | None:
        if snapshot.rsi_14 is None:
            return None

        rsi = snapshot.rsi_14
        if rsi <= self._config.rsi_oversold:
            return SignalComponentEvaluation(
                rule=SignalRuleType.RSI_REGIME,
                action=SignalAction.BUY,
                score=Decimal("1.0000"),
                weight=WEIGHT_RSI_REGIME,
                rationale=(
                    f"Wilder RSI(14) oversold regime: {rsi} <= "
                    f"{self._config.rsi_oversold}."
                ),
            )
        if rsi >= self._config.rsi_overbought:
            return SignalComponentEvaluation(
                rule=SignalRuleType.RSI_REGIME,
                action=SignalAction.SELL,
                score=Decimal("-1.0000"),
                weight=WEIGHT_RSI_REGIME,
                rationale=(
                    f"Wilder RSI(14) overbought regime: {rsi} >= "
                    f"{self._config.rsi_overbought}."
                ),
            )

        return SignalComponentEvaluation(
            rule=SignalRuleType.RSI_REGIME,
            action=SignalAction.HOLD,
            score=Decimal("0.0000"),
            weight=WEIGHT_RSI_REGIME,
            rationale=f"Wilder RSI(14) in neutral zone ({rsi}).",
        )

    def _evaluate_volatility_bollinger(
        self,
        snapshot: TechnicalIndicatorsSnapshot,
    ) -> SignalComponentEvaluation | None:
        bb = snapshot.bollinger_20_2
        if bb is None:
            return None

        prev_bb = snapshot.prev_bollinger_20_2
        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            is_expanding = (
                prev_bb is not None
                and prev_bb.bandwidth > Decimal("0")
                and bb.bandwidth
                >= prev_bb.bandwidth * self._config.bollinger_breakout_expansion_ratio
            )

        has_emas = snapshot.ema_12 is not None and snapshot.ema_26 is not None
        is_bullish_momentum = (
            (snapshot.ema_12 > snapshot.ema_26)  # type: ignore[operator]
            if has_emas
            else (snapshot.close > bb.middle_band)
        )
        is_bearish_momentum = (
            (snapshot.ema_12 < snapshot.ema_26)  # type: ignore[operator]
            if has_emas
            else (snapshot.close < bb.middle_band)
        )

        if is_expanding and bb.percent_b > Decimal("1.0000") and is_bullish_momentum:
            return SignalComponentEvaluation(
                rule=SignalRuleType.VOLATILITY_BOLLINGER,
                action=SignalAction.BUY,
                score=Decimal("0.8500"),
                weight=WEIGHT_VOLATILITY_BOLLINGER,
                rationale=(
                    f"Bullish Bollinger volatility breakout: %B={bb.percent_b}, "
                    f"bandwidth expanded from {prev_bb.bandwidth if prev_bb else 'N/A'} "
                    f"to {bb.bandwidth}."
                ),
            )

        if is_expanding and bb.percent_b < Decimal("0.0000") and is_bearish_momentum:
            return SignalComponentEvaluation(
                rule=SignalRuleType.VOLATILITY_BOLLINGER,
                action=SignalAction.SELL,
                score=Decimal("-0.8500"),
                weight=WEIGHT_VOLATILITY_BOLLINGER,
                rationale=(
                    f"Bearish Bollinger volatility breakdown: %B={bb.percent_b}, "
                    f"bandwidth expanded from {prev_bb.bandwidth if prev_bb else 'N/A'} "
                    f"to {bb.bandwidth}."
                ),
            )

        if bb.percent_b <= self._config.bollinger_lower_percent_b:
            return SignalComponentEvaluation(
                rule=SignalRuleType.VOLATILITY_BOLLINGER,
                action=SignalAction.BUY,
                score=Decimal("0.8500"),
                weight=WEIGHT_VOLATILITY_BOLLINGER,
                rationale=(
                    f"Bollinger lower-band mean-reversion entry: %B ({bb.percent_b}) "
                    f"<= {self._config.bollinger_lower_percent_b}."
                ),
            )

        if bb.percent_b >= self._config.bollinger_upper_percent_b:
            return SignalComponentEvaluation(
                rule=SignalRuleType.VOLATILITY_BOLLINGER,
                action=SignalAction.SELL,
                score=Decimal("-0.8500"),
                weight=WEIGHT_VOLATILITY_BOLLINGER,
                rationale=(
                    f"Bollinger upper-band mean-reversion exit: %B ({bb.percent_b}) "
                    f">= {self._config.bollinger_upper_percent_b}."
                ),
            )

        return SignalComponentEvaluation(
            rule=SignalRuleType.VOLATILITY_BOLLINGER,
            action=SignalAction.HOLD,
            score=Decimal("0.0000"),
            weight=WEIGHT_VOLATILITY_BOLLINGER,
            rationale=f"Bollinger %B ({bb.percent_b}) within normal volatility corridor.",
        )

    def _compute_atr_brackets(
        self,
        action: SignalAction,
        close: Decimal,
        atr_14: Decimal | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """
        Compute volatility-adjusted stop-loss and take-profit levels via ATR(14).
        When `atr_14` is `0.0000` (e.g., flat doji price series), falls back to
        1% of `close` (`max(0.0001, close * 0.0100)`) so directional risk brackets
        remain strictly valid.
        """
        if atr_14 is None:
            return None, None

        with localcontext() as ctx:
            ctx.prec = INTERMEDIATE_DECIMAL_PRECISION
            effective_atr = (
                atr_14
                if atr_14 > Decimal("0")
                else max(INDICATOR_QUANTIZE, close * Decimal("0.0100"))
            )
            sl_dist = max(
                INDICATOR_QUANTIZE,
                _quantize(effective_atr * self._config.atr_stop_loss_multiplier),
            )
            tp_dist = max(
                INDICATOR_QUANTIZE,
                _quantize(effective_atr * self._config.atr_take_profit_multiplier),
            )

            if action == SignalAction.BUY:
                candidate_sl = max(INDICATOR_QUANTIZE, _quantize(close - sl_dist))
                stop_loss = candidate_sl if candidate_sl < close else None
                take_profit = _quantize(close + tp_dist)
                return stop_loss, take_profit

            if action == SignalAction.SELL:
                stop_loss = _quantize(close + sl_dist)
                candidate_tp = max(INDICATOR_QUANTIZE, _quantize(close - tp_dist))
                take_profit = candidate_tp if candidate_tp < close else None
                return stop_loss, take_profit

        return None, None

