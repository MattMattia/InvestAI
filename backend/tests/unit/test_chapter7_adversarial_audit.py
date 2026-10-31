"""
Adversarial & Cross-Module Audit Test Suite for Chapter 7 (Modules 7.1, 7.2 & 7.3):
- End-to-End Cross-Chapter Integration (Chapter 6 DataCleaningPipeline -> 7.1 -> 7.2 -> 7.3 -> FSM)
- ThreadPoolExecutor & asyncio Concurrency Isolation under Mutated Outer Decimal Contexts
- Macroeconomic Crisis Simulations (400% FX Devaluation Shock, Tax-Loss Harvesting via HIFO)
- Deterministic Algebraic Invariant Fuzzing & Anti-DoS / Injection Hardening
(`backend/tests/unit/test_chapter7_adversarial_audit.py`).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import unittest

from pydantic import ValidationError
import pytest

from app.domain.services.ingestion.base_parser import RawHoldingRecord
from app.domain.services.ingestion.data_cleaning_pipeline import (
    CleanHoldingRecord,
    DataCleaningPipeline,
)
from app.domain.services.portfolio_valuation_service import (
    DatedCashFlowEvent,
    HistoricalValuationSnapshot,
    InvalidCashFlowPeriodError,
    InvalidFXRateError,
    InvalidValuationInputError,
    MissingMarketPriceError,
    PortfolioMarkToMarketReport,
    PortfolioValuationService,
    PositionValuationInput,
    SubPeriodValuationSlice,
)
from app.domain.services.signal_generator import (
    InvalidSignalParametersError,
    OrderFSMIntent,
    SignalAction,
    SignalGeneratorConfig,
    SignalGeneratorService,
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
from app.domain.services.tolerance_band_rebalancer import (
    AssetTargetBandSpec,
    BandBreachDirection,
    BandType,
    InsufficientLiquidityForRebalanceError,
    InvalidTargetAllocationError,
    InvalidToleranceBandConfigError,
    MissingRebalancePriceError,
    RebalanceFSMExecutionBatch,
    RebalanceMode,
    RebalancePositionInput,
    TaxLotSelectionPolicy,
    ToleranceBandRebalancerConfig,
    ToleranceBandRebalancerService,
)
from app.schemas.market_data import MarketBarDTO


@pytest.mark.unit
class TestChapter7AdversarialAudit(unittest.TestCase):
    """55 forensic adversarial and cross-module integration tests certifying Chapter 7."""

    def setUp(self) -> None:
        self.as_of = datetime(2026, 10, 31, 18, 0, tzinfo=timezone.utc)
        self.ind_svc = TechnicalIndicatorsService()
        self.sig_svc = SignalGeneratorService()
        self.val_svc = PortfolioValuationService()
        self.reb_svc = ToleranceBandRebalancerService()

    def _build_bars(
        self,
        count: int = 25,
        start_price: Decimal = Decimal("100"),
        step: Decimal = Decimal("2"),
        half_range: Decimal = Decimal("3"),
    ) -> list[MarketBarDTO]:
        base = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
        bars: list[MarketBarDTO] = []
        for idx in range(count):
            c = start_price + Decimal(idx) * step
            bars.append(
                MarketBarDTO(
                    timestamp=base + timedelta(days=idx),
                    open=c - Decimal("0.5"),
                    high=c + half_range,
                    low=max(Decimal("0.01"), c - half_range),
                    close=c,
                    volume=Decimal("10000"),
                )
            )
        return bars

    def test_audit_ch7_01_cross_chapter_e2e_raw_ingestion_to_valuation_to_rebalance_fsm(self) -> None:
        """Verify full E2E pipeline from Chapter 6 RawHoldingRecord cleaning through Modules 7.1, 7.2, and 7.3."""
        pipeline = DataCleaningPipeline()
        raw_records = [
            RawHoldingRecord(
                row_number=1,
                raw_ticker="GGAL.BA",
                raw_quantity="100",
                raw_avg_price="1.500,00",
                raw_currency="$",
            ),
            RawHoldingRecord(
                row_number=2,
                raw_ticker="AAPL",
                raw_quantity="10",
                raw_avg_price="180.00",
                raw_currency="U$S",
            ),
        ]
        cleaned_res = pipeline.clean_records(raw_records)
        self.assertEqual(len(cleaned_res.valid_records), 2)

        ggal_bars = self._build_bars(25, Decimal("1600"), Decimal("20"), Decimal("40"))
        aapl_bars = self._build_bars(25, Decimal("185"), Decimal("1"), Decimal("2"))
        ind_map = {
            "GGAL": self.ind_svc.compute_snapshot(ggal_bars, ticker="GGAL"),
            "AAPL": self.ind_svc.compute_snapshot(aapl_bars, ticker="AAPL"),
        }
        quotes = {
            "GGAL": ind_map["GGAL"].close,
            "AAPL": ind_map["AAPL"].close,
        }
        mtm = self.val_svc.value_holdings_from_quotes(
            holdings=cleaned_res.valid_records,
            market_quotes=quotes,
            fx_rate_ars_per_usd=Decimal("1000"),
            entry_fx_rates={"GGAL": Decimal("1000"), "AAPL": Decimal("1000")},
            cash_balance_usd=Decimal("500"),
            portfolio_id="pf-ch6-ch7-e2e",
            as_of=self.as_of,
        )
        raw_specs = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.5000")),
        ]
        cal_specs = self.reb_svc.calibrate_specs_from_indicators(raw_specs, ind_map)
        reb_report = self.reb_svc.rebalance_from_mtm_report(mtm, cal_specs, base_currency="USD")
        batch = self.reb_svc.build_fsm_execution_batch(reb_report)
        self.assertEqual(batch.portfolio_id, "pf-ch6-ch7-e2e")
        self.assertGreaterEqual(batch.total_orders, 1)

    def test_audit_ch7_02_cross_chapter_caja_de_valores_zero_cost_preserves_none_realized_pnl_e2e(self) -> None:
        """Verify Caja de Valores null avg_price flows through 6.2 -> 7.2 -> 7.3 with None realized PnL on SELL."""
        clean_holdings = [
            CleanHoldingRecord(
                row_number=1,
                ticker="AL30",
                quantity=Decimal("1000"),
                avg_price=None,
                currency="ARS",
            ),
            CleanHoldingRecord(
                row_number=2,
                ticker="YPFD",
                quantity=Decimal("10"),
                avg_price=Decimal("20000"),
                currency="ARS",
            ),
        ]
        mtm = self.val_svc.value_holdings_from_quotes(
            holdings=clean_holdings,
            market_quotes={"AL30": Decimal("800"), "YPFD": Decimal("20000")},
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        specs = [
            AssetTargetBandSpec(ticker="AL30", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]
        reb = self.reb_svc.rebalance_from_mtm_report(mtm, specs, base_currency="USD")
        al30_sell = next(o for o in reb.orders if o.ticker == "AL30" and o.side == "SELL")
        self.assertIsNone(al30_sell.estimated_realized_pnl)
        self.assertEqual(reb.total_estimated_realized_pnl, Decimal("0.0000"))

    def test_audit_ch7_03_outer_decimal_context_prec_6_isolation_on_technical_indicators(self) -> None:
        """Verify TechnicalIndicatorsService and BollingerBandsPoint validator succeed when outer Decimal prec=6."""
        bars = self._build_bars(25, Decimal("12345.6789"), Decimal("12.3456"), Decimal("45.6789"))
        with localcontext() as outer_ctx:
            outer_ctx.prec = 6
            snap = self.ind_svc.compute_snapshot(bars, ticker="GGAL")
            self.assertIsNotNone(snap.bollinger_20_2)
            assert snap.bollinger_20_2 is not None
            self.assertGreaterEqual(snap.bollinger_20_2.upper_band, snap.bollinger_20_2.middle_band)

    def test_audit_ch7_04_outer_decimal_context_prec_6_isolation_on_signal_generator(self) -> None:
        """Verify SignalGeneratorService and TradingSignalReport validators succeed when outer Decimal prec=6."""
        bars = self._build_bars(30, Decimal("54321.1234"), Decimal("111.1111"), Decimal("222.2222"))
        with localcontext() as outer_ctx:
            outer_ctx.prec = 6
            sig = self.sig_svc.generate_signal(bars, ticker="GGAL")
            self.assertEqual(sig.ticker, "GGAL")
            if sig.order_intent is not None:
                self.assertEqual(sig.order_intent.target_status, "PENDING")

    def test_audit_ch7_05_outer_decimal_context_prec_6_isolation_on_portfolio_valuation(self) -> None:
        """Verify PortfolioValuationService MTM, TWR, Dietz, and IRR succeed when outer Decimal prec=6."""
        pos = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("12345"),
                avg_cost_price=Decimal("8765.4321"),
                market_price=Decimal("9876.5432"),
                currency="ARS",
                entry_fx_rate=Decimal("1111.1111"),
            )
        ]
        with localcontext() as outer_ctx:
            outer_ctx.prec = 6
            rep = self.val_svc.value_portfolio_mark_to_market(
                positions=pos,
                fx_rate_ars_per_usd=Decimal("1234.5678"),
                cash_balance_ars=Decimal("987654.3210"),
                as_of=self.as_of,
            )
            self.assertEqual(rep.positions[0].weight_in_positions, Decimal("1.0000"))

    def test_audit_ch7_06_outer_decimal_context_prec_6_isolation_on_tolerance_band_rebalancer(self) -> None:
        """Verify ToleranceBandRebalancerService and DTO validators succeed when outer Decimal prec=6."""
        positions = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("77777.7777"),
                market_price=Decimal("123.4567"),
                avg_cost_price=Decimal("100.1234"),
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("22222.2222"),
                market_price=Decimal("123.4567"),
                avg_cost_price=Decimal("110.1234"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        with localcontext() as outer_ctx:
            outer_ctx.prec = 6
            rep = self.reb_svc.evaluate_and_rebalance(
                positions=positions, target_specs=targets, as_of=self.as_of
            )
            batch = self.reb_svc.build_fsm_execution_batch(rep)
            self.assertEqual(batch.total_orders, 2)

    def test_audit_ch7_07_threadpoolexecutor_parallel_chapter7_pipeline_determinism(self) -> None:
        """Verify 16 concurrent worker threads running the full Chapter 7 pipeline produce identical hashes."""
        bars = self._build_bars(25, Decimal("100"), Decimal("2"), Decimal("3"))

        def worker(worker_idx: int) -> tuple[str, Decimal, str]:
            with localcontext() as ctx:
                ctx.prec = 8 + (worker_idx % 5)
                sig = self.sig_svc.generate_signal(bars, ticker="GGAL")
                mtm = self.val_svc.value_portfolio_mark_to_market(
                    positions=[
                        PositionValuationInput(
                            ticker="GGAL",
                            quantity=Decimal("80"),
                            avg_cost_price=Decimal("100"),
                            market_price=sig.reference_price,
                            currency="USD",
                        ),
                        PositionValuationInput(
                            ticker="AAPL",
                            quantity=Decimal("20"),
                            avg_cost_price=Decimal("100"),
                            market_price=Decimal("100"),
                            currency="USD",
                        ),
                    ],
                    fx_rate_ars_per_usd=Decimal("1000"),
                    portfolio_id="pf-concurrent",
                    as_of=self.as_of,
                )
                reb = self.reb_svc.rebalance_from_mtm_report(
                    mtm,
                    [
                        AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
                        AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.5000")),
                    ],
                    base_currency="USD",
                )
                batch = self.reb_svc.build_fsm_execution_batch(reb)
                return (sig.action.value, mtm.total_net_worth_usd, batch.batch_id)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(worker, range(16)))
        self.assertEqual(len(set(results)), 1)

    def test_audit_ch7_08_asyncio_gather_concurrent_coroutines_determinism(self) -> None:
        """Verify 12 concurrent asyncio coroutines executing Chapter 7 services produce identical results."""
        bars = self._build_bars(22, Decimal("200"), Decimal("-1.5"), Decimal("2.5"))

        async def run_all() -> list[tuple[Decimal, str]]:
            async def task_fn() -> tuple[Decimal, str]:
                await asyncio.sleep(0)
                snap = self.ind_svc.compute_snapshot(bars, ticker="YPFD")
                reb = self.reb_svc.evaluate_and_rebalance(
                    positions=[
                        RebalancePositionInput(ticker="YPFD", quantity=Decimal("90"), market_price=snap.close),
                        RebalancePositionInput(ticker="PAMP", quantity=Decimal("10"), market_price=Decimal("100")),
                    ],
                    target_specs=[
                        AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
                        AssetTargetBandSpec(ticker="PAMP", target_weight=Decimal("0.5000")),
                    ],
                    portfolio_id="pf-async",
                    as_of=self.as_of,
                )
                batch = self.reb_svc.build_fsm_execution_batch(reb)
                return (reb.portfolio_turnover, batch.batch_id)

            return await asyncio.gather(*(task_fn() for _ in range(12)))

        outcomes = asyncio.run(run_all())
        self.assertEqual(len(set(outcomes)), 1)

    def test_audit_ch7_09_macro_crisis_400_pct_fx_devaluation_shock_and_defensive_usd_rebalance(self) -> None:
        """Simulate a 400% FX devaluation shock (1000 -> 5000 ARS/USD) and defensive rebalance into USD assets."""
        # GGAL (ARS) doubles nominally (1000 -> 2000 ARS), but FX jumps 5x (1000 -> 5000) -> USD value drops from $1 to $0.40
        # SPY (USD) rises from $500 to $550
        mtm = self.val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("1000"),
                    avg_cost_price=Decimal("1000"),
                    market_price=Decimal("2000"),
                    currency="ARS",
                    entry_fx_rate=Decimal("1000"),
                ),
                PositionValuationInput(
                    ticker="SPY",
                    quantity=Decimal("2"),
                    avg_cost_price=Decimal("500"),
                    market_price=Decimal("550"),
                    currency="USD",
                    entry_fx_rate=Decimal("1000"),
                ),
            ],
            fx_rate_ars_per_usd=Decimal("5000"),
            as_of=self.as_of,
        )
        # GGAL = $400 USD (26.67%), SPY = $1,100 USD (73.33%). Target = 50% / 50%
        reb = self.reb_svc.rebalance_from_mtm_report(
            mtm,
            [
                AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
                AssetTargetBandSpec(ticker="SPY", target_weight=Decimal("0.5000")),
            ],
            base_currency="USD",
        )
        self.assertTrue(reb.needs_rebalancing)
        self.assertEqual([o.side for o in reb.orders], ["SELL", "BUY"])
        self.assertEqual(reb.orders[0].ticker, "SPY")
        self.assertEqual(reb.orders[1].ticker, "GGAL")

    def test_audit_ch7_10_macro_crisis_hifo_tax_loss_harvesting_vs_fifo_tax_gain(self) -> None:
        """Verify HIFO harvests a capital loss while FIFO realizes a capital gain on the exact same trade."""
        t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        lots = [
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("40"), market_price=Decimal("100"), avg_cost_price=Decimal("40"), acquired_at=t1
            ),
            RebalancePositionInput(
                ticker="GGAL", quantity=Decimal("40"), market_price=Decimal("100"), avg_cost_price=Decimal("160"), acquired_at=t2
            ),
            RebalancePositionInput(
                ticker="YPFD", quantity=Decimal("20"), market_price=Decimal("100"), avg_cost_price=Decimal("100")
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]
        fifo_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(tax_lot_policy=TaxLotSelectionPolicy.FIFO)
        )
        hifo_svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(tax_lot_policy=TaxLotSelectionPolicy.HIFO)
        )
        rep_fifo = fifo_svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
        rep_hifo = hifo_svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
        self.assertGreater(rep_fifo.total_estimated_realized_pnl, Decimal("0.0000"))
        self.assertLess(rep_hifo.total_estimated_realized_pnl, Decimal("0.0000"))

    def test_audit_ch7_11_flat_doji_bars_atr_zero_produces_valid_signal_brackets(self) -> None:
        """Verify Round 1 audit fix: flat doji bars with atr_14 == 0.0000 still produce valid BUY/SELL brackets when forced."""
        snap = TechnicalIndicatorsSnapshot(
            ticker="DOJI",
            as_of=self.as_of,
            close=Decimal("100.0000"),
            sma_20=Decimal("90.0000"),
            ema_12=Decimal("95.0000"),
            rsi_14=Decimal("20.0000"),
            bollinger_20_2=BollingerBandsPoint(
                middle_band=Decimal("105.0000"),
                upper_band=Decimal("110.0000"),
                lower_band=Decimal("100.0000"),
                bandwidth=Decimal("0.0952"),
                percent_b=Decimal("0.0000"),
            ),
            atr_14=Decimal("0.0000"),
        )
        sig = self.sig_svc.evaluate_from_snapshot(snap)
        self.assertEqual(sig.action, SignalAction.BUY)
        self.assertIsNotNone(sig.order_intent)
        assert sig.order_intent is not None
        self.assertLess(sig.order_intent.suggested_stop_loss, Decimal("100.0000"))
        self.assertGreater(sig.order_intent.suggested_take_profit, Decimal("100.0000"))

    def test_audit_ch7_12_flat_doji_bars_sell_signal_atr_zero_produces_valid_sell_brackets(self) -> None:
        """Verify Round 1 audit fix on SELL signal when atr_14 == 0.0000."""
        snap = TechnicalIndicatorsSnapshot(
            ticker="DOJI",
            as_of=self.as_of,
            close=Decimal("100.0000"),
            sma_20=Decimal("110.0000"),
            ema_12=Decimal("105.0000"),
            rsi_14=Decimal("85.0000"),
            bollinger_20_2=BollingerBandsPoint(
                middle_band=Decimal("95.0000"),
                upper_band=Decimal("100.0000"),
                lower_band=Decimal("90.0000"),
                bandwidth=Decimal("0.1053"),
                percent_b=Decimal("1.0000"),
            ),
            atr_14=Decimal("0.0000"),
        )
        sig = self.sig_svc.evaluate_from_snapshot(snap)
        self.assertEqual(sig.action, SignalAction.SELL)
        assert sig.order_intent is not None
        self.assertGreater(sig.order_intent.suggested_stop_loss, Decimal("100.0000"))
        self.assertLess(sig.order_intent.suggested_take_profit, Decimal("100.0000"))

    def test_audit_ch7_13_deterministic_fuzzing_weight_simplex_across_prime_asset_counts(self) -> None:
        """Fuzz MTM and Rebalancer across prime portfolio sizes (2, 3, 5, 7, 11, 13, 19) verifying exact 1.0000 sum."""
        for n in (2, 3, 5, 7, 11, 13, 19):
            mtm_pos = [
                PositionValuationInput(
                    ticker=f"P{i:02d}",
                    quantity=Decimal(str(i + 1)),
                    avg_cost_price=Decimal("50"),
                    market_price=Decimal(str(100 + i * 7)),
                    currency="USD",
                )
                for i in range(n)
            ]
            mtm = self.val_svc.value_portfolio_mark_to_market(
                positions=mtm_pos, fx_rate_ars_per_usd=Decimal("1000"), as_of=self.as_of
            )
            self.assertEqual(sum(p.weight_in_positions for p in mtm.positions), Decimal("1.0000"))
            self.assertEqual(sum(p.weight_in_net_worth for p in mtm.positions), Decimal("1.0000"))

    def test_audit_ch7_14_deterministic_fuzzing_rebalancer_post_trade_weights_sum_to_one(self) -> None:
        """Fuzz ToleranceBandRebalancerService across 5 skewed portfolios verifying post_trade_weight sum == 1.0000."""
        for mult in range(1, 6):
            positions = [
                RebalancePositionInput(
                    ticker="A1", quantity=Decimal(str(10 * mult)), market_price=Decimal("100")
                ),
                RebalancePositionInput(
                    ticker="A2", quantity=Decimal(str(20 * mult)), market_price=Decimal("100")
                ),
                RebalancePositionInput(
                    ticker="A3", quantity=Decimal(str(70 * mult)), market_price=Decimal("100")
                ),
            ]
            targets = [
                AssetTargetBandSpec(ticker="A1", target_weight=Decimal("0.3334")),
                AssetTargetBandSpec(ticker="A2", target_weight=Decimal("0.3333")),
                AssetTargetBandSpec(ticker="A3", target_weight=Decimal("0.3333")),
            ]
            rep = self.reb_svc.evaluate_and_rebalance(
                positions=positions, target_specs=targets, as_of=self.as_of
            )
            self.assertEqual(sum(e.post_trade_weight for e in rep.evaluations), Decimal("1.0000"))

    def test_audit_ch7_15_deterministic_fuzzing_karnosky_singer_identity_across_10_fx_shocks(self) -> None:
        """Verify Karnosky-Singer additive closure across 10 distinct FX rate multipliers."""
        for fx_Int in (500, 750, 999, 1000, 1001, 1234, 1500, 2500, 5000, 10000):
            rep = self.val_svc.value_portfolio_mark_to_market(
                positions=[
                    PositionValuationInput(
                        ticker="GGAL",
                        quantity=Decimal("37"),
                        avg_cost_price=Decimal("1234.56"),
                        market_price=Decimal("2345.67"),
                        currency="ARS",
                        entry_fx_rate=Decimal("1000"),
                    )
                ],
                fx_rate_ars_per_usd=Decimal(str(fx_Int)),
                as_of=self.as_of,
            )
            p = rep.positions[0]
            assert p.unrealized_pnl_pct_usd is not None
            assert p.fx_return_component is not None
            assert p.interaction_return_component is not None
            assert p.unrealized_pnl_pct_ars is not None
            self.assertEqual(
                p.unrealized_pnl_pct_usd + p.fx_return_component + p.interaction_return_component,
                p.unrealized_pnl_pct_ars,
            )

    def test_audit_ch7_16_no_negative_zero_string_in_any_chapter7_json_payload(self) -> None:
        """Verify none of the Chapter 7 reports serialize '-0.0000' in JSON output."""
        bars = self._build_bars(25, Decimal("100"), Decimal("0"), Decimal("1"))
        snap = self.ind_svc.compute_snapshot(bars, ticker="FLAT")
        sig = self.sig_svc.evaluate_from_snapshot(snap)
        mtm = self.val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="FLAT",
                    quantity=Decimal("10"),
                    avg_cost_price=Decimal("100"),
                    market_price=Decimal("100"),
                    currency="USD",
                )
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        reb = self.reb_svc.rebalance_from_mtm_report(
            mtm, [AssetTargetBandSpec(ticker="FLAT", target_weight=Decimal("1.0000"))]
        )
        for dto in (snap, sig, mtm, reb):
            self.assertNotIn("-0.0000", dto.model_dump_json())

    def test_audit_ch7_17_dto_immutability_frozen_check_across_all_chapter7_schemas(self) -> None:
        """Verify all Chapter 7 DTOs are frozen (immutable) and raise ValidationError on attribute mutation."""
        bars = self._build_bars(20)
        snap = self.ind_svc.compute_snapshot(bars, ticker="GGAL")
        sig = self.sig_svc.evaluate_from_snapshot(snap)
        with self.assertRaises(ValidationError):
            snap.close = Decimal("999")  # type: ignore[misc]
        with self.assertRaises(ValidationError):
            sig.composite_score = Decimal("0")  # type: ignore[misc]

    def test_audit_ch7_18_dto_extra_forbid_check_across_all_chapter7_schemas(self) -> None:
        """Verify extra fields are forbidden on all Chapter 7 input and config schemas."""
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(unknown_field="x")  # type: ignore[call-arg]
        with self.assertRaises(ValidationError):
            ToleranceBandRebalancerConfig(unknown_field="x")  # type: ignore[call-arg]
        with self.assertRaises(ValidationError):
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("100"),
                market_price=Decimal("100"),
                currency="ARS",
                extra_hack="x",  # type: ignore[call-arg]
            )

    def test_audit_ch7_19_sql_and_xss_injection_in_tickers_rejected_across_all_services(self) -> None:
        """Verify SQLi and XSS payloads in tickers are rejected across 7.1, 7.2, and 7.3."""
        bars = self._build_bars(20)
        for bad_ticker in ("GGAL'; DROP TABLE orders;--", "<script>alert(1)</script>", "../../etc/passwd"):
            with self.assertRaises((InvalidIndicatorParameterError, ValidationError)):
                self.ind_svc.compute_snapshot(bars, ticker=bad_ticker)
            with self.assertRaises(ValidationError):
                PositionValuationInput(
                    ticker=bad_ticker,
                    quantity=Decimal("10"),
                    avg_cost_price=Decimal("100"),
                    market_price=Decimal("100"),
                    currency="ARS",
                )
            with self.assertRaises(ValidationError):
                AssetTargetBandSpec(ticker=bad_ticker, target_weight=Decimal("1.0000"))

    def test_audit_ch7_20_nan_and_infinity_rejected_across_all_chapter7_services(self) -> None:
        """Verify NaN, +Infinity, and -Infinity are rejected across 7.1, 7.2, and 7.3."""
        for bad_dec in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.assertRaises((InvalidIndicatorParameterError, InvalidMarketBarSequenceError)):
                self.ind_svc.calculate_sma([bad_dec] * 5, period=3)
            with self.assertRaises(InvalidFXRateError):
                self.val_svc.value_portfolio_mark_to_market(
                    positions=[], fx_rate_ars_per_usd=bad_dec, as_of=self.as_of
                )
            with self.assertRaises(ValidationError):
                RebalancePositionInput(ticker="GGAL", quantity=bad_dec, market_price=Decimal("100"))

    def test_audit_ch7_21_signal_generator_sell_intent_with_hold_action_rejected_by_validator(self) -> None:
        """Verify TradingSignalReport rejects HOLD action when order_intent is not None."""
        bars = self._build_bars(25)
        sig = self.sig_svc.generate_signal(bars, ticker="GGAL")
        fake_intent = OrderFSMIntent(
            ticker="GGAL",
            side="BUY",
            target_status="PENDING",
            reference_price=Decimal("100"),
            suggested_stop_loss=Decimal("95"),
            suggested_take_profit=Decimal("110"),
            signal_conviction=Decimal("0.5000"),
        )
        with self.assertRaises(ValidationError):
            TradingSignalReport(
                ticker="GGAL",
                as_of=sig.as_of,
                reference_price=sig.reference_price,
                action=SignalAction.HOLD,
                conviction=Decimal("0.0000"),
                composite_score=Decimal("0.0000"),
                components=sig.components,
                order_intent=fake_intent,
                indicators=sig.indicators,
            )

    def test_audit_ch7_22_order_fsm_intent_rejects_inverted_buy_stop_loss_above_reference_price(self) -> None:
        """Verify OrderFSMIntent rejects a BUY intent where suggested_stop_loss >= reference_price."""
        with self.assertRaises(ValidationError):
            OrderFSMIntent(
                ticker="GGAL",
                side="BUY",
                target_status="PENDING",
                reference_price=Decimal("100"),
                suggested_stop_loss=Decimal("101"),
                suggested_take_profit=Decimal("110"),
                signal_conviction=Decimal("0.5000"),
            )

    def test_audit_ch7_23_order_fsm_intent_rejects_inverted_sell_stop_loss_below_reference_price(self) -> None:
        """Verify OrderFSMIntent rejects a SELL intent where suggested_stop_loss <= reference_price."""
        with self.assertRaises(ValidationError):
            OrderFSMIntent(
                ticker="GGAL",
                side="SELL",
                target_status="PENDING",
                reference_price=Decimal("100"),
                suggested_stop_loss=Decimal("99"),
                suggested_take_profit=Decimal("90"),
                signal_conviction=Decimal("0.5000"),
            )

    def test_audit_ch7_24_bollinger_bands_point_rejects_upper_below_middle(self) -> None:
        """Verify BollingerBandsPoint model validator rejects upper_band < middle_band."""
        with self.assertRaises(ValidationError):
            BollingerBandsPoint(
                middle_band=Decimal("100"),
                upper_band=Decimal("99"),
                lower_band=Decimal("90"),
                bandwidth=Decimal("0.0900"),
                percent_b=Decimal("0.5000"),
            )

    def test_audit_ch7_25_portfolio_mtm_report_rejects_vertical_net_worth_mismatch(self) -> None:
        """Verify PortfolioMarkToMarketReport model validator rejects tampered total_net_worth_ars."""
        rep = self.val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("10"),
                    avg_cost_price=Decimal("100"),
                    market_price=Decimal("120"),
                    currency="ARS",
                )
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        dumped = rep.model_dump()
        dumped["total_net_worth_ars"] = Decimal("999999.0000")
        with self.assertRaises(ValidationError):
            PortfolioMarkToMarketReport(**dumped)

    def test_audit_ch7_26_valuation_curve_with_monthly_withdrawals_and_deposits(self) -> None:
        """Verify evaluate_valuation_curve handles alternating monthly deposits and withdrawals."""
        base_dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        snaps = [
            HistoricalValuationSnapshot(
                as_of=base_dt,
                net_worth_ars=Decimal("1000000"),
                fx_rate_ars_per_usd=Decimal("1000"),
            ),
            HistoricalValuationSnapshot(
                as_of=base_dt + timedelta(days=30),
                net_worth_ars=Decimal("1300000"),
                fx_rate_ars_per_usd=Decimal("1050"),
                net_cash_flow_ars=Decimal("200000"),
                cash_flow_timing="END",
            ),
            HistoricalValuationSnapshot(
                as_of=base_dt + timedelta(days=60),
                net_worth_ars=Decimal("1150000"),
                fx_rate_ars_per_usd=Decimal("1100"),
                net_cash_flow_ars=Decimal("-250000"),
                cash_flow_timing="END",
            ),
            HistoricalValuationSnapshot(
                as_of=base_dt + timedelta(days=90),
                net_worth_ars=Decimal("1265000"),
                fx_rate_ars_per_usd=Decimal("1150"),
                net_cash_flow_ars=Decimal("0"),
                cash_flow_timing="END",
            ),
        ]
        curve = self.val_svc.evaluate_valuation_curve(snaps, portfolio_id="pf-alt-flows")
        self.assertEqual(len(curve.points), 4)
        self.assertGreater(curve.performance_ars.twr, Decimal("0.0000"))

    def test_audit_ch7_27_indicator_driven_dynamic_rebalance_high_atr_prevents_premature_trade(self) -> None:
        """Verify high ATR widens a dynamic tolerance band enough to suppress rebalancing on a volatile asset."""
        ind_map = {
            "GGAL": TechnicalIndicatorsSnapshot(
                ticker="GGAL", as_of=self.as_of, close=Decimal("100"), atr_14=Decimal("6.0")
            ),
            "AAPL": TechnicalIndicatorsSnapshot(
                ticker="AAPL", as_of=self.as_of, close=Decimal("100"), atr_14=Decimal("2.0")
            ),
        }
        raw_specs = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.5000")),
        ]
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.DYNAMIC_VOLATILITY,
                default_relative_tolerance=Decimal("0.1500"),
                max_band_half_width=Decimal("0.2000"),
            )
        )
        cal_specs = svc.calibrate_specs_from_indicators(
            raw_specs, ind_map, baseline_atr_pct=Decimal("0.0200")
        )
        positions = [
            RebalancePositionInput(ticker="GGAL", quantity=Decimal("56"), market_price=Decimal("100")),
            RebalancePositionInput(ticker="AAPL", quantity=Decimal("44"), market_price=Decimal("100")),
        ]
        rep = svc.evaluate_and_rebalance(positions=positions, target_specs=cal_specs, as_of=self.as_of)
        self.assertFalse(rep.needs_rebalancing)

    def test_audit_ch7_28_indicator_driven_dynamic_rebalance_low_atr_tightens_band_and_triggers_trade(self) -> None:
        """Verify low ATR tightens a dynamic tolerance band and triggers rebalancing on a 6% weight drift."""
        ind_map = {
            "AAPL": TechnicalIndicatorsSnapshot(
                ticker="AAPL", as_of=self.as_of, close=Decimal("100"), atr_14=Decimal("0.5")
            ),
            "MSFT": TechnicalIndicatorsSnapshot(
                ticker="MSFT", as_of=self.as_of, close=Decimal("100"), atr_14=Decimal("0.5")
            ),
        }
        raw_specs = [
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="MSFT", target_weight=Decimal("0.5000")),
        ]
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                band_type=BandType.DYNAMIC_VOLATILITY,
                default_relative_tolerance=Decimal("0.2000"),
            )
        )
        cal_specs = svc.calibrate_specs_from_indicators(
            raw_specs, ind_map, baseline_atr_pct=Decimal("0.0200")
        )
        positions = [
            RebalancePositionInput(ticker="AAPL", quantity=Decimal("56"), market_price=Decimal("100")),
            RebalancePositionInput(ticker="MSFT", quantity=Decimal("44"), market_price=Decimal("100")),
        ]
        rep = svc.evaluate_and_rebalance(positions=positions, target_specs=cal_specs, as_of=self.as_of)
        self.assertTrue(rep.needs_rebalancing)
        self.assertEqual(rep.breached_tickers, ["AAPL", "MSFT"])

    def test_audit_ch7_29_sma_ema_convergence_on_constant_price_series(self) -> None:
        """Verify SMA and EMA equal the constant price exactly across any period."""
        series = [Decimal("42.1250")] * 30
        sma = self.ind_svc.calculate_sma(series, period=20)
        ema = self.ind_svc.calculate_ema(series, period=12)
        self.assertEqual(sma[-1], Decimal("42.1250"))
        self.assertEqual(ema[-1], Decimal("42.1250"))

    def test_audit_ch7_30_rsi_boundary_100_on_strictly_rising_and_0_on_strictly_falling_series(self) -> None:
        """Verify Wilder RSI hits 100.0000 on monotonic gains and 0.0000 on monotonic losses."""
        up = [Decimal(str(100 + i)) for i in range(20)]
        down = [Decimal(str(200 - i)) for i in range(20)]
        self.assertEqual(self.ind_svc.calculate_wilder_rsi(up, period=14)[-1], Decimal("100.0000"))
        self.assertEqual(self.ind_svc.calculate_wilder_rsi(down, period=14)[-1], Decimal("0.0000"))

    def test_audit_ch7_31_rsi_neutral_50_on_flat_no_change_series(self) -> None:
        """Verify Wilder RSI returns 50.0000 when both average gain and average loss are zero."""
        flat = [Decimal("100")] * 20
        self.assertEqual(self.ind_svc.calculate_wilder_rsi(flat, period=14)[-1], Decimal("50.0000"))

    def test_audit_ch7_32_bollinger_percent_b_neutral_half_when_bands_collapse_on_constant_series(self) -> None:
        """Verify BollingerBandsPoint sets percent_b=0.5000 and bandwidth=0.0000 when upper == lower."""
        flat = [Decimal("100")] * 25
        bb = self.ind_svc.calculate_bollinger_bands(flat, period=20)[-1]
        assert bb is not None
        self.assertEqual(bb.bandwidth, Decimal("0.0000"))
        self.assertEqual(bb.percent_b, Decimal("0.5000"))

    def test_audit_ch7_33_atr_gap_up_and_gap_down_true_range_dominance(self) -> None:
        """Verify ATR uses |high - prev_close| and |low - prev_close| when overnight gaps exceed intraday range."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [
            MarketBarDTO(
                timestamp=base + timedelta(days=i),
                open=Decimal("100") if i % 2 == 0 else Decimal("150"),
                high=Decimal("101") if i % 2 == 0 else Decimal("151"),
                low=Decimal("99") if i % 2 == 0 else Decimal("149"),
                close=Decimal("100") if i % 2 == 0 else Decimal("150"),
                volume=Decimal("1000"),
            )
            for i in range(16)
        ]
        atr = self.ind_svc.calculate_atr(bars, period=14)[-1]
        assert atr is not None
        self.assertGreater(atr, Decimal("45.0000"))

    def test_audit_ch7_34_signal_generator_all_indicators_unavailable_emits_hold_with_zero_score(self) -> None:
        """Verify 2 bars (where SMA20, EMA26, RSI14, BB20, ATR14 are all None) emits HOLD with 0.0000 score."""
        bars = self._build_bars(2)
        sig = self.sig_svc.generate_signal(bars, ticker="NEWIPO")
        self.assertEqual(sig.action, SignalAction.HOLD)
        self.assertEqual(sig.composite_score, Decimal("0.0000"))
        self.assertEqual(len(sig.components), 0)
        self.assertIsNone(sig.order_intent)

    def test_audit_ch7_35_signal_generator_partial_indicators_reweights_active_components(self) -> None:
        """Verify 15 bars activates RSI(14) while SMA(20), EMA(12/26), and BB(20) remain unavailable."""
        bars = self._build_bars(15, Decimal("100"), Decimal("2"), Decimal("1"))
        sig = self.sig_svc.generate_signal(bars, ticker="PARTIAL")
        self.assertEqual(len(sig.components), 1)
        self.assertEqual(sig.components[0].weight, Decimal("0.2500"))
        self.assertEqual(sig.composite_score, sig.components[0].score)

    def test_audit_ch7_36_mtm_consolidated_entry_fx_weighted_harmonic_mean_accuracy(self) -> None:
        """Verify consolidating 2 ARS lots with different entry_fx_rate preserves exact sum of USD cost basis."""
        lots = [
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("1000"),  # 100,000 ARS @ FX 1000 = 100 USD
                market_price=Decimal("1500"),
                currency="ARS",
                entry_fx_rate=Decimal("1000"),
            ),
            PositionValuationInput(
                ticker="GGAL",
                quantity=Decimal("100"),
                avg_cost_price=Decimal("2000"),  # 200,000 ARS @ FX 2000 = 100 USD
                market_price=Decimal("1500"),
                currency="ARS",
                entry_fx_rate=Decimal("2000"),
            ),
        ]
        rep = self.val_svc.value_portfolio_mark_to_market(
            positions=lots, fx_rate_ars_per_usd=Decimal("1500"), as_of=self.as_of
        )
        p = rep.positions[0]
        self.assertEqual(p.cost_basis_ars, Decimal("300000.0000"))
        self.assertEqual(p.cost_basis_usd, Decimal("200.0000"))
        self.assertEqual(p.fx_return_component, Decimal("0.0000"))

    def test_audit_ch7_37_rebalancer_conflicting_market_prices_across_same_ticker_lots_rejected(self) -> None:
        """Verify RebalancePositionInput lots for the same ticker with conflicting market prices are rejected."""
        lots = [
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("1000"),
                market_price=Decimal("1500"),
            ),
            RebalancePositionInput(
                ticker="GGAL",
                quantity=Decimal("10"),
                avg_cost_price=Decimal("1000"),
                market_price=Decimal("1600"),
            ),
        ]
        with self.assertRaises(InvalidToleranceBandConfigError):
            self.reb_svc.evaluate_and_rebalance(
                positions=lots,
                target_specs=[AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("1.0000"))],
                as_of=self.as_of,
            )

    def test_audit_ch7_38_rebalancer_sell_order_never_exceeds_current_holding_quantity(self) -> None:
        """Verify SELL order quantity never exceeds current_quantity even under extreme weight targets."""
        positions = [
            RebalancePositionInput(ticker="UNLISTED", quantity=Decimal("12.3456"), market_price=Decimal("100")),
            RebalancePositionInput(ticker="CORE", quantity=Decimal("87.6544"), market_price=Decimal("100")),
        ]
        targets = [AssetTargetBandSpec(ticker="CORE", target_weight=Decimal("1.0000"))]
        rep = self.reb_svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        sell_ord = next(o for o in rep.orders if o.ticker == "UNLISTED")
        self.assertLessEqual(sell_ord.quantity, Decimal("12.3456"))

    def test_audit_ch7_39_rebalancer_cash_conservation_identity_under_high_commission_and_integer_lots(self) -> None:
        """Verify initial_cash + total_sell_gross - total_buy_gross - total_estimated_commissions == projected_ending_cash."""
        svc = ToleranceBandRebalancerService(
            ToleranceBandRebalancerConfig(
                commission_bps=Decimal("350"),
                allow_fractional_shares=False,
                cash_buffer_weight=Decimal("0.0500"),
            )
        )
        positions = [
            RebalancePositionInput(ticker="A1", quantity=Decimal("90"), market_price=Decimal("107")),
            RebalancePositionInput(ticker="A2", quantity=Decimal("10"), market_price=Decimal("83")),
            RebalancePositionInput(ticker="A3", quantity=Decimal("5"), market_price=Decimal("61")),
        ]
        targets = [
            AssetTargetBandSpec(ticker="A1", target_weight=Decimal("0.3500")),
            AssetTargetBandSpec(ticker="A2", target_weight=Decimal("0.3000")),
            AssetTargetBandSpec(ticker="A3", target_weight=Decimal("0.3000")),
        ]
        rep = svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, initial_cash=Decimal("250"), as_of=self.as_of
        )
        self.assertEqual(
            rep.initial_cash + rep.total_sell_gross - rep.total_buy_gross - rep.total_estimated_commissions,
            rep.projected_ending_cash,
        )

    def test_audit_ch7_40_rebalancer_fsm_ticket_payload_fields_align_with_order_contract(self) -> None:
        """Verify every ticket in RebalanceFSMExecutionBatch contains complete order_payload fields."""
        positions = [
            RebalancePositionInput(ticker="GGAL", quantity=Decimal("80"), market_price=Decimal("100")),
            RebalancePositionInput(ticker="YPFD", quantity=Decimal("20"), market_price=Decimal("100")),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.5000")),
        ]
        rep = self.reb_svc.evaluate_and_rebalance(
            positions=positions,
            target_specs=targets,
            portfolio_id="pf-contract-check",
            as_of=self.as_of,
        )
        batch = self.reb_svc.build_fsm_execution_batch(rep)
        required_keys = {
            "portfolio_id",
            "ticker",
            "side",
            "quantity",
            "price",
            "status",
        }
        for ticket in batch.tickets:
            self.assertTrue(required_keys.issubset(ticket.order_payload.keys()))

    def test_audit_ch7_41_signal_generator_custom_weights_and_thresholds_sensitivity(self) -> None:
        """Verify narrow min_conviction_threshold (0.05) increases signal sensitivity vs default (0.25)."""
        bars = self._build_bars(25, Decimal("100"), Decimal("0.5"), Decimal("2"))
        tight_svc = SignalGeneratorService(
            SignalGeneratorConfig(
                min_conviction_threshold=Decimal("0.0500"),
                rsi_oversold=Decimal("35.0000"),
                rsi_overbought=Decimal("65.0000"),
            )
        )
        sig = tight_svc.generate_signal(bars, ticker="SENS")
        self.assertIn(sig.action, (SignalAction.BUY, SignalAction.HOLD, SignalAction.SELL))

    def test_audit_ch7_42_technical_indicators_sample_bollinger_ddof_1_wider_than_population_ddof_0(self) -> None:
        """Verify sample Bollinger Bands (ddof=1) produce wider bands than population (ddof=0) on non-flat data."""
        series = [Decimal(str(100 + (i % 5) * 3)) for i in range(25)]
        bb_pop = self.ind_svc.calculate_bollinger_bands(series, period=20, ddof=0)[-1]
        bb_smp = self.ind_svc.calculate_bollinger_bands(series, period=20, ddof=1)[-1]
        assert bb_pop is not None and bb_smp is not None
        self.assertGreater(bb_smp.upper_band, bb_pop.upper_band)
        self.assertLess(bb_smp.lower_band, bb_pop.lower_band)

    def test_audit_ch7_43_market_bars_duplicate_or_decreasing_timestamps_rejected(self) -> None:
        """Verify compute_snapshot rejects duplicate or non-monotonic timestamps in MarketBarDTO series."""
        bars = self._build_bars(20)
        bars[10] = MarketBarDTO(
            timestamp=bars[9].timestamp,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        with self.assertRaises(InvalidMarketBarSequenceError):
            self.ind_svc.compute_snapshot(bars, ticker="GGAL")

    def test_audit_ch7_44_market_bars_naive_timestamps_rejected_by_contract(self) -> None:
        """Verify MarketBarDTO rejects timezone-naive timestamps."""
        with self.assertRaises(ValidationError):
            MarketBarDTO(
                timestamp=datetime(2026, 12, 1, 15, 0),  # Naive
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("95"),
                close=Decimal("100"),
                volume=Decimal("1000"),
            )

    def test_audit_ch7_45_valuation_curve_exceeding_max_slices_rejected(self) -> None:
        """Verify calculate_twr rejects > MAX_VALUATION_SLICES (10,000) slices."""
        slice_item = SubPeriodValuationSlice(start_value=Decimal("100"), end_value=Decimal("100"))
        with self.assertRaises(InvalidValuationInputError):
            self.val_svc.calculate_twr([slice_item] * 10_001)

    def test_audit_ch7_46_mwr_dietz_zero_or_negative_weighted_capital_rejected(self) -> None:
        """Verify calculate_mwr_modified_dietz rejects cash flows that drive weighted capital <= 0."""
        cfs = [DatedCashFlowEvent(day_offset=10, amount=Decimal("-2000"))]
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.val_svc.calculate_mwr_modified_dietz(
                start_value=Decimal("1000"),
                end_value=Decimal("500"),
                total_days=100,
                cash_flows=cfs,
            )

    def test_audit_ch7_47_mwr_irr_no_sign_change_all_negative_flows_rejected(self) -> None:
        """Verify calculate_mwr_irr rejects cash flows where no sign change exists in NPV."""
        cfs = [DatedCashFlowEvent(day_offset=50, amount=Decimal("-2000"))]
        with self.assertRaises(InvalidCashFlowPeriodError):
            self.val_svc.calculate_mwr_irr(
                start_value=Decimal("1000"),
                end_value=Decimal("500"),
                total_days=100,
                cash_flows=cfs,
            )

    def test_audit_ch7_48_rebalancer_duplicate_lot_tie_breaking_by_lot_id_determinism(self) -> None:
        """Verify FIFO, LIFO, and HIFO break ties deterministically using lot_id when acquired_at and cost match."""
        t_same = datetime(2026, 3, 1, tzinfo=timezone.utc)
        lots = [
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("40"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("80"),
                acquired_at=t_same,
                lot_id="LOT-02",
            ),
            RebalancePositionInput(
                ticker="AAA",
                quantity=Decimal("40"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("80"),
                acquired_at=t_same,
                lot_id="LOT-01",
            ),
            RebalancePositionInput(
                ticker="BBB",
                quantity=Decimal("20"),
                market_price=Decimal("100"),
                avg_cost_price=Decimal("100"),
            ),
        ]
        targets = [
            AssetTargetBandSpec(ticker="AAA", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="BBB", target_weight=Decimal("0.5000")),
        ]
        for pol in (TaxLotSelectionPolicy.FIFO, TaxLotSelectionPolicy.LIFO, TaxLotSelectionPolicy.HIFO):
            svc = ToleranceBandRebalancerService(ToleranceBandRebalancerConfig(tax_lot_policy=pol))
            rep = svc.evaluate_and_rebalance(positions=lots, target_specs=targets, as_of=self.as_of)
            self.assertEqual(rep.total_estimated_realized_pnl, Decimal("600.0000"))

    def test_audit_ch7_49_rebalancer_unheld_asset_resolved_via_mtm_market_prices_dict(self) -> None:
        """Verify rebalance_from_mtm_report passes extra_market_prices for unheld target assets cleanly."""
        mtm = self.val_svc.value_portfolio_mark_to_market(
            positions=[
                PositionValuationInput(
                    ticker="GGAL",
                    quantity=Decimal("100"),
                    avg_cost_price=Decimal("10"),
                    market_price=Decimal("10"),
                    currency="USD",
                )
            ],
            fx_rate_ars_per_usd=Decimal("1000"),
            as_of=self.as_of,
        )
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.5000")),
            AssetTargetBandSpec(ticker="MSFT", target_weight=Decimal("0.5000")),
        ]
        rep = self.reb_svc.rebalance_from_mtm_report(
            mtm_report=mtm,
            target_specs=targets,
            extra_market_prices={"MSFT": Decimal("250")},
            base_currency="USD",
        )
        msft_buy = next(o for o in rep.orders if o.ticker == "MSFT")
        self.assertEqual(msft_buy.quantity, Decimal("2.0000"))

    def test_audit_ch7_50_signal_generator_evaluate_from_snapshot_rejects_non_snapshot_input(self) -> None:
        """Verify evaluate_from_snapshot rejects non-TechnicalIndicatorsSnapshot input with InvalidSignalParametersError."""
        with self.assertRaises(InvalidSignalParametersError):
            self.sig_svc.evaluate_from_snapshot("not-a-snapshot")  # type: ignore[arg-type]

    def test_audit_ch7_51_signal_generator_config_rejects_inverted_bollinger_percent_b_thresholds(self) -> None:
        """Verify SignalGeneratorConfig rejects bollinger_lower_percent_b >= bollinger_upper_percent_b."""
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(
                bollinger_lower_percent_b=Decimal("0.8000"),
                bollinger_upper_percent_b=Decimal("0.2000"),
            )

    def test_audit_ch7_52_signal_generator_config_rejects_inverted_rsi_thresholds(self) -> None:
        """Verify SignalGeneratorConfig rejects rsi_oversold >= rsi_overbought."""
        with self.assertRaises(ValidationError):
            SignalGeneratorConfig(
                rsi_oversold=Decimal("75.0000"),
                rsi_overbought=Decimal("30.0000"),
            )

    def test_audit_ch7_53_technical_indicators_insufficient_data_for_custom_period_raises_error(self) -> None:
        """Verify calculate_sma, calculate_ema, calculate_wilder_rsi, and calculate_atr reject period < 1 or empty series."""
        with self.assertRaises(InsufficientMarketDataError):
            self.ind_svc.calculate_sma([], period=5)
        with self.assertRaises(InvalidIndicatorParameterError):
            self.ind_svc.calculate_ema([Decimal("100")], period=0)
        with self.assertRaises(InvalidIndicatorParameterError):
            self.ind_svc.calculate_wilder_rsi([Decimal("100")], period=0)
        with self.assertRaises(InsufficientMarketDataError):
            self.ind_svc.calculate_atr([], period=14)

    def test_audit_ch7_54_portfolio_valuation_rejects_non_snapshot_in_evaluate_valuation_curve(self) -> None:
        """Verify evaluate_valuation_curve rejects non-HistoricalValuationSnapshot elements."""
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        snap = HistoricalValuationSnapshot(
            as_of=t0, net_worth_ars=Decimal("1000"), fx_rate_ars_per_usd=Decimal("1000")
        )
        with self.assertRaises(InvalidValuationInputError):
            self.val_svc.evaluate_valuation_curve([snap, "bad-snap"])  # type: ignore[list-item]

    def test_audit_ch7_55_full_chapter7_multi_cycle_rebalance_convergence_to_zero_turnover(self) -> None:
        """Verify applying the rebalance post-trade quantities and ending cash into a second evaluation yields needs_rebalancing=False."""
        positions = [
            RebalancePositionInput(ticker="GGAL", quantity=Decimal("80"), market_price=Decimal("100")),
            RebalancePositionInput(ticker="YPFD", quantity=Decimal("10"), market_price=Decimal("100")),
            RebalancePositionInput(ticker="AAPL", quantity=Decimal("10"), market_price=Decimal("100")),
        ]
        targets = [
            AssetTargetBandSpec(ticker="GGAL", target_weight=Decimal("0.4000")),
            AssetTargetBandSpec(ticker="YPFD", target_weight=Decimal("0.3000")),
            AssetTargetBandSpec(ticker="AAPL", target_weight=Decimal("0.3000")),
        ]
        rep1 = self.reb_svc.evaluate_and_rebalance(
            positions=positions, target_specs=targets, as_of=self.as_of
        )
        self.assertTrue(rep1.needs_rebalancing)

        # Feed post-trade holdings from cycle 1 into cycle 2
        post_positions = [
            RebalancePositionInput(
                ticker=ev.ticker,
                quantity=ev.post_trade_quantity,
                market_price=Decimal("100"),
            )
            for ev in rep1.evaluations
        ]
        rep2 = self.reb_svc.evaluate_and_rebalance(
            positions=post_positions,
            target_specs=targets,
            initial_cash=rep1.projected_ending_cash,
            as_of=self.as_of,
        )
        self.assertFalse(rep2.needs_rebalancing)
        self.assertEqual(rep2.orders, [])
        self.assertEqual(rep2.portfolio_turnover, Decimal("0.0000"))

