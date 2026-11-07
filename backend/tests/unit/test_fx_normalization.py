import unittest
from datetime import UTC, datetime

from app.domain.models.financial_statements import (
    BalanceSheetStandard,
    CashFlowStandard,
    IncomeStatementStandard,
    clean_financial_float,
    compute_standard_metrics,
    safe_divide,
)
from app.domain.models.fx import Currency, FXQuote
from app.domain.services.fx_service import FXService


class TestFXNormalization(unittest.TestCase):
    def setUp(self) -> None:
        self.fx_service = FXService()

    def test_fx_quote_validation(self) -> None:
        # Valid quote
        quote = FXQuote(
            pair="USD_CCL/ARS",
            rate=1310.50,
            timestamp=datetime.now(UTC),
            source="BYMA",
        )
        self.assertEqual(quote.pair, "USD_CCL/ARS")
        self.assertEqual(quote.rate, 1310.50)

        # Rate must be > 0
        with self.assertRaises(ValueError):
            FXQuote(pair="USD/ARS", rate=0.0)
        with self.assertRaises(ValueError):
            FXQuote(pair="USD/ARS", rate=-100.0)

        # Pair must contain slash
        with self.assertRaises(ValueError):
            FXQuote(pair="USDARS", rate=1300.0)

    def test_ratio_parsing(self) -> None:
        # Numeric
        self.assertEqual(FXService.parse_conversion_ratio(10), 10.0)
        self.assertEqual(FXService.parse_conversion_ratio(2.5), 2.5)

        # Notation string "10:1", "2:1", "1/2"
        self.assertEqual(FXService.parse_conversion_ratio("10:1"), 10.0)
        self.assertEqual(FXService.parse_conversion_ratio("2:1"), 2.0)
        self.assertEqual(FXService.parse_conversion_ratio("5/1"), 5.0)
        self.assertEqual(FXService.parse_conversion_ratio(" 10 : 1 "), 10.0)

        # Invalid ratio
        with self.assertRaises(ValueError):
            FXService.parse_conversion_ratio(0)
        with self.assertRaises(ValueError):
            FXService.parse_conversion_ratio("invalid_ratio")

    def test_implicit_ccl_calculation_with_real_cedears(self) -> None:
        # 1. AAPL CEDEAR (Ratio 10:1)
        # 10 CEDEARs = 1 AAPL share
        # CEDEAR price = $29,900 ARS, AAPL US price = $230.00 USD
        # Expected CCL = (29900 * 10) / 230 = 1300.00 ARS/USD
        ccl_aapl = self.fx_service.calculate_implicit_ccl(
            cedear_price_ars=29900.0,
            underlying_price_usd=230.0,
            conversion_ratio="10:1",
        )
        self.assertEqual(ccl_aapl, 1300.0)

        # 2. NVDA CEDEAR (Ratio 2:1)
        # 2 CEDEARs = 1 NVDA share
        # CEDEAR price = $87,750 ARS, NVDA US price = $135.00 USD
        # Expected CCL = (87750 * 2) / 135 = 1300.00 ARS/USD
        ccl_nvda = self.fx_service.calculate_implicit_ccl(
            cedear_price_ars=87750.0,
            underlying_price_usd=135.0,
            conversion_ratio=2.0,
        )
        self.assertEqual(ccl_nvda, 1300.0)

        # 3. Create implicit FXQuote
        quote = self.fx_service.create_cedear_implicit_quote(
            ticker="NVDA",
            cedear_price_ars=87750.0,
            underlying_price_usd=135.0,
            conversion_ratio="2:1",
        )
        self.assertEqual(quote.pair, "USD_CCL/ARS")
        self.assertEqual(quote.rate, 1300.0)
        self.assertIn("NVDA", quote.source)

    def test_implicit_ccl_invalid_inputs(self) -> None:
        # Zero or negative underlying price
        with self.assertRaises(ValueError):
            self.fx_service.calculate_implicit_ccl(
                cedear_price_ars=1000.0, underlying_price_usd=0.0, conversion_ratio=1.0
            )
        with self.assertRaises(ValueError):
            self.fx_service.calculate_implicit_ccl(
                cedear_price_ars=1000.0, underlying_price_usd=-50.0, conversion_ratio=1.0
            )

        # Zero or negative cedear price
        with self.assertRaises(ValueError):
            self.fx_service.calculate_implicit_ccl(
                cedear_price_ars=0.0, underlying_price_usd=100.0, conversion_ratio=1.0
            )

    def test_canonical_currency_conversions(self) -> None:
        self.fx_service.register_quote(FXQuote(pair="USD/ARS", rate=1250.0))
        self.fx_service.register_quote(FXQuote(pair="USD_CCL/ARS", rate=1300.0))
        self.fx_service.register_quote(FXQuote(pair="USD_MEP/ARS", rate=1260.0))

        # Identity
        self.assertEqual(self.fx_service.convert(500.0, Currency.ARS, Currency.ARS), 500.0)
        self.assertEqual(self.fx_service.convert(100.0, Currency.USD, Currency.USD), 100.0)

        # USD to ARS
        converted_ars = self.fx_service.convert(100.0, Currency.USD_CCL, Currency.ARS)
        self.assertEqual(converted_ars, 130000.0)

        # ARS to USD
        converted_usd = self.fx_service.convert(130000.0, Currency.ARS, Currency.USD_CCL)
        self.assertEqual(converted_usd, 100.0)

        # Convenience methods
        self.assertEqual(self.fx_service.convert_to_ars(10.0, Currency.USD_CCL), 13000.0)
        self.assertEqual(
            self.fx_service.convert_to_usd(13000.0, Currency.ARS, fx_rate=1300.0), 10.0
        )

        # Holding conversion (quantity * price)
        # 10 shares at $13,000 ARS each = $130,000 ARS -> in USD CCL = $100 USD
        val_usd = self.fx_service.convert_holding(
            quantity=10,
            price=13000.0,
            from_currency=Currency.ARS,
            to_currency=Currency.USD_CCL,
        )
        self.assertEqual(val_usd, 100.0)


class TestFinancialStatementsCanonical(unittest.TestCase):
    def test_sanitization_and_safe_divide(self) -> None:
        # clean_financial_float
        self.assertEqual(clean_financial_float("$ 1,500.50"), 1500.50)
        self.assertEqual(clean_financial_float(" 2500000 "), 2500000.0)
        self.assertIsNone(clean_financial_float("N/A"))
        self.assertIsNone(clean_financial_float("None"))
        self.assertIsNone(clean_financial_float(float("nan")))
        self.assertIsNone(clean_financial_float(float("inf")))
        self.assertIsNone(clean_financial_float(None))

        # safe_divide zero division protection
        self.assertIsNone(safe_divide(100.0, 0.0))
        self.assertIsNone(safe_divide(100.0, None))
        self.assertIsNone(safe_divide(None, 50.0))
        self.assertEqual(safe_divide(100.0, 50.0), 2.0)
        self.assertEqual(safe_divide(100.0, 0.0, default=0.0), 0.0)

    def test_canonical_statements_auto_synthesis(self) -> None:
        # Income statement
        inc = IncomeStatementStandard(
            revenue="$ 100,000,000",
            net_income="20000000",
            eps="5.00",
            diluted_eps="4.90",
            operating_income="25000000",
            ebitda="30000000",
        )
        self.assertEqual(inc.revenue, 100000000.0)
        self.assertEqual(inc.net_income, 20000000.0)
        self.assertEqual(inc.eps, 5.0)
        self.assertEqual(inc.diluted_eps, 4.90)

        # Balance sheet with auto-synthesis of Net Debt and Equity
        bal = BalanceSheetStandard(
            total_assets=150000000.0,
            total_liabilities=50000000.0,
            total_debt=30000000.0,
            cash_and_equivalents=10000000.0,
            current_assets=40000000.0,
            current_liabilities=20000000.0,
        )
        # Net Debt = 30M - 10M = 20M
        self.assertEqual(bal.net_debt, 20000000.0)
        # Total Equity = 150M - 50M = 100M
        self.assertEqual(bal.total_equity, 100000000.0)

        # Cash flow statement with auto-synthesis of FCF
        cf = CashFlowStandard(
            operating_cash_flow=25000000.0,
            capital_expenditure=5000000.0,
        )
        # FCF = 25M - 5M = 20M
        self.assertEqual(cf.free_cash_flow, 20000000.0)

    def test_compute_standard_metrics(self) -> None:
        inc = IncomeStatementStandard(
            revenue=100000000.0,
            net_income=20000000.0,
            eps=5.00,
            diluted_eps=5.00,
            ebitda=30000000.0,
        )
        bal = BalanceSheetStandard(
            total_assets=100000000.0,
            total_liabilities=40000000.0,
            total_debt=20000000.0,
            cash_and_equivalents=5000000.0,
            total_equity=60000000.0,
            current_assets=30000000.0,
            current_liabilities=15000000.0,
        )

        metrics = compute_standard_metrics(
            current_price=100.0,
            income=inc,
            balance=bal,
            shares_outstanding=4000000.0,  # 4M shares * $100 = $400M Market Cap
            earnings_growth_rate=15.0,  # 15% EPS growth
        )

        # P/E = 100 / 5 = 20.0
        self.assertEqual(metrics.pe_ratio, 20.0)
        # Book value per share = 60M / 4M = 15.0 -> P/B = 100 / 15 = 6.6667
        self.assertEqual(metrics.pb_ratio, 6.6667)
        # PEG = 20.0 / 15.0 = 1.3333
        self.assertEqual(metrics.peg_ratio, 1.3333)
        # Current Ratio = 30M / 15M = 2.0
        self.assertEqual(metrics.current_ratio, 2.0)
        # Debt to Equity = 20M / 60M = 0.3333
        self.assertEqual(metrics.debt_to_equity, 0.3333)
        # ROE = 20M / 60M = 0.3333
        self.assertEqual(metrics.roe, 0.3333)
        # EV/EBITDA: Market Cap 400M + Net Debt 15M = EV 415M -> 415M / 30M = 13.8333
        self.assertEqual(metrics.ev_to_ebitda, 13.8333)

    def test_metrics_zero_division_resilience(self) -> None:
        # Zero earnings and zero balance sheet shouldn't raise exception
        inc_zero = IncomeStatementStandard(net_income=0.0, eps=0.0, ebitda=0.0)
        bal_zero = BalanceSheetStandard(total_equity=0.0, current_liabilities=0.0)

        metrics = compute_standard_metrics(
            current_price=50.0,
            income=inc_zero,
            balance=bal_zero,
            shares_outstanding=0.0,
            earnings_growth_rate=0.0,
        )

        self.assertIsNone(metrics.pe_ratio)
        self.assertIsNone(metrics.pb_ratio)
        self.assertIsNone(metrics.peg_ratio)
        self.assertIsNone(metrics.current_ratio)


if __name__ == "__main__":
    unittest.main()
