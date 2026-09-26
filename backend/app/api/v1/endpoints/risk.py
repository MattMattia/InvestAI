from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.domain.rules.concentration import (
    MaxAssetConcentrationRule,
    MaxSectorConcentrationRule,
)
from app.domain.rules.engine import RiskEngine
from app.domain.rules.fixed_income import MinFixedIncomeAllocationRule
from app.domain.rules.fx_ccl import ImplicitFXDivergenceRule
from app.domain.rules.valuation import ValuationAnomalyRule
from app.models.risk_audit import RiskAuditSnapshotModel
from app.models.user import UserModel
from app.schemas.risk import (
    RiskAssessmentReportResponse,
    RuleResultResponse,
)
from app.services.portfolio_service import (
    get_user_portfolio_or_404,
    orm_to_domain_portfolio,
)

router = APIRouter()


@router.get("/{id}/evaluate", response_model=RiskAssessmentReportResponse, status_code=status.HTTP_200_OK)
async def evaluate_portfolio_risk(
    id: str,
    fx_ccl: float = Query(default=1300.0, gt=0.0, description="Dólar CCL de referencia"),
    db: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_user),
) -> RiskAssessmentReportResponse:
    """
    Evaluates a portfolio against the full suite of deterministic risk rules:
    - Max asset & sector concentration
    - Fixed income allocation minimum
    - Valuation anomalies (PEG > 2.0, loss-making companies)
    - Implicit FX (CCL/MEP) divergence

    Persists an immutable audit snapshot into the database.
    """
    portfolio_model = await get_user_portfolio_or_404(id, current_user.id, db)
    domain_portfolio = orm_to_domain_portfolio(portfolio_model, fx_ccl=fx_ccl)

    engine = RiskEngine(
        rules=[
            MaxAssetConcentrationRule(),
            MaxSectorConcentrationRule(),
            MinFixedIncomeAllocationRule(),
            ValuationAnomalyRule(),
            ImplicitFXDivergenceRule(),
        ]
    )

    report = engine.evaluate(
        portfolio=domain_portfolio,
        context={"fx_ccl": fx_ccl},
    )

    results_payload = [
        {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "severity": r.severity.value,
            "passed": r.passed,
            "message": r.message,
            "details": r.details,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in report.results
    ]

    snapshot = RiskAuditSnapshotModel(
        portfolio_id=portfolio_model.id,
        compliance_status=report.compliance_status.value,
        total_rules_evaluated=report.total_rules_evaluated,
        critical_alerts_count=report.critical_alerts_count,
        notification_status="EVALUATED",
        report_payload={
            "portfolio_id": report.portfolio_id,
            "portfolio_name": report.portfolio_name,
            "compliance_status": report.compliance_status.value,
            "total_rules_evaluated": report.total_rules_evaluated,
            "passed_rules_count": report.passed_rules_count,
            "failed_rules_count": report.failed_rules_count,
            "critical_alerts_count": report.critical_alerts_count,
            "warning_alerts_count": report.warning_alerts_count,
            "evaluated_at": report.evaluated_at.isoformat(),
            "results": results_payload,
        },
    )
    db.add(snapshot)
    await db.flush()

    return RiskAssessmentReportResponse(
        portfolio_id=str(report.portfolio_id),
        portfolio_name=report.portfolio_name,
        compliance_status=report.compliance_status.value,
        total_rules_evaluated=report.total_rules_evaluated,
        passed_rules_count=report.passed_rules_count,
        failed_rules_count=report.failed_rules_count,
        critical_alerts_count=report.critical_alerts_count,
        warning_alerts_count=report.warning_alerts_count,
        evaluated_at=report.evaluated_at,
        results=[
            RuleResultResponse(
                rule_id=r.rule_id,
                rule_name=r.rule_name,
                severity=r.severity.value,
                passed=r.passed,
                message=r.message,
                details=r.details,
                timestamp=r.timestamp,
            )
            for r in report.results
        ],
        snapshot_id=snapshot.id,
    )
