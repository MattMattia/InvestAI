"""
Unit test suite for Module 6.2 (Phases 2 & 3): Accounting Integrity Service,
EPS <= 0 Indeterminate Labeling, Dual-Currency Fundamental Valuation, and
Stress Testing on Negative Net Worth, Operating-Loss Startups, and Delisted Assets.
"""
from __future__ import annotations

from decimal import Decimal
import unittest

from pydantic import ValidationError
import pytest

from app.domain.services.accounting_integrity import (
    AccountingIntegrityService,
    AccountingRiskFlag,
    FundamentalInputs,
    RatioStatus,
    RatioValue,
)
from app.domain.services.ingestion.base_parser import RawHoldingRecord
from app.domain.services.ingestion.data_cleaning_pipeline import DataCleaningPipeline


@pytest.mark.unit
class TestAccountingIntegrity(unittest.TestCase):
    """Comprehensive unit tests for AccountingIntegrityService and ratio contracts."""

    def setUp(self) -> None:
        self.service = AccountingIntegrityService()

    def test_healthy_company_all_ratios_valid(self) -> None:
        """
        Verify a healthy balance sheet produces all fundamental ratios with
        status=VALID quantized to 4 decimal places and zero anomaly flags.
        """
        inputs = FundamentalInputs(
            ticker="  ypfd ",
            price=Decimal("30000"),
            eps=Decimal("2500"),
            bvps=Decimal("15000"),
            eps_growth_pct=Decimal("15"),
            dividends_per_share=Decimal("900"),
            net_income=Decimal("1000000"),
            shareholders_equity=Decimal("5000000"),
            price_currency="ARS",
            financials_currency="ARS",
        )
        report = self.service.evaluate_company_metrics(inputs)

        self.assertEqual(report.ticker, "YPFD")
        self.assertFalse(report.has_accounting_anomalies)
        self.assertEqual(report.risk_flags, [])
        self.assertEqual(report.warnings, [])

        # P/E = 30000 / 2500 = 12.0000
        self.assertEqual(report.pe_ratio.status, RatioStatus.VALID)
        self.assertEqual(report.pe_ratio.value, Decimal("12.0000"))

        # P/B = 30000 / 15000 = 2.0000
        self.assertEqual(report.pb_ratio.status, RatioStatus.VALID)
        self.assertEqual(report.pb_ratio.value, Decimal("2.0000"))

        # PEG = 12.0000 / 15 = 0.8000
        self.assertEqual(report.peg_ratio.status, RatioStatus.VALID)
        self.assertEqual(report.peg_ratio.value, Decimal("0.8000"))

        # Dividend Yield = 900 / 30000 = 0.0300
        self.assertEqual(report.dividend_yield.status, RatioStatus.VALID)
        self.assertEqual(report.dividend_yield.value, Decimal("0.0300"))

        # ROE = 1000000 / 5000000 = 0.2000
        self.assertEqual(report.roe.status, RatioStatus.VALID)
        self.assertEqual(report.roe.value, Decimal("0.2000"))

    def test_zero_and_negative_eps_marks_pe_and_peg_indeterminate(self) -> None:
        """
        Verify field directive: EPS == 0 and EPS < 0 deterministically label
        both P/E and PEG as INDETERMINATE without division-by-zero errors.
        """
        zero_eps_inputs = FundamentalInputs(
            ticker="COME",
            price=Decimal("250"),
            eps=Decimal("0"),
            bvps=Decimal("100"),
            eps_growth_pct=Decimal("20"),
            price_currency="ARS",
            financials_currency="ARS",
        )
        zero_report = self.service.evaluate_company_metrics(zero_eps_inputs)
        self.assertTrue(zero_report.has_accounting_anomalies)
        self.assertEqual(zero_report.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(zero_report.pe_ratio.value)
        self.assertEqual(zero_report.peg_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(zero_report.peg_ratio.value)
        self.assertIn(AccountingRiskFlag.ZERO_EARNINGS, zero_report.risk_flags)

        neg_eps_inputs = FundamentalInputs(
            ticker="GLOB",
            price=Decimal("180"),
            eps=Decimal("-4.50"),
            bvps=Decimal("45"),
            eps_growth_pct=Decimal("25"),
            price_currency="USD",
            financials_currency="USD",
        )
        neg_report = self.service.evaluate_company_metrics(neg_eps_inputs)
        self.assertTrue(neg_report.has_accounting_anomalies)
        self.assertEqual(neg_report.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(neg_report.pe_ratio.value)
        self.assertEqual(neg_report.peg_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(neg_report.peg_ratio.value)
        self.assertIn(AccountingRiskFlag.NEGATIVE_EARNINGS, neg_report.risk_flags)
        self.assertEqual(neg_report.pb_ratio.status, RatioStatus.VALID)
        self.assertEqual(neg_report.pb_ratio.value, Decimal("4.0000"))

    def test_negative_book_value_marks_pb_and_roe_indeterminate(self) -> None:
        """
        Verify BVPS <= 0 and shareholders_equity <= 0 mark P/B and ROE as
        INDETERMINATE, preventing the false-positive ROE trap when both net income
        and equity are negative.
        """
        distressed_inputs = FundamentalInputs(
            ticker="DIST",
            price=Decimal("50"),
            eps=Decimal("-10"),
            bvps=Decimal("-25"),
            net_income=Decimal("-500000"),
            shareholders_equity=Decimal("-1000000"),
            price_currency="USD",
            financials_currency="USD",
        )
        report = self.service.evaluate_company_metrics(distressed_inputs)

        self.assertTrue(report.has_accounting_anomalies)
        self.assertEqual(report.pb_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(report.pb_ratio.value)
        self.assertEqual(report.roe.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(report.roe.value)
        self.assertIn(AccountingRiskFlag.NEGATIVE_BOOK_VALUE, report.risk_flags)
        self.assertIn(AccountingRiskFlag.NEGATIVE_EARNINGS, report.risk_flags)

    def test_extreme_pe_near_zero_eps_and_overflow_guard(self) -> None:
        """
        Verify near-zero positive EPS (e.g. 0.001 with price 500 -> P/E = 500,000)
        flags EXTREME_PE_OUTLIER, and infinitesimal EPS (1e-25) returns INDETERMINATE
        without raising decimal.InvalidOperation.
        """
        micro_eps_inputs = FundamentalInputs(
            ticker="MICRO",
            price=Decimal("500"),
            eps=Decimal("0.001"),
            price_currency="USD",
            financials_currency="USD",
        )
        micro_report = self.service.evaluate_company_metrics(micro_eps_inputs)
        self.assertEqual(micro_report.pe_ratio.status, RatioStatus.VALID)
        self.assertEqual(micro_report.pe_ratio.value, Decimal("500000.0000"))
        self.assertIn(AccountingRiskFlag.EXTREME_PE_OUTLIER, micro_report.risk_flags)

        infinitesimal_inputs = FundamentalInputs(
            ticker="TINY",
            price=Decimal("500"),
            eps=Decimal("1e-25"),
            price_currency="USD",
            financials_currency="USD",
        )
        tiny_report = self.service.evaluate_company_metrics(infinitesimal_inputs)
        self.assertEqual(tiny_report.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(tiny_report.pe_ratio.value)
        self.assertIn(AccountingRiskFlag.EXTREME_PE_OUTLIER, tiny_report.risk_flags)

    def test_currency_mismatch_and_cedear_conversion_ratio(self) -> None:
        """
        Verify ARS/USD currency mismatch without fx_rate marks price ratios INDETERMINATE
        with CURRENCY_MISMATCH, whereas supplying fx_rate and conversion_ratio
        computes exact homogenized CEDEAR/ADR multiples.
        """
        mismatch_no_fx = FundamentalInputs(
            ticker="AAPL",
            price=Decimal("24000"),
            eps=Decimal("6.00"),
            price_currency="ARS",
            financials_currency="USD",
            fx_rate=None,
            conversion_ratio=Decimal("10"),
        )
        mismatch_report = self.service.evaluate_company_metrics(mismatch_no_fx)
        self.assertEqual(mismatch_report.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIn(AccountingRiskFlag.CURRENCY_MISMATCH, mismatch_report.risk_flags)

        # CEDEAR price = 24,000 ARS, ratio 10:1 -> underlying = 240,000 ARS
        # At fx_rate = 1,200 ARS/USD -> effective USD price = 200 USD
        # With EPS = 8.00 USD -> P/E = 200 / 8 = 25.0000
        cedear_inputs = FundamentalInputs(
            ticker="AAPL",
            price=Decimal("24000"),
            eps=Decimal("8.00"),
            bvps=Decimal("4.00"),
            price_currency="ARS",
            financials_currency="USD",
            fx_rate=Decimal("1200"),
            conversion_ratio=Decimal("10"),
        )
        cedear_report = self.service.evaluate_company_metrics(cedear_inputs)
        self.assertFalse(cedear_report.has_accounting_anomalies)
        self.assertEqual(cedear_report.pe_ratio.status, RatioStatus.VALID)
        self.assertEqual(cedear_report.pe_ratio.value, Decimal("25.0000"))
        self.assertEqual(cedear_report.pb_ratio.status, RatioStatus.VALID)
        self.assertEqual(cedear_report.pb_ratio.value, Decimal("50.0000"))

    def test_delisted_asset_and_boolean_input_rejection(self) -> None:
        """
        Verify delisted or non-positive price assets mark price-based ratios as
        INDETERMINATE with DELISTED_OR_INVALID_PRICE, and boolean inputs on Decimal
        fields are rejected by Pydantic validation.
        """
        delisted_inputs = FundamentalInputs(
            ticker="DELIST",
            price=Decimal("100"),
            eps=Decimal("10"),
            bvps=Decimal("50"),
            dividends_per_share=Decimal("2"),
            is_delisted=True,
        )
        reports = self.service.evaluate_portfolio_fundamentals([delisted_inputs])
        self.assertEqual(len(reports), 1)
        rep = reports[0]
        self.assertEqual(rep.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertEqual(rep.pb_ratio.status, RatioStatus.INDETERMINATE)
        self.assertEqual(rep.peg_ratio.status, RatioStatus.INDETERMINATE)
        self.assertEqual(rep.dividend_yield.status, RatioStatus.INDETERMINATE)
        self.assertIn(
            AccountingRiskFlag.DELISTED_OR_INVALID_PRICE, rep.risk_flags
        )

        with self.assertRaises(ValidationError):
            FundamentalInputs(ticker="GGAL", price=True)  # type: ignore[arg-type]

        with self.assertRaises(ValidationError):
            FundamentalInputs(ticker="GGAL", eps=False)  # type: ignore[arg-type]

        with self.assertRaises(ValidationError):
            RatioValue(value=Decimal("10"), status=RatioStatus.INDETERMINATE)

        with self.assertRaises(ValidationError):
            RatioValue(value=None, status=RatioStatus.VALID)

    def test_stress_distressed_negative_net_worth_and_value_trap_dividend(self) -> None:
        """
        Stress Scenario A (Technical Insolvency / Negative Net Worth) &
        Scenario B (Value Trap / Dividend paid despite negative EPS and negative BVPS).
        """
        # Scenario A: Technical insolvency with negative earnings, equity, and growth
        insolvent_inputs = FundamentalInputs(
            ticker="INSOLV",
            price=Decimal("42.00"),
            eps=Decimal("-8.75"),
            bvps=Decimal("-14.20"),
            eps_growth_pct=Decimal("-30.0"),
            dividends_per_share=Decimal("0"),
            net_income=Decimal("-12000000"),
            shareholders_equity=Decimal("-40000000"),
            price_currency="USD",
            financials_currency="USD",
        )
        rep_a = self.service.evaluate_company_metrics(insolvent_inputs)
        self.assertTrue(rep_a.has_accounting_anomalies)
        self.assertEqual(rep_a.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(rep_a.pe_ratio.value)
        self.assertEqual(rep_a.pb_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(rep_a.pb_ratio.value)
        self.assertEqual(rep_a.peg_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(rep_a.peg_ratio.value)
        # Blocks false-positive ROE (-12M / -40M = +0.30)
        self.assertEqual(rep_a.roe.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(rep_a.roe.value)
        # Zero dividend is valid (0.0000)
        self.assertEqual(rep_a.dividend_yield.status, RatioStatus.VALID)
        self.assertEqual(rep_a.dividend_yield.value, Decimal("0.0000"))
        self.assertIn(AccountingRiskFlag.NEGATIVE_EARNINGS, rep_a.risk_flags)
        self.assertIn(AccountingRiskFlag.NEGATIVE_BOOK_VALUE, rep_a.risk_flags)

        # Scenario B: Value Trap (uncovered dividend paid while EPS < 0 and BVPS < 0)
        value_trap_inputs = FundamentalInputs(
            ticker="VTRAP",
            price=Decimal("100.00"),
            eps=Decimal("-3.50"),
            bvps=Decimal("-1.20"),
            dividends_per_share=Decimal("5.00"),
            price_currency="USD",
            financials_currency="USD",
        )
        rep_b = self.service.evaluate_company_metrics(value_trap_inputs)
        self.assertTrue(rep_b.has_accounting_anomalies)
        self.assertEqual(rep_b.dividend_yield.status, RatioStatus.VALID)
        self.assertEqual(rep_b.dividend_yield.value, Decimal("0.0500"))
        self.assertEqual(rep_b.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(rep_b.pe_ratio.value)
        self.assertEqual(rep_b.pb_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(rep_b.pb_ratio.value)
        self.assertIn(AccountingRiskFlag.NEGATIVE_EARNINGS, rep_b.risk_flags)
        self.assertIn(AccountingRiskFlag.NEGATIVE_BOOK_VALUE, rep_b.risk_flags)

    def test_stress_early_stage_startup_operating_losses_high_growth(self) -> None:
        """
        Stress test an early-stage growth startup with operating losses (EPS < 0,
        Net Income < 0), positive book equity, and high projected EPS growth (65%).
        Verifies P/E and PEG remain INDETERMINATE while P/B and negative ROE are VALID.
        """
        startup_inputs = FundamentalInputs(
            ticker="STRT",
            price=Decimal("50.00"),
            eps=Decimal("-2.15"),
            bvps=Decimal("12.50"),
            eps_growth_pct=Decimal("65.0"),
            dividends_per_share=Decimal("0"),
            net_income=Decimal("-15000000"),
            shareholders_equity=Decimal("85000000"),
            price_currency="USD",
            financials_currency="USD",
        )
        report = self.service.evaluate_company_metrics(startup_inputs)

        self.assertTrue(report.has_accounting_anomalies)
        self.assertIn(AccountingRiskFlag.NEGATIVE_EARNINGS, report.risk_flags)
        self.assertNotIn(AccountingRiskFlag.NEGATIVE_BOOK_VALUE, report.risk_flags)

        # High projected growth cannot rescue PEG when base P/E is indeterminate
        self.assertEqual(report.pe_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(report.pe_ratio.value)
        self.assertEqual(report.peg_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(report.peg_ratio.value)

        # P/B = 50.00 / 12.50 = 4.0000
        self.assertEqual(report.pb_ratio.status, RatioStatus.VALID)
        self.assertEqual(report.pb_ratio.value, Decimal("4.0000"))

        # ROE = -15,000,000 / 85,000,000 = -0.1764705... -> -0.1765
        self.assertEqual(report.roe.status, RatioStatus.VALID)
        self.assertEqual(report.roe.value, Decimal("-0.1765"))

    def test_stress_delisted_suspended_and_invalid_price_matrix(self) -> None:
        """
        Evaluate instruments across pathological quotation states:
        (a) is_delisted=True with historical positive price,
        (b) is_delisted=False with price=None (suspended/unquoted),
        (c) is_delisted=False with price=0 and price=-15.0.
        All price-based multiples must be INDETERMINATE with DELISTED_OR_INVALID_PRICE,
        while accounting ROE is still evaluated from balance sheet figures.
        """
        cases = [
            FundamentalInputs(
                ticker="DEL1",
                price=Decimal("125.00"),
                eps=Decimal("5.00"),
                bvps=Decimal("25.00"),
                eps_growth_pct=Decimal("10.0"),
                dividends_per_share=Decimal("1.50"),
                net_income=Decimal("100000"),
                shareholders_equity=Decimal("500000"),
                is_delisted=True,
            ),
            FundamentalInputs(
                ticker="SUSP",
                price=None,
                eps=Decimal("5.00"),
                bvps=Decimal("25.00"),
                eps_growth_pct=Decimal("10.0"),
                dividends_per_share=Decimal("1.50"),
                net_income=Decimal("100000"),
                shareholders_equity=Decimal("500000"),
                is_delisted=False,
            ),
            FundamentalInputs(
                ticker="ZPRC",
                price=Decimal("0"),
                eps=Decimal("5.00"),
                bvps=Decimal("25.00"),
                eps_growth_pct=Decimal("10.0"),
                dividends_per_share=Decimal("1.50"),
                net_income=Decimal("100000"),
                shareholders_equity=Decimal("500000"),
                is_delisted=False,
            ),
            FundamentalInputs(
                ticker="NPRC",
                price=Decimal("-15.0"),
                eps=Decimal("5.00"),
                bvps=Decimal("25.00"),
                eps_growth_pct=Decimal("10.0"),
                dividends_per_share=Decimal("1.50"),
                net_income=Decimal("100000"),
                shareholders_equity=Decimal("500000"),
                is_delisted=False,
            ),
        ]

        for item in cases:
            rep = self.service.evaluate_company_metrics(item)
            self.assertEqual(rep.pe_ratio.status, RatioStatus.INDETERMINATE)
            self.assertIsNone(rep.pe_ratio.value)
            self.assertEqual(rep.pb_ratio.status, RatioStatus.INDETERMINATE)
            self.assertIsNone(rep.pb_ratio.value)
            self.assertEqual(rep.peg_ratio.status, RatioStatus.INDETERMINATE)
            self.assertIsNone(rep.peg_ratio.value)
            self.assertEqual(rep.dividend_yield.status, RatioStatus.INDETERMINATE)
            self.assertIsNone(rep.dividend_yield.value)
            self.assertIn(
                AccountingRiskFlag.DELISTED_OR_INVALID_PRICE, rep.risk_flags
            )
            # Accounting ROE remains valid (100,000 / 500,000 = 0.2000)
            self.assertEqual(rep.roe.status, RatioStatus.VALID)
            self.assertEqual(rep.roe.value, Decimal("0.2000"))

    def test_stress_bimonetary_bidirectional_conversion_and_invalid_fx(self) -> None:
        """
        Verify bidirectional ARS <-> USD currency homogenization and invalid FX handling:
        - Case A (ARS price -> USD financials): 15,000 ARS * 5 / 1250 = 60 USD -> P/E = 24.0000.
        - Case B (USD price -> ARS financials): 12 USD * 1250 = 15,000 ARS -> P/E = 5.0000, P/B = 1.0000.
        - Case C (Invalid FX <= 0 or None on mismatch): INDETERMINATE with CURRENCY_MISMATCH.
        """
        # Case A: ARS price -> USD financials
        case_a = FundamentalInputs(
            ticker="NVDA",
            price=Decimal("15000"),
            eps=Decimal("2.50"),
            price_currency="ARS",
            financials_currency="USD",
            conversion_ratio=Decimal("5"),
            fx_rate=Decimal("1250"),
        )
        rep_a = self.service.evaluate_company_metrics(case_a)
        self.assertFalse(rep_a.has_accounting_anomalies)
        self.assertEqual(rep_a.pe_ratio.status, RatioStatus.VALID)
        self.assertEqual(rep_a.pe_ratio.value, Decimal("24.0000"))

        # Case B: USD price -> ARS financials
        case_b = FundamentalInputs(
            ticker="ALUA",
            price=Decimal("12.00"),
            eps=Decimal("3000.00"),
            bvps=Decimal("15000.00"),
            price_currency="USD",
            financials_currency="ARS",
            fx_rate=Decimal("1250"),
        )
        rep_b = self.service.evaluate_company_metrics(case_b)
        self.assertFalse(rep_b.has_accounting_anomalies)
        self.assertEqual(rep_b.pe_ratio.status, RatioStatus.VALID)
        self.assertEqual(rep_b.pe_ratio.value, Decimal("5.0000"))
        self.assertEqual(rep_b.pb_ratio.status, RatioStatus.VALID)
        self.assertEqual(rep_b.pb_ratio.value, Decimal("1.0000"))

        # Case C: Invalid FX rates (0, negative, None) when currencies mismatch
        for bad_fx in (None, Decimal("0"), Decimal("-1150.50")):
            bad_fx_inputs = FundamentalInputs(
                ticker="BMA",
                price=Decimal("6500"),
                eps=Decimal("4.00"),
                price_currency="ARS",
                financials_currency="USD",
                fx_rate=bad_fx,
            )
            rep_c = self.service.evaluate_company_metrics(bad_fx_inputs)
            self.assertEqual(rep_c.pe_ratio.status, RatioStatus.INDETERMINATE)
            self.assertIsNone(rep_c.pe_ratio.value)
            self.assertIn(AccountingRiskFlag.CURRENCY_MISMATCH, rep_c.risk_flags)

    def test_stress_exact_zero_variants_negative_zero_and_near_zero_overflows(
        self,
    ) -> None:
        """
        Test multiple Decimal zero representations ('0', '0.0000', '-0.00'),
        elimination of negative zero ('-0.0000' -> '0.0000'), microscopic
        denominator overflows (1e-25) across P/B, PEG, and ROE, and control
        character rejection in ticker.
        """
        for zero_val in (Decimal("0"), Decimal("0.0000"), Decimal("-0.00")):
            zero_inputs = FundamentalInputs(
                ticker="ZERO",
                price=Decimal("100"),
                eps=zero_val,
                bvps=zero_val,
                eps_growth_pct=zero_val,
                dividends_per_share=zero_val,
                net_income=zero_val,
                shareholders_equity=zero_val,
            )
            rep = self.service.evaluate_company_metrics(zero_inputs)
            self.assertEqual(rep.pe_ratio.status, RatioStatus.INDETERMINATE)
            self.assertEqual(rep.pb_ratio.status, RatioStatus.INDETERMINATE)
            self.assertEqual(rep.peg_ratio.status, RatioStatus.INDETERMINATE)
            self.assertEqual(rep.roe.status, RatioStatus.INDETERMINATE)
            self.assertEqual(rep.dividend_yield.status, RatioStatus.VALID)
            self.assertEqual(str(rep.dividend_yield.value), "0.0000")

        # Verify negative zero in numerator with positive equity normalizes to "0.0000"
        neg_zero_roe_inputs = FundamentalInputs(
            ticker="NZERO",
            price=Decimal("100"),
            eps=Decimal("10"),
            net_income=Decimal("-0.00"),
            shareholders_equity=Decimal("1000"),
        )
        nz_rep = self.service.evaluate_company_metrics(neg_zero_roe_inputs)
        self.assertEqual(nz_rep.roe.status, RatioStatus.VALID)
        self.assertEqual(nz_rep.roe.value, Decimal("0.0000"))
        self.assertEqual(str(nz_rep.roe.value), "0.0000")
        self.assertIn(AccountingRiskFlag.ZERO_EARNINGS, nz_rep.risk_flags)

        # Microscopic denominators (1e-25) exceeding MAX_COMPUTABLE_RATIO
        micro_denom_inputs = FundamentalInputs(
            ticker="OVFL",
            price=Decimal("500"),
            eps=Decimal("10"),
            bvps=Decimal("1e-25"),
            eps_growth_pct=Decimal("1e-25"),
            net_income=Decimal("1000"),
            shareholders_equity=Decimal("1e-25"),
        )
        ovfl_rep = self.service.evaluate_company_metrics(micro_denom_inputs)
        self.assertEqual(ovfl_rep.pb_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(ovfl_rep.pb_ratio.value)
        self.assertEqual(ovfl_rep.peg_ratio.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(ovfl_rep.peg_ratio.value)
        self.assertEqual(ovfl_rep.roe.status, RatioStatus.INDETERMINATE)
        self.assertIsNone(ovfl_rep.roe.value)

        # Reject control characters in ticker
        for bad_ticker in ("GGAL\n", "YPFD\r", "PAMP\t", "AL30\x00"):
            with self.assertRaises(ValidationError):
                FundamentalInputs(ticker=bad_ticker, price=Decimal("100"))

    def test_stress_end_to_end_pipeline_and_portfolio_anomaly_summary(self) -> None:
        """
        End-to-end integration of Module 6.2:
        1. Clean a batch of RawHoldingRecord items via DataCleaningPipeline.clean_records().
        2. Evaluate portfolio fundamentals for the valid cleaned holdings via
           AccountingIntegrityService.evaluate_portfolio_fundamentals().
        3. Verify summarize_portfolio_anomalies() isolates only tickers with anomalies.
        """
        raw_records = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="YPFD.BA",
                raw_quantity="150",
                raw_avg_price="$ 28.500,00",
                raw_currency="Pesos Argentinos",
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="COME.BA",
                raw_quantity="1.000",
                raw_avg_price="$ 240,50",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=4,
                raw_ticker="GLOB",
                raw_quantity="25",
                raw_avg_price="U$S 180.00",
                raw_currency="Dólar MEP",
            ),
            RawHoldingRecord(
                row_number=5,
                raw_ticker="BAD_ROW",
                raw_quantity="-50",
                raw_avg_price="100",
                raw_currency="ARS",
            ),
        ]

        pipeline = DataCleaningPipeline(keep_ba_suffix=False)
        cleaned_result = pipeline.clean_records(raw_records)

        self.assertEqual(cleaned_result.total_valid, 3)
        self.assertEqual(cleaned_result.total_invalid, 1)

        # Map fundamental balance-sheet snapshots keyed by normalized ticker
        fundamentals_catalog: dict[str, dict[str, Decimal]] = {
            "YPFD": {
                "price": Decimal("30000"),
                "eps": Decimal("2500"),
                "bvps": Decimal("15000"),
                "eps_growth_pct": Decimal("15"),
                "net_income": Decimal("1000000"),
                "shareholders_equity": Decimal("5000000"),
            },
            "COME": {
                "price": Decimal("250"),
                "eps": Decimal("0"),
                "bvps": Decimal("125"),
                "eps_growth_pct": Decimal("10"),
                "net_income": Decimal("0"),
                "shareholders_equity": Decimal("250000"),
            },
            "GLOB": {
                "price": Decimal("180"),
                "eps": Decimal("-4.50"),
                "bvps": Decimal("-10.00"),
                "eps_growth_pct": Decimal("-5.0"),
                "net_income": Decimal("-50000"),
                "shareholders_equity": Decimal("-200000"),
            },
        }

        fundamental_inputs = [
            FundamentalInputs(
                ticker=holding.ticker,
                price_currency=holding.currency,
                financials_currency=holding.currency,
                **fundamentals_catalog[holding.ticker],
            )
            for holding in cleaned_result.valid_records
        ]

        reports = self.service.evaluate_portfolio_fundamentals(fundamental_inputs)
        self.assertEqual(len(reports), 3)

        anomaly_summary = self.service.summarize_portfolio_anomalies(reports)

        # YPFD is healthy and must be excluded from anomaly_summary
        self.assertNotIn("YPFD", anomaly_summary)
        self.assertEqual( set(anomaly_summary.keys()), {"COME", "GLOB"})
        self.assertEqual(
            anomaly_summary["COME"],
            [AccountingRiskFlag.ZERO_EARNINGS],
        )
        self.assertIn(AccountingRiskFlag.NEGATIVE_EARNINGS, anomaly_summary["GLOB"])
        self.assertIn(AccountingRiskFlag.NEGATIVE_BOOK_VALUE, anomaly_summary["GLOB"])


