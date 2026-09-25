from typing import Any, Dict, List, Optional
from app.domain.models.portfolio import Portfolio
from app.domain.rules.base import BaseRiskRule, RuleResult, Severity


class ImplicitFXDivergenceRule(BaseRiskRule):
    """
    Deterministic rule evaluating exchange rate distortions and arbitrage divergence
    between asset-implied dollar rates (CCL / MEP) and the benchmark FX rate (F1.4 & Sec 4.1).
    """
    rule_id = "RULE_FX_001"
    rule_name = "Desvío y Distorsión de Dólar Implícito (CCL / MEP)"
    description = "Detecta desvíos significativos entre el tipo de cambio implícito de activos bimoneda/CEDEARs y el dólar cable de referencia."

    DEFAULT_MAX_WARNING_SPREAD_PCT: float = 5.0    # 5% spread warning
    DEFAULT_MAX_CRITICAL_SPREAD_PCT: float = 10.0  # 10% spread critical anomaly

    def __init__(
        self,
        warning_spread_pct: float = DEFAULT_MAX_WARNING_SPREAD_PCT,
        critical_spread_pct: float = DEFAULT_MAX_CRITICAL_SPREAD_PCT,
    ) -> None:
        self.warning_spread_pct = warning_spread_pct
        self.critical_spread_pct = critical_spread_pct

    def evaluate(
        self,
        portfolio: Portfolio,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RuleResult]:
        ctx = context or {}
        reference_ccl = ctx.get("reference_ccl_fx")
        reference_mep = ctx.get("reference_mep_fx")
        implicit_fx_rates: Dict[str, float] = ctx.get("implicit_fx_rates", {})

        results: List[RuleResult] = []

        if not reference_ccl and not reference_mep:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message="No se suministró tasa de cambio de referencia (CCL/MEP) para contraste cambiario.",
                    details={},
                )
            )
            return results

        benchmark_fx = reference_ccl or reference_mep or 1.0

        if not implicit_fx_rates:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    passed=True,
                    severity=Severity.INFO,
                    message="No hay cotizaciones implícitas de activos bimoneda para contrastar.",
                    details={"benchmark_fx": benchmark_fx},
                )
            )
            return results

        for ticker, implied_rate in implicit_fx_rates.items():
            if implied_rate <= 0:
                continue

            spread_nominal = implied_rate - benchmark_fx
            spread_pct = abs(spread_nominal / benchmark_fx) * 100.0

            if spread_pct > self.critical_spread_pct:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=Severity.CRITICAL,
                        message=(
                            f"Distorsión cambiaria crítica en '{ticker}': Dólar implícito ${implied_rate:.2f} "
                            f"difiere un {spread_pct:.2f}% respecto al benchmark ${benchmark_fx:.2f}."
                        ),
                        details={
                            "ticker": ticker,
                            "implied_rate": round(implied_rate, 2),
                            "benchmark_fx": round(benchmark_fx, 2),
                            "spread_pct": round(spread_pct, 2),
                            "threshold_pct": self.critical_spread_pct,
                        },
                    )
                )
            elif spread_pct > self.warning_spread_pct:
                results.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        passed=False,
                        severity=Severity.WARNING,
                        message=(
                            f"Brecha cambiaria detectada en '{ticker}': Dólar implícito ${implied_rate:.2f} "
                            f"presenta un desvío del {spread_pct:.2f}% frente al benchmark ${benchmark_fx:.2f}."
                        ),
                        details={
                            "ticker": ticker,
                            "implied_rate": round(implied_rate, 2),
                            "benchmark_fx": round(benchmark_fx, 2),
                            "spread_pct": round(spread_pct, 2),
                            "threshold_pct": self.warning_spread_pct,
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
                        message=(
                            f"Dólar implícito para '{ticker}' (${implied_rate:.2f}) alineado con el benchmark "
                            f"(Desvío: {spread_pct:.2f}% <= {self.warning_spread_pct:.2f}%)."
                        ),
                        details={
                            "ticker": ticker,
                            "implied_rate": round(implied_rate, 2),
                            "benchmark_fx": round(benchmark_fx, 2),
                            "spread_pct": round(spread_pct, 2),
                        },
                    )
                )

        return results

