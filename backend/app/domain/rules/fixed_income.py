from typing import Any, Dict, List, Optional
from app.domain.models.portfolio import InvestorProfile, Portfolio
from app.domain.rules.base import BaseRiskRule, RuleResult, Severity


class MinFixedIncomeAllocationRule(BaseRiskRule):
    """
    Deterministic rule evaluating that the portfolio maintains a minimum allocation floor in Fixed Income
    instruments (Bonds, Sovereign debt, Corporate ONs, Treasury bills) according to the investor's risk profile (F1.6).
    """
    rule_id = "RULE_FI_001"
    rule_name = "Piso Mínimo de Asignación en Renta Fija"
    description = "Verifica que la cartera mantenga el porcentaje mínimo exigido en instrumentos de renta fija según el perfil de tolerancia al riesgo."

    PROFILE_MIN_FLOOR: Dict[InvestorProfile, float] = {
        InvestorProfile.CONSERVATIVE: 60.0,   # Mínimo 60% en renta fija
        InvestorProfile.MODERATE: 25.0,       # Mínimo 25% en renta fija
        InvestorProfile.AGGRESSIVE: 0.0,      # Sin piso obligatorio (0%)
    }

    def __init__(self, default_min_pct: Optional[float] = None) -> None:
        self.default_min_pct = default_min_pct

    def evaluate(
        self,
        portfolio: Portfolio,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RuleResult]:
        ctx = context or {}
        fx_ccl = ctx.get("fx_ccl", 1.0)

        min_required_pct = ctx.get(
            "min_fixed_income_pct",
            self.default_min_pct if self.default_min_pct is not None else self.PROFILE_MIN_FLOOR.get(portfolio.investor_profile, 25.0),
        )

        allocations = portfolio.get_asset_type_allocation(fx_ccl=fx_ccl)
        from app.domain.models.asset import AssetType
        current_fi_pct = round(
            allocations.get(AssetType.BOND_SOVEREIGN, 0.0)
            + allocations.get(AssetType.BOND_CORPORATE, 0.0)
            + allocations.get(AssetType.TREASURY_BILL, 0.0),
            2,
        )

        # If no minimum required (e.g. aggressive profile with 0%), always passes
        if min_required_pct <= 0:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message=f"Perfil '{portfolio.investor_profile.value}' no exige un piso obligatorio de Renta Fija (Actual: {current_fi_pct:.2f}%).",
                    details={
                        "current_fixed_income_pct": current_fi_pct,
                        "min_required_pct": min_required_pct,
                    },
                )
            ]

        if current_fi_pct < min_required_pct:
            deficit_pct = round(min_required_pct - current_fi_pct, 2)
            # Critical if holding less than half of the required floor
            is_critical = current_fi_pct < (min_required_pct * 0.5)
            severity = Severity.CRITICAL if is_critical else Severity.WARNING

            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=False,
                    severity=severity,
                    message=(
                        f"La asignación en Renta Fija ({current_fi_pct:.2f}%) está por debajo del piso mínimo "
                        f"requerido ({min_required_pct:.2f}%) para el perfil '{portfolio.investor_profile.value}'. "
                        f"Déficit: {deficit_pct:.2f}%."
                    ),
                    details={
                        "current_fixed_income_pct": current_fi_pct,
                        "min_required_pct": min_required_pct,
                        "deficit_pct": deficit_pct,
                    },
                )
            ]

        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                passed=True,
                severity=Severity.INFO,
                message=(
                    f"Asignación en Renta Fija en cumplimiento ({current_fi_pct:.2f}% >= {min_required_pct:.2f}% requerido)."
                ),
                details={
                    "current_fixed_income_pct": current_fi_pct,
                    "min_required_pct": min_required_pct,
                },
            )
        ]
