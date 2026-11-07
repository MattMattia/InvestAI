from typing import Any

from app.domain.models.portfolio import InvestorProfile, Portfolio
from app.domain.models.valuation import ValuationMetrics, ValuationStatus
from app.domain.rules.base import BaseRiskRule, RuleResult, Severity


class ValuationAnomalyRule(BaseRiskRule):
    """
    Deterministic rule evaluating accounting valuation multiples (P/E, P/B, PEG) (F1.5 & F1.6).
    Detects:
      1. Overvaluation anomalies (PEG > 2.0, extreme P/B).
      2. Loss-making companies (EPS <= 0) classified as INDETERMINATE with lack of accounting valuation.
    Severity adapts dynamically to the investor's risk tolerance profile:
      - CONSERVATIVE: CRITICAL
      - MODERATE: WARNING (or CRITICAL if extreme PEG >= 3.0)
      - AGGRESSIVE: INFO
    """

    rule_id = "RULE_VAL_001"
    rule_name = "Anomalías de Valuación Fundamental y Empresas con Pérdidas"
    description = "Evalúa anomalías en múltiplos contables (PEG > 2.0, P/B excesivo) e identifica imposibilidad de valuación contable ante EPS <= 0."

    DEFAULT_MAX_PEG: float = 2.0
    DEFAULT_MAX_PB: float = 12.0

    PROFILE_SEVERITY: dict[InvestorProfile, Severity] = {
        InvestorProfile.CONSERVATIVE: Severity.CRITICAL,
        InvestorProfile.MODERATE: Severity.WARNING,
        InvestorProfile.AGGRESSIVE: Severity.INFO,
    }

    def __init__(
        self,
        max_peg: float = DEFAULT_MAX_PEG,
        max_pb: float = DEFAULT_MAX_PB,
    ) -> None:
        self.max_peg = max_peg
        self.max_pb = max_pb

    def _determine_failure_severity(
        self, portfolio: Portfolio, is_extreme: bool = False
    ) -> Severity:
        profile = getattr(portfolio, "investor_profile", InvestorProfile.MODERATE)
        if isinstance(profile, str):
            try:
                profile = InvestorProfile(profile)
            except ValueError:
                profile = InvestorProfile.MODERATE

        if profile == InvestorProfile.CONSERVATIVE:
            return Severity.CRITICAL
        elif profile == InvestorProfile.AGGRESSIVE:
            return Severity.INFO
        else:
            return Severity.CRITICAL if is_extreme else Severity.WARNING

    def evaluate(
        self,
        portfolio: Portfolio,
        context: dict[str, Any] | None = None,
    ) -> list[RuleResult]:
        ctx = context or {}
        valuations_map: dict[str, ValuationMetrics] = ctx.get("valuations", {})
        max_peg = ctx.get("max_peg_threshold", self.max_peg)
        max_pb = ctx.get("max_pb_threshold", self.max_pb)

        results: list[RuleResult] = []

        equity_holdings = [h for h in portfolio.holdings if h.asset.is_equity]

        if not equity_holdings:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message="El portafolio no contiene activos de renta variable sujetos a ratios contables.",
                    details={},
                )
            )
            return results

        for holding in equity_holdings:
            ticker = holding.asset.ticker
            val = valuations_map.get(ticker)

            # If no valuation data was provided in context, record an info note
            if not val:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=True,
                        severity=Severity.INFO,
                        message=f"Activo '{ticker}': Datos de valuación contable no suministrados en la evaluación.",
                        details={"ticker": ticker},
                    )
                )
                continue

            # Case 1: Indeterminate valuation due to EPS <= 0 (Specification Section 4.3)
            if val.status == ValuationStatus.INDETERMINATE:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=self._determine_failure_severity(portfolio, is_extreme=False),
                        message=(
                            f"Alerta por Imposibilidad de Valuación Contable en '{ticker}': "
                            f"{val.status_reason or 'Beneficio por acción (EPS) nulo o negativo'}. "
                            f"La empresa presenta pérdidas operativas."
                        ),
                        details={
                            "ticker": ticker,
                            "eps": val.eps,
                            "status": val.status.value,
                            "status_reason": val.status_reason,
                        },
                    )
                )
                continue

            # Case 2: Extreme PEG Ratio (Overvaluation relative to earnings growth)
            if val.peg_ratio is not None and val.peg_ratio > max_peg:
                is_critical = val.peg_ratio >= 3.0
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=self._determine_failure_severity(
                            portfolio, is_extreme=is_critical
                        ),
                        message=(
                            f"Alerta de Sobrevaloración Contable en '{ticker}': Ratio PEG de {val.peg_ratio:.2f} "
                            f"supera el umbral prudencial de {max_peg:.2f}."
                        ),
                        details={
                            "ticker": ticker,
                            "peg_ratio": val.peg_ratio,
                            "pe_ratio": val.pe_ratio,
                            "growth_rate_pct": val.growth_rate_pct,
                            "max_peg_threshold": max_peg,
                        },
                    )
                )
                continue

            # Case 3: Extreme Price-to-Book (P/B)
            if val.pb_ratio is not None and val.pb_ratio > max_pb:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=self._determine_failure_severity(portfolio, is_extreme=False),
                        message=(
                            f"Múltiplo P/B anómalo en '{ticker}': Cotiza a {val.pb_ratio:.2f}x "
                            f"su valor contable en libros (umbral: {max_pb:.2f}x)."
                        ),
                        details={
                            "ticker": ticker,
                            "pb_ratio": val.pb_ratio,
                            "book_value_per_share": val.book_value_per_share,
                            "max_pb_threshold": max_pb,
                        },
                    )
                )
                continue

            # Case 4: Healthy Valuation
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message=(
                        f"Valuación consistente para '{ticker}': P/E={val.pe_ratio or 'N/A'}, "
                        f"P/B={val.pb_ratio or 'N/A'}, PEG={val.peg_ratio or 'N/A'}."
                    ),
                    details={
                        "ticker": ticker,
                        "pe_ratio": val.pe_ratio,
                        "pb_ratio": val.pb_ratio,
                        "peg_ratio": val.peg_ratio,
                        "eps": val.eps,
                    },
                )
            )

        return results
