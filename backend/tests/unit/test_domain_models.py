import unittest
from pydantic import ValidationError
from app.domain.models.asset import Asset, AssetType, Currency, Sector
from app.domain.models.portfolio import Holding, InvestorProfile, Portfolio
from app.domain.models.valuation import ValuationMetrics, ValuationStatus
from app.domain.rules.base import BaseRiskRule, RuleResult, Severity
from app.domain.rules.engine import ComplianceStatus, RiskEngine
from app.schemas.backtest import BacktestRunRequest
from app.schemas.portfolio import PortfolioCreate


class MockConcentrationRule(BaseRiskRule):
    rule_id = "R001_CONCENTRATION"
    rule_name = "Límite de Concentración Máxima por Activo"
    description = "Alerta si algún activo supera el 50% de la cartera."

    def evaluate(self, portfolio: Portfolio, context=None):
        results = []
        weights = portfolio.get_holding_weights()
        for ticker, weight in weights.items():
            if weight > 50.0:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=Severity.CRITICAL,
                        message=f"Activo {ticker} supera el límite (50%): actual {weight}%",
                        details={"ticker": ticker, "weight": weight, "limit": 50.0},
                    )
                )
            else:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=True,
                        severity=Severity.INFO,
                        message=f"Activo {ticker} dentro del límite: {weight}%",
                        details={"ticker": ticker, "weight": weight},
                    )
                )
        return results


class TestDomainModels(unittest.TestCase):
    def test_asset_creation_and_properties(self):
        aapl = Asset(
            ticker="AAPL",
            name="Apple Inc.",
            asset_type=AssetType.CEDEAR,
            currency=Currency.ARS,
            sector=Sector.TECHNOLOGY,
            country="US",
            cedear_ratio=10.0,
            underlying_ticker="AAPL",
        )
        self.assertTrue(aapl.is_equity)
        self.assertFalse(aapl.is_fixed_income)
        self.assertTrue(aapl.is_cedear)

    def test_valuation_metrics_positive_eps(self):
        val = ValuationMetrics.calculate(
            ticker="AAPL",
            price=150.0,
            eps=6.0,
            book_value_per_share=30.0,
            growth_rate_pct=15.0,
            is_equity=True,
        )
        self.assertEqual(val.status, ValuationStatus.VALID)
        self.assertEqual(val.pe_ratio, 25.0)
        self.assertEqual(val.pb_ratio, 5.0)
        self.assertEqual(val.peg_ratio, 1.6667)

    def test_valuation_metrics_negative_or_zero_eps_indeterminate(self):
        val_neg = ValuationMetrics.calculate(
            ticker="LOSS_CO",
            price=50.0,
            eps=-2.5,
            book_value_per_share=10.0,
            growth_rate_pct=10.0,
            is_equity=True,
        )
        self.assertEqual(val_neg.status, ValuationStatus.INDETERMINATE)
        self.assertIsNone(val_neg.pe_ratio)
        self.assertIsNone(val_neg.peg_ratio)
        self.assertIn("EPS nulo o negativo", val_neg.status_reason or "")

        val_zero = ValuationMetrics.calculate(
            ticker="ZERO_CO",
            price=20.0,
            eps=0.0,
            book_value_per_share=5.0,
            growth_rate_pct=5.0,
            is_equity=True,
        )
        self.assertEqual(val_zero.status, ValuationStatus.INDETERMINATE)
        self.assertIsNone(val_zero.pe_ratio)

    def test_portfolio_weights_and_allocations(self):
        aapl = Asset("AAPL", "Apple CEDEAR", AssetType.CEDEAR, Currency.ARS, Sector.TECHNOLOGY, "US", 10.0)
        al30 = Asset("AL30", "Bono AL30", AssetType.BOND_SOVEREIGN, Currency.ARS, Sector.GOVERNMENT, "AR")

        h1 = Holding(asset=aapl, quantity=10, average_buy_price=1000.0, current_price=1200.0, currency=Currency.ARS)
        h2 = Holding(asset=al30, quantity=100, average_buy_price=200.0, current_price=280.0, currency=Currency.ARS)

        portfolio = Portfolio(
            id="port-01",
            name="Cartera Test",
            investor_profile=InvestorProfile.MODERATE,
            holdings=[h1, h2],
            cash_balance_ars=0.0,
        )

        total = portfolio.total_value_ars()
        self.assertEqual(total, 40000.0)

        weights = portfolio.get_holding_weights()
        self.assertEqual(weights["AAPL"], 30.0)
        self.assertEqual(weights["AL30"], 70.0)

        sector_alloc = portfolio.get_sector_allocation()
        self.assertEqual(sector_alloc[Sector.TECHNOLOGY], 30.0)
        self.assertEqual(sector_alloc[Sector.GOVERNMENT], 70.0)

        self.assertEqual(portfolio.fixed_income_weight_pct, 70.0)
        self.assertEqual(portfolio.equity_weight_pct, 30.0)

    def test_risk_engine_execution(self):
        aapl = Asset("AAPL", "Apple CEDEAR", AssetType.CEDEAR, Currency.ARS, Sector.TECHNOLOGY, "US", 10.0)
        al30 = Asset("AL30", "Bono AL30", AssetType.BOND_SOVEREIGN, Currency.ARS, Sector.GOVERNMENT, "AR")

        h1 = Holding(asset=aapl, quantity=10, average_buy_price=1000.0, current_price=1200.0)
        h2 = Holding(asset=al30, quantity=100, average_buy_price=200.0, current_price=280.0)

        portfolio = Portfolio(
            id="port-01",
            name="Cartera Test",
            investor_profile=InvestorProfile.MODERATE,
            holdings=[h1, h2],
        )

        engine = RiskEngine()
        engine.register_rule(MockConcentrationRule())

        report = engine.evaluate(portfolio)
        self.assertEqual(report.total_rules_evaluated, 2)
        self.assertEqual(report.passed_rules_count, 1)
        self.assertEqual(report.failed_rules_count, 1)
        self.assertEqual(report.critical_alerts_count, 1)
        self.assertEqual(report.compliance_status, ComplianceStatus.NON_COMPLIANT)

    def test_portfolio_create_forbids_extra_fields(self):
        """Verifica que PortfolioCreate rechaza campos no autorizados (ARQ-01 / SEC-01)."""
        with self.assertRaises(ValidationError) as ctx:
            PortfolioCreate(
                name="Test Portfolio",
                unauthorized_injection_field="malicious_payload",
            )
        self.assertIn("extra_forbidden", str(ctx.exception))

    def test_backtest_run_request_forbids_extra_fields(self):
        """Verifica que BacktestRunRequest rechaza campos no autorizados (ARQ-01 / SEC-01)."""
        with self.assertRaises(ValidationError) as ctx:
            BacktestRunRequest(
                initial_capital=100000.0,
                tickers=["AAPL"],
                start_date="2024-01-01",
                end_date="2024-06-01",
                malicious_field=12345,
            )
        self.assertIn("extra_forbidden", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
