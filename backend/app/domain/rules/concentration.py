from typing import Any, Dict, List, Optional
from app.domain.models.portfolio import InvestorProfile, Portfolio
from app.domain.rules.base import BaseRiskRule, RuleResult, Severity


class MaxAssetConcentrationRule(BaseRiskRule):
    """
    Deterministic rule evaluating that no single asset exceeds the maximum concentration limit.
    Thresholds can be customized via context or derived from the investor profile.
    """
    rule_id = "RULE_CONC_001"
    rule_name = "Concentración Máxima por Activo"
    description = "Evalúa que la ponderación individual de cada activo no supere el umbral máximo de riesgo."

    PROFILE_LIMITS: Dict[InvestorProfile, float] = {
        InvestorProfile.CONSERVATIVE: 10.0,   # Máximo 10% por activo
        InvestorProfile.MODERATE: 20.0,       # Máximo 20% por activo
        InvestorProfile.AGGRESSIVE: 35.0,     # Máximo 35% por activo
    }

    def __init__(self, default_max_pct: Optional[float] = None) -> None:
        self.default_max_pct = default_max_pct

    def evaluate(
        self,
        portfolio: Portfolio,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RuleResult]:
        ctx = context or {}
        fx_ccl = ctx.get("fx_ccl", 1.0)
        
        # Determine limit: context override > default_max_pct > profile limit > fallback 20%
        limit_pct = ctx.get(
            "max_asset_concentration_pct",
            self.default_max_pct or self.PROFILE_LIMITS.get(portfolio.investor_profile, 20.0),
        )

        weights = portfolio.get_holding_weights(fx_ccl=fx_ccl)
        results: List[RuleResult] = []

        if not weights:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message="El portafolio no posee tenencias registradas.",
                    details={"limit_pct": limit_pct, "holdings_count": 0},
                )
            )
            return results

        for ticker, weight in weights.items():
            if weight > limit_pct:
                # Critical if exceeds by more than 30% of the threshold, else Warning
                is_critical = weight >= (limit_pct * 1.3)
                severity = Severity.CRITICAL if is_critical else Severity.WARNING
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=severity,
                        message=(
                            f"El activo '{ticker}' representa el {weight:.2f}% de la cartera, "
                            f"superando el límite máximo permitido del {limit_pct:.2f}%."
                        ),
                        details={
                            "ticker": ticker,
                            "current_weight_pct": weight,
                            "max_allowed_pct": limit_pct,
                            "excess_pct": round(weight - limit_pct, 2),
                        },
                    )
                )
            else:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=True,
                        severity=Severity.INFO,
                        message=f"El activo '{ticker}' ({weight:.2f}%) se encuentra dentro del límite ({limit_pct:.2f}%).",
                        details={
                            "ticker": ticker,
                            "current_weight_pct": weight,
                            "max_allowed_pct": limit_pct,
                        },
                    )
                )

        return results


class MaxSectorConcentrationRule(BaseRiskRule):
    """
    Deterministic rule evaluating that no economic sector exceeds the maximum concentration limit.
    """
    rule_id = "RULE_CONC_002"
    rule_name = "Concentración Máxima por Sector"
    description = "Evalúa que la exposición agrupada por sector económico no sobrepase el umbral de diversificación."

    PROFILE_LIMITS: Dict[InvestorProfile, float] = {
        InvestorProfile.CONSERVATIVE: 25.0,   # Máximo 25% por sector
        InvestorProfile.MODERATE: 40.0,       # Máximo 40% por sector
        InvestorProfile.AGGRESSIVE: 60.0,     # Máximo 60% por sector
    }

    def __init__(self, default_max_pct: Optional[float] = None) -> None:
        self.default_max_pct = default_max_pct

    def evaluate(
        self,
        portfolio: Portfolio,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RuleResult]:
        ctx = context or {}
        fx_ccl = ctx.get("fx_ccl", 1.0)

        limit_pct = ctx.get(
            "max_sector_concentration_pct",
            self.default_max_pct or self.PROFILE_LIMITS.get(portfolio.investor_profile, 40.0),
        )

        allocations = portfolio.get_sector_allocation(fx_ccl=fx_ccl)
        results: List[RuleResult] = []

        if not allocations:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message="No hay sectores computables en el portafolio.",
                    details={"limit_pct": limit_pct},
                )
            )
            return results

        for sector, weight in allocations.items():
            sector_name = sector.value if hasattr(sector, "value") else str(sector)
            if weight > limit_pct:
                is_critical = weight >= (limit_pct * 1.25)
                severity = Severity.CRITICAL if is_critical else Severity.WARNING
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=severity,
                        message=(
                            f"La exposición al sector '{sector_name}' es del {weight:.2f}%, "
                            f"excediendo el límite permitido del {limit_pct:.2f}%."
                        ),
                        details={
                            "sector": sector_name,
                            "current_weight_pct": weight,
                            "max_allowed_pct": limit_pct,
                            "excess_pct": round(weight - limit_pct, 2),
                        },
                    )
                )
            else:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=True,
                        severity=Severity.INFO,
                        message=f"Sector '{sector_name}' ({weight:.2f}%) en cumplimiento con el límite ({limit_pct:.2f}%).",
                        details={
                            "sector": sector_name,
                            "current_weight_pct": weight,
                            "max_allowed_pct": limit_pct,
                        },
                    )
                )

        return results
