"""
Unit test suite for Module 7.1 (Phases 1, 2 & 3):
- Vectorized Technical Indicators Library (`backend/app/domain/services/technical_indicators.py`)
- Trading Signal Generation Engine (`backend/app/domain/services/signal_generator.py`)
- Analytical Benchmark Reference Series & Scale Boundary Stress Tests
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from pydantic import ValidationError
import pytest

import app.domain.services as domain_services_pkg
from app.domain.services.signal_generator import (
    InvalidSignalParametersError,
    OrderFSMIntent,
    SignalAction,
    SignalComponentEvaluation,
    SignalGeneratorConfig,
    SignalGeneratorService,
    SignalRuleType,
    TradingSignalReport,
)
from app.domain.services.technical_indicators import (
    MAX_VALID_BAR_PRICE,
    BollingerBandsPoint,
    InsufficientMarketDataError,
    InvalidIndicatorParameterError,
    InvalidMarketBarSequenceError,
    TechnicalIndicatorsService,
    TechnicalIndicatorsSnapshot,
    _quantize,
)
from app.schemas.market_data import MarketBarDTO


def _make_bar(
    day_offset: int,
    open_p: str | Decimal,
    high_p: str | Decimal,
    low_p: str | Decimal,
    close_p: str | Decimal,
    volume: str | Decimal = "1000",
) -> MarketBarDTO:
    """Create a canonical UTC MarketBarDTO at a deterministic daily offset."""
    base_ts = datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc)
    return MarketBarDTO(
        timestamp=base_ts + timedelta(days=day_offset),
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        volume=Decimal(str(volume)),
    )


@pytest.mark.unit
class TestTechnicalIndicators(unittest.TestCase):
    """Unit tests verifying numerical accuracy and edge-case resilience of TechnicalIndicatorsService."""

    def setUp(self) -> None:
        self.service = TechnicalIndicatorsService()

    def test_sma_and_ema_exact_decimal_series_and_unsorted_bars(self) -> None:
        """
        Verify exact 4-decimal SMA and EMA calculations over known series and
        confirm that unsorted MarketBarDTO sequences are sorted chronologically
        before computing moving averages.
        """
        prices = [
            Decimal("10"),
            Decimal("20"),
            Decimal("30"),
            Decimal("40"),
            Decimal("50"),
        ]

        # SMA(3): [20.0000, 30.0000, 40.0000]
        sma_3 = self.service.calculate_sma(prices, period=3)
        self.assertEqual(
            sma_3,
            [Decimal("20.0000"), Decimal("30.0000"), Decimal("40.0000")],
        )

        # EMA(3): seed = 20, alpha = 2/(3+1) = 0.5
        # t=2: 20.0000
        # t=3: (40 - 20)*0.5 + 20 = 30.0000
        # t=4: (50 - 30)*0.5 + 30 = 40.0000
        ema_3 = self.service.calculate_ema(prices, period=3)
        self.assertEqual(
            ema_3,
            [Decimal("20.0000"), Decimal("30.0000"), Decimal("40.0000")],
        )

        # Non-trivial EMA(4) with fractional multiplier alpha = 2/5 = 0.4
        # prices = [100, 105, 110, 115, 130]
        # seed = (100+105+110+115)/4 = 107.5000
        # next = (130 - 107.5)*0.4 + 107.5 = 9.0 + 107.5 = 116.5000
        ema_4 = self.service.calculate_ema(
            [100, 105, 110, 115, 130], period=4
        )
        self.assertEqual(ema_4, [Decimal("107.5000"), Decimal("116.5000")])

        # Unsorted MarketBarDTO sequence produces identical results to sorted
        bars_sorted = [
            _make_bar(idx, p, p + Decimal("5"), p - Decimal("5"), p)
            for idx, p in enumerate(prices)
        ]
        bars_shuffled = [
            bars_sorted[3],
            bars_sorted[0],
            bars_sorted[4],
            bars_sorted[1],
            bars_sorted[2],
        ]
        self.assertEqual(self.service.calculate_sma(bars_shuffled, period=3), sma_3)
        self.assertEqual(self.service.calculate_ema(bars_shuffled, period=3), ema_3)

    def test_wilder_rsi_singularities_and_oscillating_benchmark(self) -> None:
        """
        Verify Wilder RSI handles monotonic gains (100.0000), monotonic losses (0.0000),
        flat series (50.0000) without ZeroDivisionError, and matches exact Wilder
        recursive smoothing on an oscillating benchmark series.
        """
        # 1. Strictly increasing series -> RSI = 100.0000
        up_series = [Decimal(100 + i * 2) for i in range(6)]
        rsi_up = self.service.calculate_wilder_rsi(up_series, period=4)
        self.assertEqual(rsi_up, [Decimal("100.0000"), Decimal("100.0000")])

        # 2. Strictly decreasing series -> RSI = 0.0000
        down_series = [Decimal(100 - i * 2) for i in range(6)]
        rsi_down = self.service.calculate_wilder_rsi(down_series, period=4)
        self.assertEqual(rsi_down, [Decimal("0.0000"), Decimal("0.0000")])

        # 3. Completely flat series -> AvgGain == 0 and AvgLoss == 0 -> RSI = 50.0000
        flat_series = [Decimal("150.00")] * 6
        rsi_flat = self.service.calculate_wilder_rsi(flat_series, period=4)
        self.assertEqual(rsi_flat, [Decimal("50.0000"), Decimal("50.0000")])

        # 4. Oscillating series with period = 3:
        # Closes: [100, 103, 101, 105, 102]
        # Deltas: [+3, -2, +4, -3]
        # Initial 3 deltas: gains = [3, 0, 4] -> avg_gain = 7/3
        #                   losses = [0, 2, 0] -> avg_loss = 2/3
        # RS_0 = (7/3) / (2/3) = 3.5 -> RSI_0 = 100 - 100/4.5 = 77.77777... -> 77.7778
        # Step 1 (delta = -3): gain = 0, loss = 3
        # avg_gain_1 = ((7/3)*2 + 0)/3 = 14/9
        # avg_loss_1 = ((2/3)*2 + 3)/3 = 13/9
        # RS_1 = 14/13 -> RSI_1 = 100 - 100/(27/13) = 1400/27 = 51.85185... -> 51.8519
        osc_series = [
            Decimal("100"),
            Decimal("103"),
            Decimal("101"),
            Decimal("105"),
            Decimal("102"),
        ]
        rsi_osc = self.service.calculate_wilder_rsi(osc_series, period=3)
        self.assertEqual(
            rsi_osc,
            [Decimal("77.7778"), Decimal("51.8519")],
        )

    def test_bollinger_bands_volatility_flat_market_and_extreme_shock(self) -> None:
        """
        Verify Bollinger Bands on:
        1. Flat price series (std_dev=0 -> upper == middle == lower, bandwidth=0.0000, %B=0.5000).
        2. Known variance window with exact population (ddof=0) and sample (ddof=1) std_dev.
        3. Extreme volatility shock where lower_band becomes negative without failing validation.
        """
        # 1. Flat market
        flat_bars = [
            _make_bar(i, "100", "100", "100", "100") for i in range(5)
        ]
        bb_flat = self.service.calculate_bollinger_bands(
            flat_bars, period=5, num_std_dev=Decimal("2"), ddof=0
        )
        self.assertEqual(len(bb_flat), 1)
        pt_flat = bb_flat[0]
        self.assertEqual(pt_flat.timestamp, flat_bars[-1].timestamp)
        self.assertEqual(pt_flat.upper_band, Decimal("100.0000"))
        self.assertEqual(pt_flat.middle_band, Decimal("100.0000"))
        self.assertEqual(pt_flat.lower_band, Decimal("100.0000"))
        self.assertEqual(pt_flat.bandwidth, Decimal("0.0000"))
        self.assertEqual(pt_flat.percent_b, Decimal("0.5000"))

        # 2. Known variance window: [10, 10, 20, 20], period=4, ddof=0
        # mean = 15, variance = ((25+25+25+25)/4) = 25, std_dev = 5
        # middle = 15.0000, upper = 15 + 2*5 = 25.0000, lower = 15 - 2*5 = 5.0000
        # bandwidth = (25 - 5) / 15 = 1.3333
        # percent_b (last close = 20) = (20 - 5) / (25 - 5) = 15 / 20 = 0.7500
        bb_known = self.service.calculate_bollinger_bands(
            [Decimal("10"), Decimal("10"), Decimal("20"), Decimal("20")],
            period=4,
            num_std_dev=Decimal("2"),
            ddof=0,
        )
        self.assertEqual(len(bb_known), 1)
        self.assertEqual(bb_known[0].middle_band, Decimal("15.0000"))
        self.assertEqual(bb_known[0].upper_band, Decimal("25.0000"))
        self.assertEqual(bb_known[0].lower_band, Decimal("5.0000"))
        self.assertEqual(bb_known[0].bandwidth, Decimal("1.3333"))
        self.assertEqual(bb_known[0].percent_b, Decimal("0.7500"))

        # 3. Extreme shock where 2 * std_dev > mean -> negative lower_band is permitted
        shock_series = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("1000")]
        bb_shock = self.service.calculate_bollinger_bands(
            shock_series, period=4, num_std_dev=Decimal("2"), ddof=0
        )
        self.assertEqual(len(bb_shock), 1)
        self.assertLess(bb_shock[0].lower_band, Decimal("0"))
        self.assertGreater(bb_shock[0].upper_band, bb_shock[0].middle_band)

    def test_atr_captures_overnight_gaps_and_wilder_smoothing(self) -> None:
        """
        Verify ATR(3) captures overnight gap-ups and gap-downs via
        TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|) and applies
        Wilder recursive smoothing.
        """
        # Bar 0: H=110, L=100, C=105 -> TR_0 = 110 - 100 = 10
        # Bar 1 (Gap up): O=120, H=125, L=118, C=122 (prev_C=105)
        #   H-L = 7, |H - prev_C| = |125 - 105| = 20, |L - prev_C| = 13 -> TR_1 = 20
        # Bar 2 (Gap down): O=102, H=104, L=98, C=100 (prev_C=122)
        #   H-L = 6, |H - prev_C| = 18, |L - prev_C| = |98 - 122| = 24 -> TR_2 = 24
        # Seed ATR_0 (period=3) = (10 + 20 + 24) / 3 = 54 / 3 = 18.0000
        # Bar 3: O=100, H=106, L=97, C=103 (prev_C=100)
        #   H-L = 9, |H - prev_C| = 6, |L - prev_C| = 3 -> TR_3 = 9
        # Wilder ATR_1 = (18 * 2 + 9) / 3 = 45 / 3 = 15.0000
        bars = [
            _make_bar(0, "102", "110", "100", "105"),
            _make_bar(1, "120", "125", "118", "122"),
            _make_bar(2, "102", "104", "98", "100"),
            _make_bar(3, "100", "106", "97", "103"),
        ]
        atr_vals = self.service.calculate_atr(bars, period=3)
        self.assertEqual(atr_vals, [Decimal("18.0000"), Decimal("15.0000")])

    def test_compute_snapshot_partial_and_full_windows_with_prev_values(self) -> None:
        """
        Verify compute_snapshot gracefully populates None for long-window indicators
        when given a short series (15 bars) and populates all current and previous
        indicators when given a full 55-bar series.
        """
        # 1. Partial window: 15 bars
        bars_15 = [
            _make_bar(
                i,
                Decimal(100 + i),
                Decimal(103 + i),
                Decimal(98 + i),
                Decimal(101 + i),
            )
            for i in range(15)
        ]
        snap_15 = self.service.compute_snapshot(bars_15, ticker=" ggal ")
        self.assertEqual(snap_15.ticker, "GGAL")
        self.assertEqual(snap_15.as_of, bars_15[-1].timestamp)
        self.assertEqual(snap_15.close, Decimal("115.0000"))
        self.assertEqual(snap_15.previous_close, Decimal("114.0000"))

        # Available at 15 bars: ema_12 (needs 12), rsi_14 (needs 15), atr_14 (needs 14)
        self.assertIsNotNone(snap_15.ema_12)
        self.assertIsNotNone(snap_15.prev_ema_12)
        self.assertIsNotNone(snap_15.rsi_14)
        self.assertIsNone(snap_15.prev_rsi_14)  # 15 bars yields exactly 1 RSI(14) point
        self.assertIsNotNone(snap_15.atr_14)
        self.assertIsNotNone(snap_15.prev_atr_14)  # 15 bars yields 2 ATR(14) points

        # Unavailable at 15 bars: sma_20, sma_50, ema_26, bollinger_20_2
        self.assertIsNone(snap_15.sma_20)
        self.assertIsNone(snap_15.prev_sma_20)
        self.assertIsNone(snap_15.sma_50)
        self.assertIsNone(snap_15.ema_26)
        self.assertIsNone(snap_15.bollinger_20_2)

        # 2. Full window: 55 bars
        bars_55 = [
            _make_bar(
                i,
                Decimal(200 + (i % 7) * 3 + i),
                Decimal(206 + (i % 7) * 3 + i),
                Decimal(197 + (i % 7) * 3 + i),
                Decimal(202 + (i % 7) * 3 + i),
            )
            for i in range(55)
        ]
        snap_55 = self.service.compute_snapshot(bars_55, ticker="YPFD")
        self.assertEqual(snap_55.ticker, "YPFD")
        self.assertIsNotNone(snap_55.sma_20)
        self.assertIsNotNone(snap_55.prev_sma_20)
        self.assertIsNotNone(snap_55.sma_50)
        self.assertIsNotNone(snap_55.prev_sma_50)
        self.assertIsNotNone(snap_55.ema_12)
        self.assertIsNotNone(snap_55.prev_ema_12)
        self.assertIsNotNone(snap_55.ema_26)
        self.assertIsNotNone(snap_55.prev_ema_26)
        self.assertIsNotNone(snap_55.rsi_14)
        self.assertIsNotNone(snap_55.prev_rsi_14)
        self.assertIsNotNone(snap_55.bollinger_20_2)
        self.assertIsNotNone(snap_55.prev_bollinger_20_2)
        self.assertIsNotNone(snap_55.atr_14)
        self.assertIsNotNone(snap_55.prev_atr_14)

    def test_validation_guards_ohlc_invariants_duplicate_timestamps_and_boolean_rejection(
        self,
    ) -> None:
        """
        Verify defensive guards reject:
        - Empty series or insufficient window lengths (InsufficientMarketDataError)
        - Invalid period/ddof/num_std_dev or booleans (InvalidIndicatorParameterError)
        - Duplicate timestamps, corrupted model_construct OHLC bars, NaN/Inf/non-positive
          prices, and boolean elements in series (InvalidMarketBarSequenceError)
        - Extra fields or invalid band ordering in DTO contracts (ValidationError)
        """
        # 1. Empty or insufficient series
        with self.assertRaises(InsufficientMarketDataError):
            self.service.calculate_sma([], period=5)
        with self.assertRaises(InsufficientMarketDataError):
            self.service.calculate_sma([Decimal("100"), Decimal("101")], period=5)
        with self.assertRaises(InsufficientMarketDataError):
            self.service.calculate_wilder_rsi([Decimal("100")] * 14, period=14)

        # 2. Invalid parameters & boolean traps
        for bad_period in (0, -5, True, False, 50_001, "20"):
            with self.assertRaises(InvalidIndicatorParameterError):
                self.service.calculate_sma([Decimal("100")] * 5, period=bad_period)  # type: ignore[arg-type]

        with self.assertRaises(InvalidIndicatorParameterError):
            self.service.calculate_bollinger_bands(
                [Decimal("100")] * 5, period=5, num_std_dev=True  # type: ignore[arg-type]
            )
        with self.assertRaises(InvalidIndicatorParameterError):
            self.service.calculate_bollinger_bands(
                [Decimal("100")] * 5, period=5, ddof=2
            )
        with self.assertRaises(InvalidIndicatorParameterError):
            self.service.calculate_bollinger_bands(
                [Decimal("100")], period=1, ddof=1
            )

        # 3. Invalid prices in scalar series (bool, <= 0, NaN, Inf, > MAX_VALID_BAR_PRICE)
        for bad_val in (
            True,
            False,
            None,
            Decimal("0"),
            Decimal("-10"),
            float("nan"),
            float("inf"),
            Decimal("1000000000001"),
        ):
            with self.assertRaises(InvalidMarketBarSequenceError):
                self.service.calculate_sma([bad_val], period=1)  # type: ignore[list-item]

        # 4. Duplicate timestamps in MarketBarDTO sequence
        dup_bar_1 = _make_bar(0, "100", "105", "95", "102")
        dup_bar_2 = _make_bar(0, "101", "106", "96", "103")
        with self.assertRaises(InvalidMarketBarSequenceError):
            self.service.validate_and_sort_bars([dup_bar_1, dup_bar_2])

        # 5. Corrupted MarketBarDTO bypassing Pydantic via model_construct (high < close)
        corrupted_bar = MarketBarDTO.model_construct(
            timestamp=datetime(2026, 1, 2, 18, 0, tzinfo=timezone.utc),
            open=Decimal("100"),
            high=Decimal("90"),
            low=Decimal("80"),
            close=Decimal("105"),
            volume=Decimal("500"),
        )
        with self.assertRaises(InvalidMarketBarSequenceError):
            self.service.validate_and_sort_bars([corrupted_bar])

        # 6. DTO contract invariants (upper < middle or extra fields)
        with self.assertRaises(ValidationError):
            BollingerBandsPoint(
                upper_band=Decimal("90"),
                middle_band=Decimal("100"),
                lower_band=Decimal("80"),
                bandwidth=Decimal("0.1"),
                percent_b=Decimal("0.5"),
            )
        with self.assertRaises(ValidationError):
            TechnicalIndicatorsSnapshot(
                ticker="GGAL\x00",
                as_of=datetime(2026, 1, 2, 18, 0, tzinfo=timezone.utc),
                close=Decimal("100"),
            )

    def test_signal_generator_bullish_crossover_and_oversold_emits_buy_with_fsm_intent(self) -> None:
        """Verify bullish EMA(12)/EMA(26) crossover + oversold RSI(14) emits BUY with valid OrderFSMIntent."""
        as_of_ts = datetime(2026, 3, 15, 18, 0, tzinfo=timezone.utc)
        snapshot = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of_ts,
            close=Decimal("100.0000"),
            ema_12=Decimal("101.2000"),
            prev_ema_12=Decimal("99.5000"),
            ema_26=Decimal("100.0000"),
            prev_ema_26=Decimal("100.1000"),
            sma_20=Decimal("99.8000"),
            prev_sma_20=Decimal("98.5000"),
            sma_50=Decimal("99.0000"),
            prev_sma_50=Decimal("99.0000"),
            rsi_14=Decimal("24.0000"),
            prev_rsi_14=Decimal("29.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("108.0000"),
                middle_band=Decimal("100.5000"),
                lower_band=Decimal("93.0000"),
                bandwidth=Decimal("0.1493"),
                percent_b=Decimal("0.0400"),
            ),
            atr_14=Decimal("2.5000"),
            prev_atr_14=Decimal("2.4000"),
        )

        generator = SignalGeneratorService()
        report = generator.evaluate_from_snapshot(snapshot, ticker=" ggal ")

        self.assertEqual(report.ticker, "GGAL")
        self.assertEqual(report.action, SignalAction.BUY)
        self.assertGreaterEqual(report.composite_score, Decimal("0.2500"))
        self.assertEqual(report.conviction, abs(report.composite_score))
        self.assertEqual(len(report.components), 4)

        self.assertIsNotNone(report.order_intent)
        assert report.order_intent is not None
        self.assertEqual(report.order_intent.side, "BUY")
        self.assertEqual(report.order_intent.target_status, "PENDING")
        self.assertEqual(report.order_intent.reference_price, Decimal("100.0000"))
        # Stop loss = 100 - 2.0 * 2.5 = 95.0000; Take profit = 100 + 3.0 * 2.5 = 107.5000
        self.assertEqual(report.stop_loss_price, Decimal("95.0000"))
        self.assertEqual(report.take_profit_price, Decimal("107.5000"))
        self.assertEqual(report.order_intent.suggested_stop_loss, Decimal("95.0000"))
        self.assertEqual(report.order_intent.suggested_take_profit, Decimal("107.5000"))
        self.assertLess(
            report.order_intent.suggested_stop_loss,
            report.order_intent.reference_price,
        )
        self.assertLess(
            report.order_intent.reference_price,
            report.order_intent.suggested_take_profit,
        )

        payload = report.order_intent.to_order_payload(
            quantity=Decimal("100"),
            portfolio_id="port-uuid-123",
        )
        self.assertEqual(
            payload,
            {
                "ticker": "GGAL",
                "side": "BUY",
                "quantity": Decimal("100.0000"),
                "price": Decimal("100.0000"),
                "status": "PENDING",
                "portfolio_id": "port-uuid-123",
            },
        )

    def test_signal_generator_bearish_crossover_and_overbought_emits_sell_with_fsm_intent(self) -> None:
        """Verify bearish EMA(12)/EMA(26) crossover + overbought RSI(14) emits SELL with directional OrderFSMIntent."""
        as_of_ts = datetime(2026, 3, 16, 18, 0, tzinfo=timezone.utc)
        snapshot = TechnicalIndicatorsSnapshot(
            ticker="YPFD",
            as_of=as_of_ts,
            close=Decimal("195.0000"),
            ema_12=Decimal("198.5000"),
            prev_ema_12=Decimal("201.0000"),
            ema_26=Decimal("200.0000"),
            prev_ema_26=Decimal("200.5000"),
            sma_20=Decimal("197.0000"),
            prev_sma_20=Decimal("200.0000"),
            sma_50=Decimal("199.0000"),
            prev_sma_50=Decimal("199.5000"),
            rsi_14=Decimal("78.0000"),
            prev_rsi_14=Decimal("71.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("199.0000"),
                middle_band=Decimal("192.0000"),
                lower_band=Decimal("185.0000"),
                bandwidth=Decimal("0.0729"),
                percent_b=Decimal("0.9600"),
            ),
            atr_14=Decimal("4.0000"),
            prev_atr_14=Decimal("3.8000"),
        )

        generator = SignalGeneratorService()
        report = generator.evaluate_from_snapshot(snapshot)

        self.assertEqual(report.ticker, "YPFD")
        self.assertEqual(report.action, SignalAction.SELL)
        self.assertLessEqual(report.composite_score, Decimal("-0.2500"))
        self.assertEqual(report.conviction, abs(report.composite_score))
        self.assertIsNotNone(report.order_intent)
        assert report.order_intent is not None
        self.assertEqual(report.order_intent.side, "SELL")
        self.assertEqual(report.order_intent.target_status, "PENDING")
        # Stop loss = 195 + 2.0 * 4.0 = 203.0000; Take profit = 195 - 3.0 * 4.0 = 183.0000
        self.assertEqual(report.order_intent.suggested_stop_loss, Decimal("203.0000"))
        self.assertEqual(report.order_intent.suggested_take_profit, Decimal("183.0000"))
        self.assertLess(
            report.order_intent.suggested_take_profit,
            report.order_intent.reference_price,
        )
        self.assertLess(
            report.order_intent.reference_price,
            report.order_intent.suggested_stop_loss,
        )

    def test_signal_generator_volatility_breakout_vs_mean_reversion_bollinger(self) -> None:
        """Verify Bollinger mean-reversion vs bandwidth-expansion breakout evaluation."""
        as_of_ts = datetime(2026, 3, 17, 18, 0, tzinfo=timezone.utc)
        generator = SignalGeneratorService()

        # 1. Mean-reversion when %B >= 0.95 WITHOUT bandwidth expansion
        mr_snapshot = TechnicalIndicatorsSnapshot(
            ticker="PAMP",
            as_of=as_of_ts,
            close=Decimal("109.5000"),
            ema_12=Decimal("105.0000"),
            ema_26=Decimal("103.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("110.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("90.0000"),
                bandwidth=Decimal("0.2000"),
                percent_b=Decimal("0.9600"),
            ),
            prev_bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("110.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("90.0000"),
                bandwidth=Decimal("0.2000"),
                percent_b=Decimal("0.8500"),
            ),
            atr_14=Decimal("2.0000"),
        )
        mr_report = generator.evaluate_from_snapshot(mr_snapshot)
        mr_bb_comp = next(
            c for c in mr_report.components if c.rule == SignalRuleType.VOLATILITY_BOLLINGER
        )
        self.assertEqual(mr_bb_comp.action, SignalAction.SELL)
        self.assertEqual(mr_bb_comp.score, Decimal("-0.8500"))

        # 2. Bullish volatility breakout when %B > 1.0 AND bandwidth expands >= 1.15x with bullish EMA momentum
        bo_snapshot = TechnicalIndicatorsSnapshot(
            ticker="PAMP",
            as_of=as_of_ts,
            close=Decimal("112.0000"),
            ema_12=Decimal("106.0000"),
            ema_26=Decimal("102.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("110.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("90.0000"),
                bandwidth=Decimal("0.2500"),
                percent_b=Decimal("1.1000"),
            ),
            prev_bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("108.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("92.0000"),
                bandwidth=Decimal("0.1600"),
                percent_b=Decimal("0.8500"),
            ),
            atr_14=Decimal("2.0000"),
        )
        bo_report = generator.evaluate_from_snapshot(bo_snapshot)
        bo_bb_comp = next(
            c for c in bo_report.components if c.rule == SignalRuleType.VOLATILITY_BOLLINGER
        )
        self.assertEqual(bo_bb_comp.action, SignalAction.BUY)
        self.assertEqual(bo_bb_comp.score, Decimal("0.8500"))

    def test_signal_generator_neutral_regime_or_short_series_emits_hold(self) -> None:
        """Verify sideways market (RSI=50, %B=0.50) or short 5-bar sequence emits HOLD with order_intent=None."""
        generator = SignalGeneratorService()

        # 1. Neutral lateral regime
        neutral_snapshot = TechnicalIndicatorsSnapshot(
            ticker="ALUA",
            as_of=datetime(2026, 3, 18, 18, 0, tzinfo=timezone.utc),
            close=Decimal("100.0000"),
            ema_12=Decimal("100.0000"),
            prev_ema_12=Decimal("100.0000"),
            ema_26=Decimal("100.0000"),
            prev_ema_26=Decimal("100.0000"),
            sma_20=Decimal("100.0000"),
            prev_sma_20=Decimal("100.0000"),
            sma_50=Decimal("100.0000"),
            prev_sma_50=Decimal("100.0000"),
            rsi_14=Decimal("50.0000"),
            prev_rsi_14=Decimal("50.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("105.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("95.0000"),
                bandwidth=Decimal("0.1000"),
                percent_b=Decimal("0.5000"),
            ),
            atr_14=Decimal("1.5000"),
        )
        neutral_report = generator.evaluate_from_snapshot(neutral_snapshot)
        self.assertEqual(neutral_report.action, SignalAction.HOLD)
        self.assertEqual(neutral_report.composite_score, Decimal("0.0000"))
        self.assertEqual(neutral_report.conviction, Decimal("0.0000"))
        self.assertIsNone(neutral_report.order_intent)
        self.assertIsNone(neutral_report.stop_loss_price)
        self.assertIsNone(neutral_report.take_profit_price)

        # 2. End-to-end generate_signal with a short 5-bar sequence (no indicators available yet)
        short_bars = [
            _make_bar(idx, "100", "110", "99", str(100 + idx))
            for idx in range(5)
        ]
        short_report = generator.generate_signal(short_bars, ticker="TXAR")
        self.assertEqual(short_report.ticker, "TXAR")
        self.assertEqual(short_report.action, SignalAction.HOLD)
        self.assertEqual(short_report.composite_score, Decimal("0.0000"))
        self.assertEqual(short_report.conviction, Decimal("0.0000"))
        self.assertIsNone(short_report.order_intent)

    def test_signal_generator_config_and_dto_invariants_validation(self) -> None:
        """Verify SignalGeneratorConfig and OrderFSMIntent enforce domain and directional invariants."""
        # 1. rsi_oversold >= rsi_overbought raises ValidationError
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(
                rsi_oversold=Decimal("70.0000"),
                rsi_overbought=Decimal("70.0000"),
            )
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(
                rsi_oversold=Decimal("75.0000"),
                rsi_overbought=Decimal("65.0000"),
            )
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(
                bollinger_lower_percent_b=Decimal("0.9500"),
                bollinger_upper_percent_b=Decimal("0.0500"),
            )

        # 2. Out-of-range min_conviction_threshold rejected
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(min_conviction_threshold=Decimal("0.0000"))
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(min_conviction_threshold=Decimal("1.5000"))

        # 3. Extra fields forbidden on frozen BaseSchema DTOs
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(unknown_param="attack")  # type: ignore[call-arg]

        # 4. OrderFSMIntent directional invariants for BUY vs SELL
        with self.assertRaises(ValidationError):
            # BUY with stop_loss >= reference_price must fail
            OrderFSMIntent(
                ticker="GGAL",
                side="BUY",
                reference_price=Decimal("100.0000"),
                suggested_stop_loss=Decimal("101.0000"),
                suggested_take_profit=Decimal("110.0000"),
                signal_conviction=Decimal("0.8000"),
            )
        with self.assertRaises(ValidationError):
            # SELL with stop_loss <= reference_price must fail
            OrderFSMIntent(
                ticker="GGAL",
                side="SELL",
                reference_price=Decimal("100.0000"),
                suggested_stop_loss=Decimal("99.0000"),
                suggested_take_profit=Decimal("90.0000"),
                signal_conviction=Decimal("0.8000"),
            )

        # 5. OrderFSMIntent.to_order_payload rejects quantity <= 0 or boolean
        valid_intent = OrderFSMIntent(
            ticker="GGAL",
            side="BUY",
            reference_price=Decimal("100.0000"),
            suggested_stop_loss=Decimal("95.0000"),
            suggested_take_profit=Decimal("108.0000"),
            signal_conviction=Decimal("0.7500"),
        )
        with self.assertRaises(InvalidSignalParametersError):
            valid_intent.to_order_payload(Decimal("0"))
        with self.assertRaises(InvalidSignalParametersError):
            valid_intent.to_order_payload(Decimal("-10"))
        with self.assertRaises(InvalidSignalParametersError):
            valid_intent.to_order_payload(True)  # type: ignore[arg-type]

        # 6. TradingSignalReport enforces HOLD <-> order_intent=None and BUY/SELL <-> matching order_intent
        as_of_ts = datetime(2026, 3, 18, 18, 0, tzinfo=timezone.utc)
        dummy_snapshot = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of_ts,
            close=Decimal("100.0000"),
        )
        with self.assertRaises(ValidationError):
            TradingSignalReport(
                ticker="GGAL",
                as_of=as_of_ts,
                action=SignalAction.HOLD,
                conviction=Decimal("0.0000"),
                composite_score=Decimal("0.0000"),
                reference_price=Decimal("100.0000"),
                components=[],
                order_intent=valid_intent,
                indicators=dummy_snapshot,
            )

    def test_benchmark_wilder_14_period_rsi_and_atr_step_by_step_reference(self) -> None:
        """
        Verify Wilder RSI(14) and ATR(14) over an 18-bar OHLC benchmark series
        against analytically precalculated arithmetic seed and recursive Wilder
        smoothing (alpha = 1/14) reference values.
        """
        # First 14 price changes (bars 0 -> 14): 10 gains of +2.0 and 4 losses of -1.5
        # Close progression:
        # t=0: 100.0
        # t=1..10: +2.0 each -> 102, 104, 106, 108, 110, 112, 114, 116, 118, 120
        # t=11..14: -1.5 each -> 118.5, 117.0, 115.5, 114.0
        # t=15: +8.0 (122.0), t=16: -7.5 (114.5), t=17: +3.5 (118.0)
        closes_18 = [
            Decimal("100.0"),
            Decimal("102.0"),
            Decimal("104.0"),
            Decimal("106.0"),
            Decimal("108.0"),
            Decimal("110.0"),
            Decimal("112.0"),
            Decimal("114.0"),
            Decimal("116.0"),
            Decimal("118.0"),
            Decimal("120.0"),
            Decimal("118.5"),
            Decimal("117.0"),
            Decimal("115.5"),
            Decimal("114.0"),
            Decimal("122.0"),
            Decimal("114.5"),
            Decimal("118.0"),
        ]

        # Build 18 OHLC bars with exact True Ranges:
        # Bars 0..13 (first 14 bars): TR = 4.0000 each -> ATR_0 (seed at t=13) = 4.0000
        # Bar 14 (C_13=115.5, C_14=114.0): H=119.5, L=112.5 -> TR_14 = 7.0000
        # Bar 15 (C_14=114.0, C_15=122.0, overnight gap up!): O=120.0, H=124.0, L=120.0 -> |H-C_14| = 10.0000
        # Bar 16 (C_15=122.0, C_16=114.5): O=118.0, H=123.0, L=114.0 -> TR_16 = 9.0000
        # Bar 17 (C_16=114.5, C_17=118.0): O=115.0, H=119.5, L=113.5 -> TR_17 = 6.0000
        bars_18: list[MarketBarDTO] = []
        for idx in range(14):
            c_val = closes_18[idx]
            prev_c = closes_18[idx - 1] if idx > 0 else c_val
            hi = max(c_val, prev_c) + Decimal("1.0")
            lo = hi - Decimal("4.0")
            bars_18.append(_make_bar(idx, c_val, hi, lo, c_val))

        bars_18.append(_make_bar(14, "114.5", "119.5", "112.5", "114.0"))
        bars_18.append(_make_bar(15, "120.0", "124.0", "120.0", "122.0"))
        bars_18.append(_make_bar(16, "118.0", "123.0", "114.0", "114.5"))
        bars_18.append(_make_bar(17, "115.0", "119.5", "113.5", "118.0"))

        rsi_14 = self.service.calculate_wilder_rsi(bars_18, period=14)
        # Analytical reference values:
        # t=14 (seed): AvgGain=20/14, AvgLoss=6/14 -> RS=10/3 -> RSI = 1000/13 = 76.9231
        # t=15 (+8.0): AvgGain=372/196, AvgLoss=78/196 -> RS=62/13 -> RSI = 248/3 = 82.6667
        # t=16 (-7.5): AvgGain=4836/2744, AvgLoss=2484/2744 -> RS=403/207 -> RSI = 4030/61 = 66.0656
        # t=17 (+3.5): AvgGain=72472/38416, AvgLoss=32292/38416 -> RS=18118/8073 -> RSI = 69.1764
        self.assertEqual(
            rsi_14,
            [
                Decimal("76.9231"),
                Decimal("82.6667"),
                Decimal("66.0656"),
                Decimal("69.1764"),
            ],
        )

        atr_14 = self.service.calculate_atr(bars_18, period=14)
        # Analytical reference values:
        # t=13 (seed): 56/14 = 4.0000
        # t=14 (TR=7): (4*13 + 7)/14 = 59/14 = 4.2143
        # t=15 (TR=10): (59/14*13 + 10)/14 = 907/196 = 4.6276
        # t=16 (TR=9): (907/196*13 + 9)/14 = 13555/2744 = 4.9399
        # t=17 (TR=6): (13555/2744*13 + 6)/14 = 192679/38416 = 5.0156
        self.assertEqual(
            atr_14,
            [
                Decimal("4.0000"),
                Decimal("4.2143"),
                Decimal("4.6276"),
                Decimal("4.9399"),
                Decimal("5.0156"),
            ],
        )

    def test_benchmark_sma_ema_linear_progression_and_asymptotic_lag_identity(self) -> None:
        """
        Verify SMA(5) and EMA(5) over a linear arithmetic progression P_t = 100 + 2t
        and over a flat-to-linear ramp against exact recurrence and lag identities.
        """
        # 1. Pure linear progression P_t = 100 + 2t for t = 0..9
        linear_prices = [Decimal(100 + 2 * t) for t in range(10)]
        sma_5 = self.service.calculate_sma(linear_prices, period=5)
        ema_5 = self.service.calculate_ema(linear_prices, period=5)

        expected_linear = [
            Decimal("104.0000"),
            Decimal("106.0000"),
            Decimal("108.0000"),
            Decimal("110.0000"),
            Decimal("112.0000"),
            Decimal("114.0000"),
        ]
        self.assertEqual(sma_5, expected_linear)
        self.assertEqual(ema_5, expected_linear)
        # Theoretical steady-state lag for period=5 and slope=2 is ((5-1)/2)*2 = 4.0000
        for idx, val in enumerate(ema_5):
            current_price = linear_prices[idx + 4]
            self.assertEqual(current_price - val, Decimal("4.0000"))

        # 2. Flat seed followed by linear ramp: [100, 100, 100, 100, 100, 102, 104, 106, 108]
        ramp_prices = [
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("102"),
            Decimal("104"),
            Decimal("106"),
            Decimal("108"),
        ]
        ramp_ema_5 = self.service.calculate_ema(ramp_prices, period=5)
        # Exact alpha = 1/3 recurrence:
        # t=4: 100.0000
        # t=5 (102): 302/3 = 100.6667
        # t=6 (104): 916/9 = 101.7778
        # t=7 (106): 2786/27 = 103.1852
        # t=8 (108): 8488/81 = 104.7901
        self.assertEqual(
            ramp_ema_5,
            [
                Decimal("100.0000"),
                Decimal("100.6667"),
                Decimal("101.7778"),
                Decimal("103.1852"),
                Decimal("104.7901"),
            ],
        )

    def test_benchmark_bollinger_bands_population_ddof0_vs_sample_ddof1_bessel_ratio(self) -> None:
        """
        Compare Bollinger Bands with ddof=0 vs ddof=1 over a 5-price window and verify
        Bessel's ratio sqrt(5/4) scaling on half-width and bandwidth.
        """
        window_5 = [
            Decimal("100"),
            Decimal("102"),
            Decimal("104"),
            Decimal("106"),
            Decimal("108"),
        ]
        bb_pop = self.service.calculate_bollinger_bands(
            window_5, period=5, num_std_dev=Decimal("2"), ddof=0
        )[0]
        bb_samp = self.service.calculate_bollinger_bands(
            window_5, period=5, num_std_dev=Decimal("2"), ddof=1
        )[0]

        # Exact precalculated ddof=0 values (sigma = sqrt(8)):
        self.assertEqual(bb_pop.middle_band, Decimal("104.0000"))
        self.assertEqual(bb_pop.upper_band, Decimal("109.6569"))
        self.assertEqual(bb_pop.lower_band, Decimal("98.3431"))
        self.assertEqual(bb_pop.bandwidth, Decimal("0.1088"))
        self.assertEqual(bb_pop.percent_b, Decimal("0.8536"))

        # Exact precalculated ddof=1 values (s = sqrt(10)):
        self.assertEqual(bb_samp.middle_band, Decimal("104.0000"))
        self.assertEqual(bb_samp.upper_band, Decimal("110.3246"))
        self.assertEqual(bb_samp.lower_band, Decimal("97.6754"))
        self.assertEqual(bb_samp.bandwidth, Decimal("0.1216"))
        self.assertEqual(bb_samp.percent_b, Decimal("0.8162"))

        # Bessel correction factor sqrt(5 / 4) = sqrt(1.25)
        bessel_factor = (Decimal("5") / Decimal("4")).sqrt()
        pop_half_width = bb_pop.upper_band - bb_pop.middle_band
        samp_half_width = bb_samp.upper_band - bb_samp.middle_band
        self.assertLessEqual(
            abs(samp_half_width - (pop_half_width * bessel_factor)),
            Decimal("0.0001"),
        )
        self.assertLessEqual(
            abs(bb_samp.bandwidth - (bb_pop.bandwidth * bessel_factor)),
            Decimal("0.0001"),
        )

    def test_signal_generator_progressive_window_activation_matrix(self) -> None:
        """
        Verify progressive rule activation across series prefixes of length
        N = 5, 15, 20, 26, and 55 bars.
        """
        bars_55 = [
            _make_bar(
                idx,
                Decimal(100 + idx),
                Decimal(103 + idx),
                Decimal(98 + idx),
                Decimal(101 + idx),
            )
            for idx in range(55)
        ]
        generator = SignalGeneratorService()

        # N = 5: 0 active rules -> HOLD, composite_score == 0.0000, components == []
        rep_5 = generator.generate_signal(bars_55[:5], ticker="GGAL")
        self.assertEqual(rep_5.action, SignalAction.HOLD)
        self.assertEqual(rep_5.composite_score, Decimal("0.0000"))
        self.assertEqual(rep_5.components, [])

        # N = 15: 1 active rule (RSI_REGIME)
        rep_15 = generator.generate_signal(bars_55[:15], ticker="GGAL")
        self.assertEqual(
            [c.rule for c in rep_15.components],
            [SignalRuleType.RSI_REGIME],
        )

        # N = 20: 3 active rules (SMA_TREND via sma_20, RSI_REGIME, VOLATILITY_BOLLINGER)
        rep_20 = generator.generate_signal(bars_55[:20], ticker="GGAL")
        self.assertEqual(
            [c.rule for c in rep_20.components],
            [
                SignalRuleType.SMA_TREND,
                SignalRuleType.RSI_REGIME,
                SignalRuleType.VOLATILITY_BOLLINGER,
            ],
        )
        self.assertIsNotNone(rep_20.indicators.sma_20)
        self.assertIsNone(rep_20.indicators.sma_50)

        # N = 26: 4 active rules (EMA_CROSSOVER joins)
        rep_26 = generator.generate_signal(bars_55[:26], ticker="GGAL")
        self.assertEqual(
            [c.rule for c in rep_26.components],
            [
                SignalRuleType.EMA_CROSSOVER,
                SignalRuleType.SMA_TREND,
                SignalRuleType.RSI_REGIME,
                SignalRuleType.VOLATILITY_BOLLINGER,
            ],
        )
        self.assertIsNotNone(rep_26.indicators.ema_12)
        self.assertIsNotNone(rep_26.indicators.ema_26)
        self.assertIsNone(rep_26.indicators.sma_50)

        # N = 55: 4 active rules with full SMA(20) and SMA(50) pair active
        rep_55 = generator.generate_signal(bars_55, ticker="GGAL")
        self.assertEqual(len(rep_55.components), 4)
        self.assertIsNotNone(rep_55.indicators.sma_20)
        self.assertIsNotNone(rep_55.indicators.sma_50)
        self.assertIsNotNone(rep_55.indicators.prev_sma_50)

    def test_signal_generator_golden_cross_and_death_cross_exact_transition_bars(self) -> None:
        """
        Verify exact score transition from crossover bar t (score = ±1.0000) to
        continuation bar t+1 (EMA score = ±0.4000, SMA score = ±0.6000).
        """
        generator = SignalGeneratorService()
        as_of_t = datetime(2026, 4, 1, 18, 0, tzinfo=timezone.utc)
        as_of_t1 = datetime(2026, 4, 2, 18, 0, tzinfo=timezone.utc)

        # 1. Bullish Golden Cross at bar t -> Continuation at bar t+1
        golden_cross_t = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of_t,
            close=Decimal("105.0000"),
            ema_12=Decimal("101.0000"),
            prev_ema_12=Decimal("100.0000"),
            ema_26=Decimal("100.5000"),
            prev_ema_26=Decimal("100.0000"),
            sma_20=Decimal("102.0000"),
            prev_sma_20=Decimal("99.5000"),
            sma_50=Decimal("101.0000"),
            prev_sma_50=Decimal("99.5000"),
        )
        rep_gc_t = generator.evaluate_from_snapshot(golden_cross_t)
        ema_gc_t = next(c for c in rep_gc_t.components if c.rule == SignalRuleType.EMA_CROSSOVER)
        sma_gc_t = next(c for c in rep_gc_t.components if c.rule == SignalRuleType.SMA_TREND)
        self.assertEqual(ema_gc_t.score, Decimal("1.0000"))
        self.assertEqual(sma_gc_t.score, Decimal("1.0000"))

        golden_cont_t1 = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of_t1,
            close=Decimal("106.0000"),
            ema_12=Decimal("102.0000"),
            prev_ema_12=Decimal("101.0000"),
            ema_26=Decimal("101.0000"),
            prev_ema_26=Decimal("100.5000"),
            sma_20=Decimal("103.0000"),
            prev_sma_20=Decimal("102.0000"),
            sma_50=Decimal("101.5000"),
            prev_sma_50=Decimal("101.0000"),
        )
        rep_gc_t1 = generator.evaluate_from_snapshot(golden_cont_t1)
        ema_gc_t1 = next(c for c in rep_gc_t1.components if c.rule == SignalRuleType.EMA_CROSSOVER)
        sma_gc_t1 = next(c for c in rep_gc_t1.components if c.rule == SignalRuleType.SMA_TREND)
        self.assertEqual(ema_gc_t1.score, Decimal("0.4000"))
        self.assertEqual(sma_gc_t1.score, Decimal("0.6000"))

        # 2. Bearish Death Cross at bar t -> Continuation at bar t+1
        death_cross_t = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of_t,
            close=Decimal("95.0000"),
            ema_12=Decimal("99.0000"),
            prev_ema_12=Decimal("100.0000"),
            ema_26=Decimal("99.5000"),
            prev_ema_26=Decimal("100.0000"),
            sma_20=Decimal("98.0000"),
            prev_sma_20=Decimal("100.5000"),
            sma_50=Decimal("99.0000"),
            prev_sma_50=Decimal("100.5000"),
        )
        rep_dc_t = generator.evaluate_from_snapshot(death_cross_t)
        ema_dc_t = next(c for c in rep_dc_t.components if c.rule == SignalRuleType.EMA_CROSSOVER)
        sma_dc_t = next(c for c in rep_dc_t.components if c.rule == SignalRuleType.SMA_TREND)
        self.assertEqual(ema_dc_t.score, Decimal("-1.0000"))
        self.assertEqual(sma_dc_t.score, Decimal("-1.0000"))

        death_cont_t1 = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of_t1,
            close=Decimal("94.0000"),
            ema_12=Decimal("98.0000"),
            prev_ema_12=Decimal("99.0000"),
            ema_26=Decimal("99.0000"),
            prev_ema_26=Decimal("99.5000"),
            sma_20=Decimal("97.0000"),
            prev_sma_20=Decimal("98.0000"),
            sma_50=Decimal("98.5000"),
            prev_sma_50=Decimal("99.0000"),
        )
        rep_dc_t1 = generator.evaluate_from_snapshot(death_cont_t1)
        ema_dc_t1 = next(c for c in rep_dc_t1.components if c.rule == SignalRuleType.EMA_CROSSOVER)
        sma_dc_t1 = next(c for c in rep_dc_t1.components if c.rule == SignalRuleType.SMA_TREND)
        self.assertEqual(ema_dc_t1.score, Decimal("-0.4000"))
        self.assertEqual(sma_dc_t1.score, Decimal("-0.6000"))

    def test_long_series_500_bars_numerical_stability_and_scale_boundaries(self) -> None:
        """
        Verify 500-bar series stability, upper price ceiling (10^12) precision safety,
        microscopic price (0.0001) bracket degradation, and domain package re-exports.
        """
        generator = SignalGeneratorService()

        # 1. 500-bar deterministic series
        bars_500: list[MarketBarDTO] = []
        for idx in range(500):
            wave = Decimal((idx % 17) - 8) * Decimal("0.75")
            base_c = Decimal("150.0000") + Decimal(idx) * Decimal("0.25") + wave
            open_p = base_c - Decimal("0.50")
            high_p = base_c + Decimal("2.25")
            low_p = base_c - Decimal("2.00")
            bars_500.append(_make_bar(idx, open_p, high_p, low_p, base_c))

        snap_500 = self.service.compute_snapshot(bars_500, ticker="SPY")
        rep_500 = generator.generate_signal(bars_500, ticker="SPY")
        expected_last_sma20 = _quantize(
            sum((b.close for b in bars_500[-20:]), Decimal("0")) / Decimal("20")
        )
        self.assertEqual(snap_500.sma_20, expected_last_sma20)
        self.assertEqual(rep_500.indicators.sma_20, expected_last_sma20)
        self.assertEqual(len(rep_500.components), 4)

        # 2. Upper scale boundary: prices up to MAX_VALID_BAR_PRICE (10^12)
        upper_bars: list[MarketBarDTO] = []
        for idx in range(30):
            c_val = MAX_VALID_BAR_PRICE - Decimal((30 - idx) * 1_000_000)
            hi_val = min(MAX_VALID_BAR_PRICE, c_val + Decimal("500000"))
            lo_val = c_val - Decimal("500000")
            upper_bars.append(_make_bar(idx, c_val, hi_val, lo_val, c_val))

        bb_upper = self.service.calculate_bollinger_bands(upper_bars, period=20)
        self.assertEqual(len(bb_upper), 11)
        upper_rep = generator.generate_signal(upper_bars, ticker="BRK.A")
        self.assertIsNotNone(upper_rep.indicators.bollinger_20_2)

        # 3. Lower scale boundary: microscopic price close == Decimal("0.0001")
        micro_as_of = datetime(2026, 5, 1, 18, 0, tzinfo=timezone.utc)
        micro_buy_snapshot = TechnicalIndicatorsSnapshot(
            ticker="PENNY",
            as_of=micro_as_of,
            close=Decimal("0.0001"),
            rsi_14=Decimal("20.0000"),
            atr_14=Decimal("0.0005"),
        )
        micro_buy_report = generator.evaluate_from_snapshot(micro_buy_snapshot)
        self.assertEqual(micro_buy_report.action, SignalAction.BUY)
        self.assertIsNone(micro_buy_report.stop_loss_price)
        self.assertIsNotNone(micro_buy_report.take_profit_price)
        assert micro_buy_report.order_intent is not None
        self.assertIsNone(micro_buy_report.order_intent.suggested_stop_loss)

        micro_sell_snapshot = TechnicalIndicatorsSnapshot(
            ticker="PENNY",
            as_of=micro_as_of,
            close=Decimal("0.0001"),
            rsi_14=Decimal("85.0000"),
            atr_14=Decimal("0.0005"),
        )
        micro_sell_report = generator.evaluate_from_snapshot(micro_sell_snapshot)
        self.assertEqual(micro_sell_report.action, SignalAction.SELL)
        self.assertIsNotNone(micro_sell_report.stop_loss_price)
        self.assertIsNone(micro_sell_report.take_profit_price)
        assert micro_sell_report.order_intent is not None
        self.assertIsNone(micro_sell_report.order_intent.suggested_take_profit)

        # 4. Verify re-exports in app.domain.services
        self.assertIs(
            domain_services_pkg.TechnicalIndicatorsService,
            TechnicalIndicatorsService,
        )
        self.assertIs(
            domain_services_pkg.SignalGeneratorService,
            SignalGeneratorService,
        )



