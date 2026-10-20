"""
Unit test suite for Module 6.2 Phase 2: Accounting Integrity Service,
EPS <= 0 Indeterminate Labeling, and Dual-Currency Fundamental Valuation.
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

