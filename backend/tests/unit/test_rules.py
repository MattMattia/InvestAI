import unittest
from app.domain.models.asset import Asset, AssetType, Currency, Sector
from app.domain.models.portfolio import Holding, InvestorProfile, Portfolio
from app.domain.models.valuation import ValuationMetrics, ValuationStatus
from app.domain.rules.base import Severity
from app.domain.rules.concentration import (
    MaxAssetConcentrationRule,
    MaxSectorConcentrationRule,
)
from app.domain.rules.engine import ComplianceStatus, RiskEngine
from app.domain.rules.fixed_income import MinFixedIncomeAllocationRule
from app.domain.rules.fx_ccl import ImplicitFXDivergenceRule
from app.domain.rules.valuation import ValuationAnomalyRule


class TestRiskRules(unittest.TestCase):
    def setUp(self):
        # Sample Assets
        self.aapl = Asset("AAPL", "Apple Inc.", AssetType.CEDEAR, Currency.ARS, Sector.TECHNOLOGY, "US", 10.0)
        self.msft = Asset("MSFT", "Microsoft", AssetType.CEDEAR, Currency.ARS, Sector.TECHNOLOGY, "US", 10.0)
        self.al30 = Asset("AL30", "Bono AL30", AssetType.BOND_SOVEREIGN, Currency.ARS, Sector.GOVERNMENT, "AR")
        self.ypf = Asset("YPFD", "YPF S.A.", AssetType.EQUITY, Currency.ARS, Sector.ENERGY, "AR")

    # =========================================================================
    # 1. MaxAssetConcentrationRule Tests
    # =========================================================================
    def test_max_asset_concentration_pass(self):
        # Portfolio with 4 assets evenly distributed at 25% each (Moderate limit = 15%, let's customize limit to 30%)
        h1 = Holding(self.aapl, quantity=10, average_buy_price=100.0, current_price=100.0)
        h2 = Holding(self.msft, quantity=10, average_buy_price=100.0, current_price=100.0)
        h3 = Holding(self.al30, quantity=10, average_buy_price=100.0, current_price=100.0)
        h4 = Holding(self.ypf, quantity=10, average_buy_price=100.0, current_price=100.0)

        portfolio = Portfolio("p1", "Test", InvestorProfile.MODERATE, [h1, h2, h3, h4])
        rule = MaxAssetConcentrationRule(default_max_pct=30.0)

        results = rule.evaluate(portfolio)
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertTrue(r.passed)
            self.assertEqual(r.severity, Severity.INFO)

    def test_max_asset_concentration_warning_and_critical(self):
        # Total = 10000. AAPL = 2000 (20%), MSFT = 4000 (40%), AL30 = 4000 (40%). Limit = 15%.
        # AAPL (20%) is > 15% but < 15%*1.3 (19.5%) -> wait, 20% > 19.5% -> Critical.
        # Let's adjust: limit = 20%. AAPL = 22% (Warning), MSFT = 40% (Critical).
        h_aapl = Holding(self.aapl, quantity=22, average_buy_price=100.0, current_price=100.0) # 2200 (22%)
        h_msft = Holding(self.msft, quantity=40, average_buy_price=100.0, current_price=100.0) # 4000 (40%)
        h_al30 = Holding(self.al30, quantity=38, average_buy_price=100.0, current_price=100.0) # 3800 (38%)

        portfolio = Portfolio("p2", "Concentrated", InvestorProfile.MODERATE, [h_aapl, h_msft, h_al30])
        rule = MaxAssetConcentrationRule(default_max_pct=20.0)

        results = rule.evaluate(portfolio)
        res_map = {r.details["ticker"]: r for r in results}

        # AAPL at 22% is > 20% and < 26% (20 * 1.3) -> WARNING
        self.assertFalse(res_map["AAPL"].passed)
        self.assertEqual(res_map["AAPL"].severity, Severity.WARNING)

        # MSFT at 40% is >= 26% -> CRITICAL
        self.assertFalse(res_map["MSFT"].passed)
        self.assertEqual(res_map["MSFT"].severity, Severity.CRITICAL)

    # =========================================================================
    # 2. MaxSectorConcentrationRule Tests
    # =========================================================================
    def test_max_sector_concentration(self):
        # Technology (AAPL + MSFT) = 70%, Government (AL30) = 30%. Limit = 35%.
        h_aapl = Holding(self.aapl, quantity=35, average_buy_price=100.0, current_price=100.0)
        h_msft = Holding(self.msft, quantity=35, average_buy_price=100.0, current_price=100.0)
        h_al30 = Holding(self.al30, quantity=30, average_buy_price=100.0, current_price=100.0)

        portfolio = Portfolio("p3", "Sector Port", InvestorProfile.MODERATE, [h_aapl, h_msft, h_al30])
        rule = MaxSectorConcentrationRule(default_max_pct=35.0)

        results = rule.evaluate(portfolio)
        res_map = {r.details["sector"]: r for r in results}

        # Technology = 70% > 35% * 1.25 (43.75%) -> CRITICAL
        self.assertFalse(res_map[Sector.TECHNOLOGY.value].passed)
        self.assertEqual(res_map[Sector.TECHNOLOGY.value].severity, Severity.CRITICAL)

        # Government = 30% <= 35% -> PASS (INFO)
        self.assertTrue(res_map[Sector.GOVERNMENT.value].passed)
        self.assertEqual(res_map[Sector.GOVERNMENT.value].severity, Severity.INFO)

    # =========================================================================
    # 3. MinFixedIncomeAllocationRule Tests
    # =========================================================================
    def test_min_fixed_income_allocation_conservative(self):
        # Conservative requires 50% minimum fixed income floor
        # Case A: 60% Fixed Income -> PASS
        h_al30 = Holding(self.al30, quantity=60, average_buy_price=100.0, current_price=100.0)
        h_aapl = Holding(self.aapl, quantity=40, average_buy_price=100.0, current_price=100.0)
        port_pass = Portfolio("p4", "Cons Pass", InvestorProfile.CONSERVATIVE, [h_al30, h_aapl])

        rule = MinFixedIncomeAllocationRule()
        res_pass = rule.evaluate(port_pass)
        self.assertTrue(res_pass[0].passed)
        self.assertEqual(res_pass[0].severity, Severity.INFO)

        # Case B: 30% Fixed Income (Floor is 50%, deficit is 20%, 30% > 25% (50*0.5)) -> WARNING
        h_al30_b = Holding(self.al30, quantity=30, average_buy_price=100.0, current_price=100.0)
        h_aapl_b = Holding(self.aapl, quantity=70, average_buy_price=100.0, current_price=100.0)
        port_warn = Portfolio("p5", "Cons Warn", InvestorProfile.CONSERVATIVE, [h_al30_b, h_aapl_b])

        res_warn = rule.evaluate(port_warn)
        self.assertFalse(res_warn[0].passed)
        self.assertEqual(res_warn[0].severity, Severity.WARNING)

        # Case C: 10% Fixed Income (10% < 25% (half of floor)) -> CRITICAL
        h_al30_c = Holding(self.al30, quantity=10, average_buy_price=100.0, current_price=100.0)
        h_aapl_c = Holding(self.aapl, quantity=90, average_buy_price=100.0, current_price=100.0)
        port_crit = Portfolio("p6", "Cons Crit", InvestorProfile.CONSERVATIVE, [h_al30_c, h_aapl_c])

        res_crit = rule.evaluate(port_crit)
        self.assertFalse(res_crit[0].passed)
        self.assertEqual(res_crit[0].severity, Severity.CRITICAL)

    # =========================================================================
    # 4. ValuationAnomalyRule Tests
    # =========================================================================
    def test_valuation_anomaly_rule(self):
        h_aapl = Holding(self.aapl, quantity=10, average_buy_price=100.0, current_price=100.0)
        h_ypf = Holding(self.ypf, quantity=10, average_buy_price=100.0, current_price=100.0)
        portfolio = Portfolio("p7", "Valuation Port", InvestorProfile.MODERATE, [h_aapl, h_ypf])

        # AAPL has PEG = 2.5 (> 2.0 -> WARNING)
        val_aapl = ValuationMetrics.calculate(
            ticker="AAPL",
            price=150.0,
            eps=6.0,
            book_value_per_share=30.0,
            growth_rate_pct=10.0,  # P/E = 25.0, PEG = 2.5
        )

        # YPF has negative earnings EPS = -3.0 -> INDETERMINATE (WARNING)
        val_ypf = ValuationMetrics.calculate(
            ticker="YPFD",
            price=80.0,
            eps=-3.0,
            book_value_per_share=40.0,
            growth_rate_pct=5.0,
        )

        rule = ValuationAnomalyRule(max_peg=2.0)
        results = rule.evaluate(portfolio, context={"valuations": {"AAPL": val_aapl, "YPFD": val_ypf}})

        res_map = {r.details["ticker"]: r for r in results}

        self.assertFalse(res_map["AAPL"].passed)
        self.assertEqual(res_map["AAPL"].severity, Severity.WARNING)
        self.assertIn("Ratio PEG de 2.50", res_map["AAPL"].message)

        self.assertFalse(res_map["YPFD"].passed)
        self.assertEqual(res_map["YPFD"].severity, Severity.WARNING)
        self.assertIn("Alerta por Imposibilidad de Valuación Contable", res_map["YPFD"].message)

    # =========================================================================
    # 5. ImplicitFXDivergenceRule Tests
    # =========================================================================
    def test_implicit_fx_divergence_rule(self):
        portfolio = Portfolio("p8", "FX Port", InvestorProfile.MODERATE, [])
        rule = ImplicitFXDivergenceRule(warning_spread_pct=5.0, critical_spread_pct=10.0)

        # Benchmark CCL = 1300 ARS/USD
        context = {
            "reference_ccl_fx": 1300.0,
            "implicit_fx_rates": {
                "AAPL": 1320.0,  # Spread: 1.54% -> PASS (INFO)
                "AL30": 1390.0,  # Spread: 6.92% -> WARNING (> 5%)
                "GGAL": 1450.0,  # Spread: 11.54% -> CRITICAL (> 10%)
            },
        }

        results = rule.evaluate(portfolio, context=context)
        res_map = {r.details["ticker"]: r for r in results}

        self.assertTrue(res_map["AAPL"].passed)
        self.assertEqual(res_map["AAPL"].severity, Severity.INFO)

        self.assertFalse(res_map["AL30"].passed)
        self.assertEqual(res_map["AL30"].severity, Severity.WARNING)

        self.assertFalse(res_map["GGAL"].passed)
        self.assertEqual(res_map["GGAL"].severity, Severity.CRITICAL)

    # =========================================================================
    # 6. Full RiskEngine Orchestration with all Rules
    # =========================================================================
    def test_risk_engine_full_suite(self):
        h_aapl = Holding(self.aapl, quantity=80, average_buy_price=100.0, current_price=100.0) # 80% Tech
        h_al30 = Holding(self.al30, quantity=20, average_buy_price=100.0, current_price=100.0) # 20% Gov / FI

        portfolio = Portfolio("p9", "Full Engine Port", InvestorProfile.CONSERVATIVE, [h_aapl, h_al30])

        engine = RiskEngine([
            MaxAssetConcentrationRule(),
            MaxSectorConcentrationRule(),
            MinFixedIncomeAllocationRule(),
            ImplicitFXDivergenceRule(),
        ])

        report = engine.evaluate(
            portfolio,
            context={
                "reference_ccl_fx": 1300.0,
                "implicit_fx_rates": {"AAPL": 1310.0, "AL30": 1315.0},
            },
        )

        self.assertEqual(report.compliance_status, ComplianceStatus.NON_COMPLIANT)
        self.assertGreater(report.critical_alerts_count, 0)
        self.assertEqual(report.total_rules_evaluated, 7)  # 2 assets + 2 sectors + 1 FI floor + 2 FX tickers = 7
        self.assertIsNotNone(report.evaluated_at)


if __name__ == "__main__":
    unittest.main()
