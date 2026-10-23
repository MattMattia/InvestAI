"""
Unit test suite for Module 7.1 (Phases 1 & 2):
- Vectorized Technical Indicators Library (`backend/app/domain/services/technical_indicators.py`)
- Trading Signal Generation Engine (`backend/app/domain/services/signal_generator.py`)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from pydantic import ValidationError
import pytest

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
    BollingerBandsPoint,
    InsufficientMarketDataError,
    InvalidIndicatorParameterError,
    InvalidMarketBarSequenceError,
    TechnicalIndicatorsService,
    TechnicalIndicatorsSnapshot,
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


