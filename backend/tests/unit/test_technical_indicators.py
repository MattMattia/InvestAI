"""
Unit test suite for Module 7.1 (Phases 1, 2 & 3):
- Vectorized Technical Indicators Library (`backend/app/domain/services/technical_indicators.py`)
- Trading Signal Generation Engine (`backend/app/domain/services/signal_generator.py`)
- Analytical Benchmark Reference Series & Scale Boundary Stress Tests
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import app.domain.services as domain_services_pkg
import pytest
from app.domain.services.signal_generator import (
    InvalidSignalParametersError,
    OrderFSMIntent,
    SignalAction,
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
from pydantic import ValidationError


def _make_bar(
    day_offset: int,
    open_p: str | Decimal,
    high_p: str | Decimal,
    low_p: str | Decimal,
    close_p: str | Decimal,
    volume: str | Decimal = "1000",
) -> MarketBarDTO:
    """Create a canonical UTC MarketBarDTO at a deterministic daily offset."""
    base_ts = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
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
        ema_4 = self.service.calculate_ema([100, 105, 110, 115, 130], period=4)
        self.assertEqual(ema_4, [Decimal("107.5000"), Decimal("116.5000")])

        # Unsorted MarketBarDTO sequence produces identical results to sorted
        bars_sorted = [
            _make_bar(idx, p, p + Decimal("5"), p - Decimal("5"), p) for idx, p in enumerate(prices)
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
        flat_bars = [_make_bar(i, "100", "100", "100", "100") for i in range(5)]
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
                [Decimal("100")] * 5,
                period=5,
                num_std_dev=True,  # type: ignore[arg-type]
            )
        with self.assertRaises(InvalidIndicatorParameterError):
            self.service.calculate_bollinger_bands([Decimal("100")] * 5, period=5, ddof=2)
        with self.assertRaises(InvalidIndicatorParameterError):
            self.service.calculate_bollinger_bands([Decimal("100")], period=1, ddof=1)

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
            timestamp=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
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
                as_of=datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                close=Decimal("100"),
            )

    def test_signal_generator_bullish_crossover_and_oversold_emits_buy_with_fsm_intent(
        self,
    ) -> None:
        """Verify bullish EMA(12)/EMA(26) crossover + oversold RSI(14) emits BUY with valid OrderFSMIntent."""
        as_of_ts = datetime(2026, 3, 15, 18, 0, tzinfo=UTC)
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

    def test_signal_generator_bearish_crossover_and_overbought_emits_sell_with_fsm_intent(
        self,
    ) -> None:
        """Verify bearish EMA(12)/EMA(26) crossover + overbought RSI(14) emits SELL with directional OrderFSMIntent."""
        as_of_ts = datetime(2026, 3, 16, 18, 0, tzinfo=UTC)
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
        as_of_ts = datetime(2026, 3, 17, 18, 0, tzinfo=UTC)
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
            as_of=datetime(2026, 3, 18, 18, 0, tzinfo=UTC),
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
        short_bars = [_make_bar(idx, "100", "110", "99", str(100 + idx)) for idx in range(5)]
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
        as_of_ts = datetime(2026, 3, 18, 18, 0, tzinfo=UTC)
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
        as_of_t = datetime(2026, 4, 1, 18, 0, tzinfo=UTC)
        as_of_t1 = datetime(2026, 4, 2, 18, 0, tzinfo=UTC)

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
        micro_as_of = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
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

    # =========================================================================
    # 6-Round Forensic Audit Expansion: 48 Additional Unit Tests (01..48)
    # =========================================================================

    def test_audit_ti_01_sma_period_1_identity_over_prices_and_bars(self) -> None:
        """Verify SMA(1) returns the exact 4-decimal quantized input sequence for scalars and bars."""
        prices = [Decimal("10.12345"), Decimal("20.55555"), Decimal("30.00004")]
        sma_1 = self.service.calculate_sma(prices, period=1)
        self.assertEqual(
            sma_1,
            [Decimal("10.1235"), Decimal("20.5556"), Decimal("30.0000")],
        )
        bars = [
            _make_bar(i, p, p + Decimal("1"), p - Decimal("1"), p) for i, p in enumerate(prices)
        ]
        self.assertEqual(self.service.calculate_sma(bars, period=1), sma_1)

    def test_audit_ti_02_sma_period_2_pairwise_averages(self) -> None:
        """Verify SMA(2) computes exact pairwise arithmetic means across consecutive prices."""
        prices = [Decimal("10"), Decimal("13"), Decimal("19"), Decimal("20")]
        self.assertEqual(
            self.service.calculate_sma(prices, period=2),
            [Decimal("11.5000"), Decimal("16.0000"), Decimal("19.5000")],
        )

    def test_audit_ti_03_sma_period_14_and_50_exact_window_lengths(self) -> None:
        """Verify SMA(14) and SMA(50) output lengths N - period + 1 and exact arithmetic averages."""
        prices_60 = [Decimal(100 + i) for i in range(60)]
        sma_14 = self.service.calculate_sma(prices_60, period=14)
        sma_50 = self.service.calculate_sma(prices_60, period=50)
        self.assertEqual(len(sma_14), 47)
        self.assertEqual(len(sma_50), 11)
        # First 14-window: average of 100..113 = 106.5000
        self.assertEqual(sma_14[0], Decimal("106.5000"))
        # First 50-window: average of 100..149 = 124.5000
        self.assertEqual(sma_50[0], Decimal("124.5000"))

    def test_audit_ti_04_sma_period_200_institutional_long_window(self) -> None:
        """Verify institutional 200-period SMA over a 210-bar series."""
        prices_210 = [Decimal(500 + 2 * i) for i in range(210)]
        sma_200 = self.service.calculate_sma(prices_210, period=200)
        self.assertEqual(len(sma_200), 11)
        # Average of 500 + 2*0 .. 500 + 2*199 is 500 + 199 = 699.0000
        self.assertEqual(sma_200[0], Decimal("699.0000"))
        self.assertEqual(sma_200[-1], Decimal("719.0000"))

    def test_audit_ti_05_sma_monotonic_decreasing_series(self) -> None:
        """Verify SMA(4) strictly decreases when input prices are strictly decreasing."""
        prices = [
            Decimal("100"),
            Decimal("90"),
            Decimal("80"),
            Decimal("70"),
            Decimal("60"),
            Decimal("50"),
        ]
        sma_4 = self.service.calculate_sma(prices, period=4)
        self.assertEqual(
            sma_4,
            [Decimal("85.0000"), Decimal("75.0000"), Decimal("65.0000")],
        )

    def test_audit_ti_06_sma_unit_impulse_response_and_decay(self) -> None:
        """Verify SMA(4) response to a single impulse spike returns to baseline after 4 steps."""
        prices = [
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("140"),
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
        ]
        sma_4 = self.service.calculate_sma(prices, period=4)
        self.assertEqual(
            sma_4,
            [
                Decimal("110.0000"),
                Decimal("110.0000"),
                Decimal("110.0000"),
                Decimal("110.0000"),
                Decimal("100.0000"),
            ],
        )

    def test_audit_ti_07_sma_step_function_transition(self) -> None:
        """Verify SMA(4) transitions linearly across a permanent step jump from 100 to 200."""
        prices = [
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("200"),
            Decimal("200"),
            Decimal("200"),
            Decimal("200"),
        ]
        self.assertEqual(
            self.service.calculate_sma(prices, period=4),
            [
                Decimal("100.0000"),
                Decimal("125.0000"),
                Decimal("150.0000"),
                Decimal("175.0000"),
                Decimal("200.0000"),
            ],
        )

    def test_audit_ti_08_sma_subpip_0_0001_and_billion_10_pow_9_prices(self) -> None:
        """Verify SMA precision at microscopic (0.0001) and institutional (10^9) price scales."""
        micro = [Decimal("0.0001"), Decimal("0.0002"), Decimal("0.0003")]
        self.assertEqual(self.service.calculate_sma(micro, period=3), [Decimal("0.0002")])
        macro = [Decimal("1000000000.0001"), Decimal("1000000000.0002"), Decimal("1000000000.0003")]
        self.assertEqual(
            self.service.calculate_sma(macro, period=3),
            [Decimal("1000000000.0002")],
        )

    def test_audit_ti_09_ema_period_1_tracks_exact_close_series(self) -> None:
        """Verify EMA(1) has smoothing multiplier alpha = 2/(1+1) = 1.0 and equals the input series."""
        prices = [Decimal("50.1234"), Decimal("55.6789"), Decimal("48.0001")]
        self.assertEqual(self.service.calculate_ema(prices, period=1), prices)

    def test_audit_ti_10_ema_period_2_alpha_two_thirds_recurrence(self) -> None:
        """Verify EMA(2) applies exact alpha = 2/3 recurrence from SMA(2) seed."""
        # P = [10, 16, 22, 28]
        # Seed EMA_0 = (10 + 16)/2 = 13.0000
        # EMA_1 = (2/3)*22 + (1/3)*13 = 57/3 = 19.0000
        # EMA_2 = (2/3)*28 + (1/3)*19 = 75/3 = 25.0000
        prices = [Decimal("10"), Decimal("16"), Decimal("22"), Decimal("28")]
        self.assertEqual(
            self.service.calculate_ema(prices, period=2),
            [Decimal("13.0000"), Decimal("19.0000"), Decimal("25.0000")],
        )

    def test_audit_ti_11_ema_period_14_and_50_smoothing_convergence(self) -> None:
        """Verify EMA(14) responds faster than EMA(50) to an upward price trend."""
        prices = [Decimal("100")] * 50 + [Decimal("150")] * 10
        ema_14 = self.service.calculate_ema(prices, period=14)
        ema_50 = self.service.calculate_ema(prices, period=50)
        self.assertGreater(ema_14[-1], ema_50[-1])
        self.assertGreater(ema_50[-1], Decimal("100.0000"))

    def test_audit_ti_12_ema_period_200_long_memory_stability(self) -> None:
        """Verify EMA(200) over a constant 250-bar series preserves exact 0.0000 drift."""
        prices = [Decimal("325.7500")] * 250
        ema_200 = self.service.calculate_ema(prices, period=200)
        self.assertEqual(len(ema_200), 51)
        self.assertTrue(all(v == Decimal("325.7500") for v in ema_200))

    def test_audit_ti_13_ema_unit_impulse_geometric_decay(self) -> None:
        """Verify EMA(3) (alpha = 0.5) halves its impulse excess at every subsequent bar."""
        # Seed [100, 100, 100] -> 100.0000
        # t=3: P=164 -> EMA = 0.5*164 + 0.5*100 = 132.0000 (+32)
        # t=4: P=100 -> EMA = 116.0000 (+16)
        # t=5: P=100 -> EMA = 108.0000 (+8)
        # t=6: P=100 -> EMA = 104.0000 (+4)
        prices = [
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("164"),
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
        ]
        self.assertEqual(
            self.service.calculate_ema(prices, period=3),
            [
                Decimal("100.0000"),
                Decimal("132.0000"),
                Decimal("116.0000"),
                Decimal("108.0000"),
                Decimal("104.0000"),
            ],
        )

    def test_audit_ti_14_ema_step_function_asymptotic_approach(self) -> None:
        """Verify EMA(3) (alpha = 0.5) closes 50% of the remaining gap to a new step level each bar."""
        prices = [
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Decimal("200"),
            Decimal("200"),
            Decimal("200"),
            Decimal("200"),
        ]
        self.assertEqual(
            self.service.calculate_ema(prices, period=3),
            [
                Decimal("100.0000"),
                Decimal("150.0000"),
                Decimal("175.0000"),
                Decimal("187.5000"),
                Decimal("193.7500"),
            ],
        )

    def test_audit_ti_15_rsi_pure_gains_returns_100_0000(self) -> None:
        """Verify Wilder RSI returns 100.0000 when all price changes are strictly positive."""
        prices = [Decimal(100 + i * 2) for i in range(20)]
        rsi = self.service.calculate_wilder_rsi(prices, period=14)
        self.assertEqual(len(rsi), 6)
        self.assertTrue(all(val == Decimal("100.0000") for val in rsi))

    def test_audit_ti_16_rsi_pure_losses_returns_0_0000(self) -> None:
        """Verify Wilder RSI returns 0.0000 when all price changes are strictly negative."""
        prices = [Decimal(200 - i * 2) for i in range(20)]
        rsi = self.service.calculate_wilder_rsi(prices, period=14)
        self.assertEqual(len(rsi), 6)
        self.assertTrue(all(val == Decimal("0.0000") for val in rsi))

    def test_audit_ti_17_rsi_constant_flat_prices_returns_50_0000(self) -> None:
        """Verify Wilder RSI returns neutral 50.0000 when avg_gain == 0 and avg_loss == 0."""
        prices = [Decimal("123.4500")] * 20
        rsi = self.service.calculate_wilder_rsi(prices, period=14)
        self.assertEqual(rsi, [Decimal("50.0000")] * 6)

    def test_audit_ti_18_rsi_symmetric_alternating_gains_and_losses_seed_50(self) -> None:
        """Verify Wilder RSI(4) seed is 50.0000 when 2 gains of +5 and 2 losses of -5 balance."""
        prices = [Decimal("100"), Decimal("105"), Decimal("100"), Decimal("105"), Decimal("100")]
        rsi_4 = self.service.calculate_wilder_rsi(prices, period=4)
        self.assertEqual(rsi_4, [Decimal("50.0000")])

    def test_audit_ti_19_rsi_period_2_ultra_fast_connors_rsi(self) -> None:
        """Verify Wilder RSI(2) over a 5-price swing sequence."""
        # Changes: +4, +2, -3, +3
        # Seed (first 2 changes: +4, +2): avg_gain=3, avg_loss=0 -> RSI_0 = 100.0000
        # Next (-3): avg_gain=(3*1+0)/2=1.5, avg_loss=(0*1+3)/2=1.5 -> RS=1 -> RSI_1 = 50.0000
        # Next (+3): avg_gain=(1.5*1+3)/2=2.25, avg_loss=(1.5*1+0)/2=0.75 -> RS=3 -> RSI_2 = 75.0000
        prices = [Decimal("100"), Decimal("104"), Decimal("106"), Decimal("103"), Decimal("106")]
        self.assertEqual(
            self.service.calculate_wilder_rsi(prices, period=2),
            [Decimal("100.0000"), Decimal("50.0000"), Decimal("75.0000")],
        )

    def test_audit_ti_20_rsi_period_7_and_21_custom_windows(self) -> None:
        """Verify Wilder RSI supports custom window lengths period=7 and period=21."""
        prices = [Decimal(100 + (i % 5) * 2 + i) for i in range(30)]
        rsi_7 = self.service.calculate_wilder_rsi(prices, period=7)
        rsi_21 = self.service.calculate_wilder_rsi(prices, period=21)
        self.assertEqual(len(rsi_7), 23)
        self.assertEqual(len(rsi_21), 9)
        self.assertTrue(all(Decimal("0") <= v <= Decimal("100") for v in rsi_7))
        self.assertTrue(all(Decimal("0") <= v <= Decimal("100") for v in rsi_21))

    def test_audit_ti_21_rsi_recovery_from_pure_loss_zero_seed(self) -> None:
        """Verify Wilder RSI(4) transitions smoothly above 0.0000 when a gain follows 4 straight losses."""
        # Changes: -4, -4, -4, -4 (seed avg_gain=0, avg_loss=4 -> RSI=0.0000), then +4
        # At t=5: avg_gain = (0*3 + 4)/4 = 1.0, avg_loss = (4*3 + 0)/4 = 3.0 -> RS = 1/3 -> RSI = 25.0000
        prices = [
            Decimal("100"),
            Decimal("96"),
            Decimal("92"),
            Decimal("88"),
            Decimal("84"),
            Decimal("88"),
        ]
        self.assertEqual(
            self.service.calculate_wilder_rsi(prices, period=4),
            [Decimal("0.0000"), Decimal("25.0000")],
        )

    def test_audit_ti_22_rsi_pullback_from_pure_gain_100_seed(self) -> None:
        """Verify Wilder RSI(4) transitions smoothly below 100.0000 when a loss follows 4 straight gains."""
        # Changes: +4, +4, +4, +4 (seed avg_gain=4, avg_loss=0 -> RSI=100.0000), then -4
        # At t=5: avg_gain = (4*3 + 0)/4 = 3.0, avg_loss = (0*3 + 4)/4 = 1.0 -> RS = 3 -> RSI = 75.0000
        prices = [
            Decimal("100"),
            Decimal("104"),
            Decimal("108"),
            Decimal("112"),
            Decimal("116"),
            Decimal("112"),
        ]
        self.assertEqual(
            self.service.calculate_wilder_rsi(prices, period=4),
            [Decimal("100.0000"), Decimal("75.0000")],
        )

    def test_audit_ti_23_bollinger_multiplier_1_0_and_1_5_scaling(self) -> None:
        """Verify Bollinger Bands width scales linearly with num_std_dev = 1.0 vs 1.5."""
        # Window [90, 100, 100, 110]: mean = 100, variance (ddof=0) = 200/4 = 50 -> std = sqrt(50)
        # Better: [94, 100, 100, 106]? No, [90, 90, 110, 110]: mean=100, var=100, std=10.0000!
        prices = [Decimal("90"), Decimal("90"), Decimal("110"), Decimal("110")]
        bb_1 = self.service.calculate_bollinger_bands(
            prices, period=4, num_std_dev=Decimal("1.0"), ddof=0
        )[0]
        bb_15 = self.service.calculate_bollinger_bands(
            prices, period=4, num_std_dev=Decimal("1.5"), ddof=0
        )[0]
        self.assertEqual(bb_1.upper_band, Decimal("110.0000"))
        self.assertEqual(bb_1.lower_band, Decimal("90.0000"))
        self.assertEqual(bb_1.bandwidth, Decimal("0.2000"))
        self.assertEqual(bb_15.upper_band, Decimal("115.0000"))
        self.assertEqual(bb_15.lower_band, Decimal("85.0000"))
        self.assertEqual(bb_15.bandwidth, Decimal("0.3000"))

    def test_audit_ti_24_bollinger_multiplier_2_5_and_3_0_wide_corridors(self) -> None:
        """Verify Bollinger Bands at 2.5 and 3.0 standard deviations on exact std=10 window."""
        prices = [Decimal("90"), Decimal("90"), Decimal("110"), Decimal("110")]
        bb_25 = self.service.calculate_bollinger_bands(
            prices, period=4, num_std_dev=Decimal("2.5"), ddof=0
        )[0]
        bb_30 = self.service.calculate_bollinger_bands(
            prices, period=4, num_std_dev=Decimal("3.0"), ddof=0
        )[0]
        self.assertEqual(bb_25.upper_band, Decimal("125.0000"))
        self.assertEqual(bb_25.lower_band, Decimal("75.0000"))
        self.assertEqual(bb_25.bandwidth, Decimal("0.5000"))
        self.assertEqual(bb_30.upper_band, Decimal("130.0000"))
        self.assertEqual(bb_30.lower_band, Decimal("70.0000"))
        self.assertEqual(bb_30.bandwidth, Decimal("0.6000"))

    def test_audit_ti_25_bollinger_percent_b_above_one_on_upper_breakout(self) -> None:
        """Verify %B > 1.0000 when the latest close exceeds the upper Bollinger band."""
        prices = [Decimal("100"), Decimal("100"), Decimal("100"), Decimal("140")]
        # mean = 110, deviations = [-10, -10, -10, +30], var (ddof=0) = 1200/4 = 300, std = 17.3205
        # With k = 1.0, upper = 127.3205 < close (140) -> %B > 1.0000
        bb = self.service.calculate_bollinger_bands(
            prices, period=4, num_std_dev=Decimal("1.0"), ddof=0
        )[0]
        self.assertGreater(bb.percent_b, Decimal("1.0000"))

    def test_audit_ti_26_bollinger_percent_b_negative_on_lower_breakdown(self) -> None:
        """Verify %B < 0.0000 when the latest close drops below the lower Bollinger band."""
        prices = [Decimal("100"), Decimal("100"), Decimal("100"), Decimal("60")]
        bb = self.service.calculate_bollinger_bands(
            prices, period=4, num_std_dev=Decimal("1.0"), ddof=0
        )[0]
        self.assertLess(bb.percent_b, Decimal("0.0000"))

    def test_audit_ti_27_bollinger_percent_b_exact_half_at_middle_band(self) -> None:
        """Verify %B == 0.5000 when the latest close equals the window SMA (middle band)."""
        prices = [Decimal("90"), Decimal("110"), Decimal("100")]
        bb = self.service.calculate_bollinger_bands(
            prices, period=3, num_std_dev=Decimal("2.0"), ddof=0
        )[0]
        self.assertEqual(bb.middle_band, Decimal("100.0000"))
        self.assertEqual(bb.percent_b, Decimal("0.5000"))

    def test_audit_ti_28_bollinger_zero_variance_flat_series_collapse(self) -> None:
        """Verify zero-variance flat series collapses upper == middle == lower with bandwidth=0 and %B=0.5."""
        prices = [Decimal("250.0000")] * 10
        bb_list = self.service.calculate_bollinger_bands(prices, period=5)
        self.assertEqual(len(bb_list), 6)
        for pt in bb_list:
            self.assertEqual(pt.upper_band, Decimal("250.0000"))
            self.assertEqual(pt.middle_band, Decimal("250.0000"))
            self.assertEqual(pt.lower_band, Decimal("250.0000"))
            self.assertEqual(pt.bandwidth, Decimal("0.0000"))
            self.assertEqual(pt.percent_b, Decimal("0.5000"))

    def test_audit_ti_29_bollinger_period_1_ddof_0_zero_width_corridor(self) -> None:
        """Verify Bollinger Bands with period=1 and ddof=0 yields zero variance and %B=0.5000."""
        bars = [_make_bar(0, "100", "105", "95", "102")]
        bb = self.service.calculate_bollinger_bands(bars, period=1, ddof=0)[0]
        self.assertEqual(bb.middle_band, Decimal("102.0000"))
        self.assertEqual(bb.bandwidth, Decimal("0.0000"))
        self.assertEqual(bb.percent_b, Decimal("0.5000"))
        self.assertEqual(bb.timestamp, bars[0].timestamp)

    def test_audit_ti_30_atr_branch_1_intraday_high_minus_low_dominance(self) -> None:
        """Verify True Range selects H_t - L_t when previous close sits inside [L_t, H_t]."""
        bars = [
            _make_bar(0, "100", "110", "90", "100"),  # TR = 20
            _make_bar(1, "100", "115", "85", "100"),  # prev_C=100 inside [85, 115] -> TR = 30
        ]
        self.assertEqual(
            self.service.calculate_atr(bars, period=2),
            [Decimal("25.0000")],
        )

    def test_audit_ti_31_atr_branch_2_overnight_gap_up_dominance(self) -> None:
        """Verify True Range selects |H_t - C_{t-1}| on an overnight gap-up bar."""
        bars = [
            _make_bar(0, "100", "105", "95", "100"),  # TR_0 = 10
            _make_bar(1, "125", "130", "124", "128"),  # H-L=6, |130-100|=30 -> TR_1 = 30
        ]
        self.assertEqual(
            self.service.calculate_atr(bars, period=2),
            [Decimal("20.0000")],
        )

    def test_audit_ti_32_atr_branch_3_overnight_gap_down_dominance(self) -> None:
        """Verify True Range selects |L_t - C_{t-1}| on an overnight gap-down bar."""
        bars = [
            _make_bar(0, "100", "105", "95", "100"),  # TR_0 = 10
            _make_bar(1, "75", "78", "70", "72"),  # H-L=8, |70-100|=30 -> TR_1 = 30
        ]
        self.assertEqual(
            self.service.calculate_atr(bars, period=2),
            [Decimal("20.0000")],
        )

    def test_audit_ti_33_atr_flat_doji_bars_returns_0_0000(self) -> None:
        """Verify Wilder ATR returns 0.0000 across completely flat doji bars (O=H=L=C)."""
        bars = [_make_bar(i, "100", "100", "100", "100") for i in range(16)]
        atr = self.service.calculate_atr(bars, period=14)
        self.assertEqual(atr, [Decimal("0.0000"), Decimal("0.0000"), Decimal("0.0000")])

    def test_audit_ti_34_atr_custom_periods_1_5_and_20(self) -> None:
        """Verify Wilder ATR supports period=1 (raw True Range), period=5, and period=20."""
        bars = [_make_bar(i, "100", "106", "96", "101") for i in range(22)]
        atr_1 = self.service.calculate_atr(bars, period=1)
        atr_5 = self.service.calculate_atr(bars, period=5)
        atr_20 = self.service.calculate_atr(bars, period=20)
        self.assertEqual(len(atr_1), 22)
        self.assertEqual(len(atr_5), 18)
        self.assertEqual(len(atr_20), 3)
        self.assertTrue(all(v == Decimal("10.0000") for v in atr_1))
        self.assertTrue(all(v == Decimal("10.0000") for v in atr_5))
        self.assertTrue(all(v == Decimal("10.0000") for v in atr_20))

    def test_audit_ti_35_compute_snapshot_single_bar_minimal_state(self) -> None:
        """Verify compute_snapshot on a 1-bar series sets close and leaves all windowed fields None."""
        bars = [_make_bar(0, "100", "105", "95", "102.5000")]
        snap = self.service.compute_snapshot(bars, ticker="GGAL")
        self.assertEqual(snap.ticker, "GGAL")
        self.assertEqual(snap.close, Decimal("102.5000"))
        self.assertIsNone(snap.previous_close)
        self.assertIsNone(snap.ema_12)
        self.assertIsNone(snap.rsi_14)
        self.assertIsNone(snap.atr_14)
        self.assertIsNone(snap.bollinger_20_2)

    def test_audit_ti_36_compute_snapshot_exact_12_and_26_bar_boundaries(self) -> None:
        """Verify compute_snapshot at N=12 (ema_12 populated, prev_ema_12 None) and N=26 (ema_26 populated, prev_ema_26 None)."""
        bars_26 = [_make_bar(i, "100", str(135 + i), "95", str(100 + i)) for i in range(26)]
        snap_12 = self.service.compute_snapshot(bars_26[:12], ticker="YPFD")
        self.assertIsNotNone(snap_12.ema_12)
        self.assertIsNone(snap_12.prev_ema_12)
        self.assertIsNone(snap_12.atr_14)

        snap_26 = self.service.compute_snapshot(bars_26, ticker="YPFD")
        self.assertIsNotNone(snap_26.ema_26)
        self.assertIsNone(snap_26.prev_ema_26)
        self.assertIsNotNone(snap_26.bollinger_20_2)
        self.assertIsNotNone(snap_26.prev_bollinger_20_2)

    def test_audit_ti_37_signal_ema_crossover_isolated_bullish_and_bearish_cross(self) -> None:
        """Verify isolated EMA_CROSSOVER rule emits +1.0000 on fresh bullish cross and -1.0000 on fresh bearish cross."""
        gen = SignalGeneratorService()
        as_of = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
        bull_snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("100"),
            ema_12=Decimal("102"),
            prev_ema_12=Decimal("99"),
            ema_26=Decimal("100"),
            prev_ema_26=Decimal("100"),
        )
        bull_rep = gen.evaluate_from_snapshot(bull_snap)
        self.assertEqual(len(bull_rep.components), 1)
        self.assertEqual(bull_rep.composite_score, Decimal("1.0000"))
        self.assertEqual(bull_rep.action, SignalAction.BUY)

        bear_snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("100"),
            ema_12=Decimal("98"),
            prev_ema_12=Decimal("101"),
            ema_26=Decimal("100"),
            prev_ema_26=Decimal("100"),
        )
        bear_rep = gen.evaluate_from_snapshot(bear_snap)
        self.assertEqual(bear_rep.composite_score, Decimal("-1.0000"))
        self.assertEqual(bear_rep.action, SignalAction.SELL)

    def test_audit_ti_38_signal_ema_crossover_equal_emas_emits_hold(self) -> None:
        """Verify EMA_CROSSOVER emits HOLD (score=0.0000) when EMA(12) == EMA(26)."""
        gen = SignalGeneratorService()
        snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            close=Decimal("100"),
            ema_12=Decimal("100"),
            ema_26=Decimal("100"),
        )
        rep = gen.evaluate_from_snapshot(snap)
        self.assertEqual(rep.action, SignalAction.HOLD)
        self.assertEqual(rep.components[0].score, Decimal("0.0000"))

    def test_audit_ti_39_signal_sma_trend_price_vs_sma20_only_fallback(self) -> None:
        """Verify SMA_TREND falls back to close vs SMA(20) (score = ±0.3500) when SMA(50) is None."""
        gen = SignalGeneratorService()
        as_of = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
        up_snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("105"),
            sma_20=Decimal("100"),
        )
        up_rep = gen.evaluate_from_snapshot(up_snap)
        self.assertEqual(up_rep.components[0].score, Decimal("0.3500"))
        self.assertEqual(up_rep.action, SignalAction.BUY)

        down_snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("95"),
            sma_20=Decimal("100"),
        )
        down_rep = gen.evaluate_from_snapshot(down_snap)
        self.assertEqual(down_rep.components[0].score, Decimal("-0.3500"))
        self.assertEqual(down_rep.action, SignalAction.SELL)

    def test_audit_ti_40_signal_sma_trend_divergent_price_below_sma20_above_sma50(self) -> None:
        """Verify SMA_TREND emits HOLD (0.0000) when SMA(20) > SMA(50) but close < SMA(20) without a fresh cross."""
        gen = SignalGeneratorService()
        snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            close=Decimal("101"),
            sma_20=Decimal("105"),
            prev_sma_20=Decimal("104"),
            sma_50=Decimal("100"),
            prev_sma_50=Decimal("99"),
        )
        rep = gen.evaluate_from_snapshot(snap)
        self.assertEqual(rep.components[0].action, SignalAction.HOLD)
        self.assertEqual(rep.components[0].score, Decimal("0.0000"))

    def test_audit_ti_41_signal_rsi_regime_exact_boundary_equality_30_and_70(self) -> None:
        """Verify RSI_REGIME triggers BUY at exact rsi_14 == 30.0000 and SELL at exact rsi_14 == 70.0000."""
        gen = SignalGeneratorService()
        as_of = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
        rep_30 = gen.evaluate_from_snapshot(
            TechnicalIndicatorsSnapshot(
                ticker="GGAL", as_of=as_of, close=Decimal("100"), rsi_14=Decimal("30.0000")
            )
        )
        self.assertEqual(rep_30.action, SignalAction.BUY)
        self.assertEqual(rep_30.composite_score, Decimal("1.0000"))

        rep_70 = gen.evaluate_from_snapshot(
            TechnicalIndicatorsSnapshot(
                ticker="GGAL", as_of=as_of, close=Decimal("100"), rsi_14=Decimal("70.0000")
            )
        )
        self.assertEqual(rep_70.action, SignalAction.SELL)
        self.assertEqual(rep_70.composite_score, Decimal("-1.0000"))

    def test_audit_ti_42_signal_bollinger_bearish_volatility_breakdown_with_expansion(self) -> None:
        """Verify VOLATILITY_BOLLINGER emits SELL (-0.8500) on bearish volatility breakdown (%B < 0 and expanding bandwidth)."""
        gen = SignalGeneratorService()
        snap = TechnicalIndicatorsSnapshot(
            ticker="YPFD",
            as_of=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            close=Decimal("88.0000"),
            ema_12=Decimal("92.0000"),
            ema_26=Decimal("96.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("110.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("90.0000"),
                bandwidth=Decimal("0.2500"),
                percent_b=Decimal("-0.1000"),
            ),
            prev_bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("108.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("92.0000"),
                bandwidth=Decimal("0.1600"),
                percent_b=Decimal("0.1500"),
            ),
        )
        rep = gen.evaluate_from_snapshot(snap)
        bb_comp = next(c for c in rep.components if c.rule == SignalRuleType.VOLATILITY_BOLLINGER)
        self.assertEqual(bb_comp.action, SignalAction.SELL)
        self.assertEqual(bb_comp.score, Decimal("-0.8500"))
        self.assertIn("breakdown", bb_comp.rationale.lower())

    def test_audit_ti_43_signal_bollinger_breakout_without_ema_uses_close_vs_middle(self) -> None:
        """Verify Bollinger breakout uses close > middle_band when EMA(12)/EMA(26) are not yet available."""
        gen = SignalGeneratorService()
        snap = TechnicalIndicatorsSnapshot(
            ticker="PAMP",
            as_of=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            close=Decimal("112.0000"),
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
        )
        rep = gen.evaluate_from_snapshot(snap)
        self.assertEqual(rep.components[0].action, SignalAction.BUY)
        self.assertEqual(rep.components[0].score, Decimal("0.8500"))

    def test_audit_ti_44_signal_weight_renormalization_with_subset_of_rules(self) -> None:
        """Verify composite_score renormalizes active rule weights when only RSI (0.25) and Bollinger (0.20) are present."""
        gen = SignalGeneratorService()
        # RSI = BUY (+1.0000, weight 0.25), Bollinger = SELL (-0.8500, weight 0.20)
        # Weighted score = (1.0 * 0.25 - 0.85 * 0.20) / (0.25 + 0.20) = 0.08 / 0.45 = 0.1778
        snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            close=Decimal("100.0000"),
            rsi_14=Decimal("25.0000"),
            bollinger_20_2=BollingerBandsPoint(
                upper_band=Decimal("110.0000"),
                middle_band=Decimal("100.0000"),
                lower_band=Decimal("90.0000"),
                bandwidth=Decimal("0.2000"),
                percent_b=Decimal("0.9800"),
            ),
        )
        rep = gen.evaluate_from_snapshot(snap)
        self.assertEqual(rep.composite_score, Decimal("0.1778"))
        self.assertEqual(rep.action, SignalAction.HOLD)

    def test_audit_ti_45_signal_exact_min_conviction_threshold_boundary_buy_sell_hold(self) -> None:
        """Verify composite_score == min_conviction_threshold triggers BUY/SELL while 0.0001 below triggers HOLD."""
        as_of = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
        # EMA continuation score is +0.4000
        snap_40 = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("105"),
            ema_12=Decimal("102"),
            prev_ema_12=Decimal("101"),
            ema_26=Decimal("100"),
            prev_ema_26=Decimal("100"),
        )
        gen_exact = SignalGeneratorService(
            config=SignalGeneratorConfig(min_conviction_threshold=Decimal("0.4000"))
        )
        self.assertEqual(gen_exact.evaluate_from_snapshot(snap_40).action, SignalAction.BUY)

        gen_higher = SignalGeneratorService(
            config=SignalGeneratorConfig(min_conviction_threshold=Decimal("0.4001"))
        )
        self.assertEqual(gen_higher.evaluate_from_snapshot(snap_40).action, SignalAction.HOLD)

    def test_audit_ti_46_signal_flat_doji_atr_zero_uses_one_percent_fallback_brackets(self) -> None:
        """Verify Audit Round 1 fix: when atr_14 == Decimal('0.0000'), fallback 1% of close produces valid brackets."""
        gen = SignalGeneratorService()
        as_of = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
        buy_snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("100.0000"),
            rsi_14=Decimal("20.0000"),
            atr_14=Decimal("0.0000"),
        )
        buy_rep = gen.evaluate_from_snapshot(buy_snap)
        self.assertEqual(buy_rep.action, SignalAction.BUY)
        # 1% of 100 = 1.0000 -> SL = 100 - 2*1 = 98.0000, TP = 100 + 3*1 = 103.0000
        self.assertEqual(buy_rep.stop_loss_price, Decimal("98.0000"))
        self.assertEqual(buy_rep.take_profit_price, Decimal("103.0000"))

        sell_snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=as_of,
            close=Decimal("100.0000"),
            rsi_14=Decimal("80.0000"),
            atr_14=Decimal("0.0000"),
        )
        sell_rep = gen.evaluate_from_snapshot(sell_snap)
        self.assertEqual(sell_rep.action, SignalAction.SELL)
        self.assertEqual(sell_rep.stop_loss_price, Decimal("102.0000"))
        self.assertEqual(sell_rep.take_profit_price, Decimal("97.0000"))

    def test_audit_ti_47_signal_atr_none_emits_intent_with_none_brackets(self) -> None:
        """Verify that when atr_14 is None, BUY/SELL signals emit OrderFSMIntent with None stop-loss and take-profit."""
        gen = SignalGeneratorService()
        snap = TechnicalIndicatorsSnapshot(
            ticker="GGAL",
            as_of=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            close=Decimal("100.0000"),
            rsi_14=Decimal("20.0000"),
            atr_14=None,
        )
        rep = gen.evaluate_from_snapshot(snap)
        self.assertEqual(rep.action, SignalAction.BUY)
        self.assertIsNone(rep.stop_loss_price)
        self.assertIsNone(rep.take_profit_price)
        assert rep.order_intent is not None
        self.assertIsNone(rep.order_intent.suggested_stop_loss)
        self.assertIsNone(rep.order_intent.suggested_take_profit)

    def test_audit_ti_48_order_fsm_intent_to_order_payload_types_and_guards(self) -> None:
        """Verify OrderFSMIntent.to_order_payload accepts int/float/Decimal and rejects sub-pip or control-char portfolio_id."""
        intent = OrderFSMIntent(
            ticker="GGAL",
            side="BUY",
            reference_price=Decimal("100.0000"),
            signal_conviction=Decimal("0.8000"),
        )
        p_int = intent.to_order_payload(25)
        self.assertEqual(p_int["quantity"], Decimal("25.0000"))
        self.assertNotIn("portfolio_id", p_int)

        p_float = intent.to_order_payload(12.5, portfolio_id=" pf-01 ")
        self.assertEqual(p_float["quantity"], Decimal("12.5000"))
        self.assertEqual(p_float["portfolio_id"], "pf-01")

        for bad_qty in (Decimal("0.00001"), float("nan"), float("inf"), "10"):
            with self.assertRaises(InvalidSignalParametersError):
                intent.to_order_payload(bad_qty)  # type: ignore[arg-type]

        for bad_pid in ("   ", "pf\x00bad", 123):
            with self.assertRaises(InvalidSignalParametersError):
                intent.to_order_payload(Decimal("10"), portfolio_id=bad_pid)  # type: ignore[arg-type]
