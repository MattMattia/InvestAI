"""
Unit test suite for Module 6.2 Phase 1: Data Cleaning Pipeline,
Monetary Normalization, and Ticker/Currency Validation.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

import pytest
from app.domain.services.ingestion import (
    CleaningErrorCode,
    DataCleaningPipeline,
    RawHoldingRecord,
)


@pytest.mark.unit
class TestDataCleaningPipeline(unittest.TestCase):
    """Comprehensive unit tests for DataCleaningPipeline and monetary/ticker contracts."""

    def test_parse_decimal_argentine_and_us_formats(self) -> None:
        """
        Verify parse_decimal accurately resolves Argentine ('1.250.500,75') and
        US ('1,250,500.75') formats, thousand-only groupings, and currency symbols.
        """
        parse = DataCleaningPipeline.parse_decimal

        self.assertEqual(parse("1.250.500,75"), Decimal("1250500.75"))
        self.assertEqual(parse("1,250,500.75"), Decimal("1250500.75"))
        self.assertEqual(parse("1250,50"), Decimal("1250.50"))
        self.assertEqual(parse("1.000.000"), Decimal("1000000"))
        self.assertEqual(parse("1,000,000"), Decimal("1000000"))
        self.assertEqual(parse("$ 4.520,30"), Decimal("4520.30"))
        self.assertEqual(parse("U$S 120,50"), Decimal("120.50"))
        self.assertEqual(parse("USD\xa01,500.25"), Decimal("1500.25"))
        self.assertEqual(parse("ARS 98.765,43"), Decimal("98765.43"))
        self.assertEqual(parse(1500), Decimal("1500"))
        self.assertEqual(parse(100.55), Decimal("100.55"))

    def test_parse_decimal_accounting_parentheses_and_trailing_minus(self) -> None:
        """
        Verify accounting negative notation '(1.250,50)' and trailing minus '500-'
        parse as negative Decimals and trigger NEGATIVE_QUANTITY in clean_records.
        """
        parse = DataCleaningPipeline.parse_decimal

        self.assertEqual(parse("(1.250,50)"), Decimal("-1250.50"))
        self.assertEqual(parse("500-"), Decimal("-500"))
        self.assertEqual(parse("U$S (120,50)"), Decimal("-120.50"))

        pipeline = DataCleaningPipeline()
        raw_records = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="GGAL",
                raw_quantity="(1.250,50)",
                raw_avg_price="4200,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="YPFD",
                raw_quantity="500-",
                raw_avg_price="30000,00",
                raw_currency="ARS",
            ),
        ]
        result = pipeline.clean_records(raw_records)
        self.assertEqual(result.total_valid, 0)
        self.assertEqual(result.total_invalid, 2)
        self.assertTrue(result.has_errors)
        self.assertEqual(
            result.invalid_records[0].error_code,
            CleaningErrorCode.NEGATIVE_QUANTITY,
        )
        self.assertEqual(
            result.invalid_records[1].error_code,
            CleaningErrorCode.NEGATIVE_QUANTITY,
        )

    def test_parse_decimal_rejects_nan_infinity_and_exponent_bomb(self) -> None:
        """
        Verify parse_decimal rejects NaN, Infinity, -Inf, booleans, and oversized
        exponent bomb strings (> 32 characters).
        """
        parse = DataCleaningPipeline.parse_decimal

        for bad_input in (
            "NaN",
            "nan",
            "Infinity",
            "-Infinity",
            "Inf",
            "-Inf",
            Decimal("NaN"),
            Decimal("Infinity"),
            float("nan"),
            float("inf"),
            True,
            False,
            None,
            "1e999999999999999999999999999999999",
            "9" * 33,
            "1.2.3",
            "1,2,3",
        ):
            with self.assertRaises(ValueError):
                parse(bad_input)

    def test_normalize_ticker_strips_local_suffixes_and_preserves_dot_classes(
        self,
    ) -> None:
        """
        Verify normalize_ticker strips '.BA', '.BCBA', '.RO', '.AR' suffixes by default
        (or normalizes to '.BA' when keep_ba_suffix=True) while preserving 'BRK.B' and 'BF.B'.
        """
        norm = DataCleaningPipeline.normalize_ticker

        self.assertEqual(norm(" ggal.ba "), "GGAL")
        self.assertEqual(norm("YPFD.BCBA"), "YPFD")
        self.assertEqual(norm("AL30.AR"), "AL30")
        self.assertEqual(norm("pamp.ro"), "PAMP")
        self.assertEqual(norm("BRK.B"), "BRK.B")
        self.assertEqual(norm("BF.B"), "BF.B")

        self.assertEqual(norm("ggal.bcba", keep_ba_suffix=True), "GGAL.BA")
        self.assertEqual(norm("BRK.B", keep_ba_suffix=True), "BRK.B")

        for invalid_ticker in ("", "   ", "GGAL..BA", ".BA", "BAD TICKER!", "A" * 25):
            with self.assertRaises(ValueError):
                norm(invalid_ticker)

    def test_normalize_currency_ars_and_usd_variants(self) -> None:
        """
        Verify normalize_currency maps Argentine and US dollar variants into 'ARS' or 'USD'
        and rejects unsupported currencies with UNSUPPORTED_CURRENCY in clean_records.
        """
        norm_curr = DataCleaningPipeline.normalize_currency

        for ars_label in (
            "$",
            "Pesos",
            "ARS",
            "Pesos Argentinos",
            "Moneda Local",
            "AR$",
            None,
            "  ",
        ):
            self.assertEqual(norm_curr(ars_label), "ARS")

        for usd_label in (
            "U$S",
            "US$",
            "USD",
            "USD MEP",
            "Dólar CCL",
            "Dólar Estadounidense",
            "Cable",
            "MEP",
            "CCL",
            "Dólar Billete",
        ):
            self.assertEqual(norm_curr(usd_label), "USD")

        with self.assertRaises(ValueError):
            norm_curr("EUR")

        pipeline = DataCleaningPipeline()
        res = pipeline.clean_records(
            [
                RawHoldingRecord(
                    row_number=5,
                    raw_ticker="VWCE",
                    raw_quantity="100",
                    raw_avg_price="118,50",
                    raw_currency="EUR",
                )
            ]
        )
        self.assertEqual(res.total_valid, 0)
        self.assertEqual(res.total_invalid, 1)
        self.assertEqual(
            res.invalid_records[0].error_code,
            CleaningErrorCode.UNSUPPORTED_CURRENCY,
        )

    def test_clean_records_isolates_negative_and_zero_quantities(self) -> None:
        """
        Verify clean_records isolates NEGATIVE_QUANTITY, ZERO_QUANTITY, and
        INVALID_NUMERIC_FORMAT rows into invalid_records without aborting valid rows.
        """
        pipeline = DataCleaningPipeline()
        raw_batch = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="GGAL.BA",
                raw_quantity="1.500,00",
                raw_avg_price="$ 4.250,50",
                raw_currency="Pesos",
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="GFGC4500O",
                raw_quantity="-150",
                raw_avg_price="120,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=4,
                raw_ticker="AL30",
                raw_quantity="0,00",
                raw_avg_price="65.000,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=5,
                raw_ticker="YPFD",
                raw_quantity="not_a_number",
                raw_avg_price="30.000,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=6,
                raw_ticker="SPY",
                raw_quantity="25",
                raw_avg_price="U$S 580,25",
                raw_currency="Dólar CCL",
            ),
        ]

        result = pipeline.clean_records(raw_batch)
        self.assertEqual(result.total_valid, 2)
        self.assertEqual(result.total_invalid, 3)
        self.assertTrue(result.has_errors)

        self.assertEqual(result.valid_records[0].ticker, "GGAL")
        self.assertEqual(result.valid_records[0].quantity, Decimal("1500"))
        self.assertEqual(result.valid_records[0].avg_price, Decimal("4250.50"))
        self.assertEqual(result.valid_records[0].currency, "ARS")

        self.assertEqual(result.valid_records[1].ticker, "SPY")
        self.assertEqual(result.valid_records[1].quantity, Decimal("25"))
        self.assertEqual(result.valid_records[1].avg_price, Decimal("580.25"))
        self.assertEqual(result.valid_records[1].currency, "USD")

        self.assertEqual(
            [inv.error_code for inv in result.invalid_records],
            [
                CleaningErrorCode.NEGATIVE_QUANTITY,
                CleaningErrorCode.ZERO_QUANTITY,
                CleaningErrorCode.INVALID_NUMERIC_FORMAT,
            ],
        )

    def test_clean_records_handles_missing_zero_and_negative_avg_price(self) -> None:
        """
        Verify avg_price=None, '-', or '0,00' produces a valid CleanHoldingRecord
        with avg_price=None (and logs a warning for zero), whereas negative or
        corrupted avg_price values are rejected with INVALID_PRICE.
        """
        pipeline = DataCleaningPipeline()
        raw_batch = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="AL30",
                raw_quantity="1000",
                raw_avg_price=None,
                raw_currency="USD",
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="GD30",
                raw_quantity="2000",
                raw_avg_price="-",
                raw_currency="USD",
            ),
            RawHoldingRecord(
                row_number=4,
                raw_ticker="PAMP",
                raw_quantity="500",
                raw_avg_price="0,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=5,
                raw_ticker="TXAR",
                raw_quantity="300",
                raw_avg_price="-10,50",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=6,
                raw_ticker="CEPU",
                raw_quantity="400",
                raw_avg_price="abc_corrupt",
                raw_currency="ARS",
            ),
        ]

        result = pipeline.clean_records(raw_batch)
        self.assertEqual(result.total_valid, 3)
        self.assertEqual(result.total_invalid, 2)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("PAMP", result.warnings[0])

        for valid_rec in result.valid_records:
            self.assertIsNone(valid_rec.avg_price)

        self.assertEqual(result.invalid_records[0].error_code, CleaningErrorCode.INVALID_PRICE)
        self.assertEqual(result.invalid_records[1].error_code, CleaningErrorCode.INVALID_PRICE)

    def test_currency_inference_from_price_string_when_currency_column_missing(
        self,
    ) -> None:
        """
        Verify that when raw_currency is None, embedded USD indicators in
        raw_avg_price ('U$S 105,50' or 'USD 98.20') infer currency='USD'.
        """
        pipeline = DataCleaningPipeline()
        raw_batch = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="GD30",
                raw_quantity="5000",
                raw_avg_price="U$S 105,50",
                raw_currency=None,
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="GGAL",
                raw_quantity="1000",
                raw_avg_price="$ 4.500,00",
                raw_currency=None,
            ),
        ]

        result = pipeline.clean_records(raw_batch)
        self.assertEqual(result.total_valid, 2)
        self.assertEqual(result.valid_records[0].currency, "USD")
        self.assertEqual(result.valid_records[0].avg_price, Decimal("105.50"))
        self.assertEqual(result.valid_records[1].currency, "ARS")
        self.assertEqual(result.valid_records[1].avg_price, Decimal("4500.00"))

    def test_adversarial_sub_pip_quantity_rejected_and_sub_pip_price_normalized(
        self,
    ) -> None:
        """
        Verify sub-pip positive quantities ('0,00004' -> quantizes to '0.0000') are
        rejected as ZERO_QUANTITY, and sub-pip average prices ('0,00004') are
        normalized to None with an auditable warning.
        """
        pipeline = DataCleaningPipeline()
        raw_batch = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="GGAL",
                raw_quantity="0,00004",
                raw_avg_price="1200,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="YPFD",
                raw_quantity="10,00004",
                raw_avg_price="0,00004",
                raw_currency="ARS",
            ),
        ]

        result = pipeline.clean_records(raw_batch)
        self.assertEqual(result.total_valid, 1)
        self.assertEqual(result.total_invalid, 1)
        self.assertEqual(result.invalid_records[0].error_code, CleaningErrorCode.ZERO_QUANTITY)
        self.assertEqual(result.valid_records[0].ticker, "YPFD")
        self.assertEqual(result.valid_records[0].quantity, Decimal("10.0000"))
        self.assertIsNone(result.valid_records[0].avg_price)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("YPFD", result.warnings[0])

    def test_adversarial_interleaved_formula_prefixes_and_numeric_formula_rejection(
        self,
    ) -> None:
        """
        Verify iterative CWE-1236 formula prefix neutralization on tickers ('- =GGAL',
        '\\t +@YPFD.BA', \"'=AL30\") and rejection of formula expressions ('=-SUM(A1)',
        '=1+1') in quantity/price as INVALID_NUMERIC_FORMAT while preserving real negatives.
        """
        pipeline = DataCleaningPipeline()
        raw_batch = [
            RawHoldingRecord(
                row_number=2,
                raw_ticker="- =GGAL",
                raw_quantity="100",
                raw_avg_price="1500,00",
                raw_currency="=ARS",
            ),
            RawHoldingRecord(
                row_number=3,
                raw_ticker="\t +@YPFD.BA",
                raw_quantity="=-SUM(A1)",
                raw_avg_price="21000,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=4,
                raw_ticker="'=AL30",
                raw_quantity="=1+1",
                raw_avg_price="850,00",
                raw_currency="ARS",
            ),
            RawHoldingRecord(
                row_number=5,
                raw_ticker="COME",
                raw_quantity="- 150,50",
                raw_avg_price="240,00",
                raw_currency="ARS",
            ),
        ]

        result = pipeline.clean_records(raw_batch)
        self.assertEqual(result.total_valid, 1)
        self.assertEqual(result.valid_records[0].ticker, "GGAL")
        self.assertEqual(result.valid_records[0].currency, "ARS")
        self.assertEqual(
            [inv.error_code for inv in result.invalid_records],
            [
                CleaningErrorCode.INVALID_NUMERIC_FORMAT,
                CleaningErrorCode.INVALID_NUMERIC_FORMAT,
                CleaningErrorCode.NEGATIVE_QUANTITY,
            ],
        )
