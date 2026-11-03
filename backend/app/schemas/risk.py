from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RuleResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    rule_name: str
    severity: str
    passed: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class RiskAssessmentReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: str
    portfolio_name: str
    compliance_status: str
    total_rules_evaluated: int
    passed_rules_count: int
    failed_rules_count: int
    critical_alerts_count: int
    warning_alerts_count: int
    evaluated_at: datetime
    results: List[RuleResultResponse]
    snapshot_id: Optional[str] = None


class RiskAuditSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    portfolio_id: str
    compliance_status: str
    total_rules_evaluated: int
    critical_alerts_count: int
    notification_status: str
    created_at: datetime
    report_payload: Dict[str, Any]


class TargetAllocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticker: str = Field(..., description="Ticker del activo")
    target_weight: float = Field(..., ge=0.0, le=100.0, description="Ponderación objetivo % (0-100)")
    tolerance_band: Optional[float] = Field(default=None, ge=0.0, description="Banda de tolerancia % (+/-). Si se omite, se infiere del perfil del inversor.")

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        return v.strip().upper()


class RebalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    targets: Optional[List[TargetAllocationInput]] = Field(
        default=None,
        description="Lista de asignaciones objetivo manuales. Si se omite o se indica strategy cuantitativa, el motor 10Y calcula los pesos óptimos.",
    )
    strategy: Optional[str] = Field(
        default=None,
        description="Modelo cuantitativo 10Y: AUTO, CONSERVATIVE, MODERATE, AGGRESSIVE, EQUAL_WEIGHT, MIN_VARIANCE, RISK_PARITY, MAX_SHARPE",
    )
    tolerance_band: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Banda de tolerancia global % (+/-) aplicada cuando los pesos objetivo son generados por el motor 10Y",
    )
    custom_prices: Optional[Dict[str, float]] = Field(default=None, description="Precios de mercado opcionales")
    fx_ccl: float = Field(default=1300.0, gt=0.0, description="Dólar CCL de referencia")
    include_hold: bool = Field(default=False, description="Incluir órdenes de tipo HOLD")


class RebalanceOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    side: str
    current_weight: float
    target_weight: float
    delta_weight: float
    delta_amount: float
    estimated_shares: int
    price_used: float
    justification: str


class RebalancePlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    portfolio_id: str
    strategy_used: str = "CUSTOM_TARGETS"
    asset_metrics: List[Dict[str, Any]] = Field(default_factory=list)
    orders: List[RebalanceOrderResponse]
    total_buy_amount: float
    total_sell_amount: float
    net_cash_flow: float
    available_cash: float
    is_liquidity_sufficient: bool
    liquidity_warning: Optional[str] = None
