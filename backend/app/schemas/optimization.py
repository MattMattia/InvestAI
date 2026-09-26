from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class OptimizationMethod(str, Enum):
    MINIMUM_VARIANCE = "MINIMUM_VARIANCE"
    RISK_PARITY = "RISK_PARITY"


class TailRiskMetrics(BaseModel):
    """Métricas estandarizadas de riesgo de cola y distribución de retornos."""
    model_config = ConfigDict(frozen=True)

    skewness: float = Field(description="Asimetría de la distribución de retornos (Skewness)")
    kurtosis: float = Field(description="Exceso de curtosis relativo a la distribución normal")
    var_historical: float = Field(description="Value at Risk empírico / histórico (magnitud de pérdida)")
    var_parametric: float = Field(description="Value at Risk paramétrico gaussiano (magnitud de pérdida)")
    cvar_historical: float = Field(description="Conditional VaR / Expected Shortfall (magnitud de pérdida esperada)")
    confidence_level: float = Field(default=0.95, description="Nivel de confianza alpha utilizado (ej. 0.95)")


class OptimizationRequest(BaseModel):
    """Parámetros de configuración para la optimización cuantitativa de cartera."""
    model_config = ConfigDict(str_strip_whitespace=True)

    method: Optional[OptimizationMethod] = Field(
        default=OptimizationMethod.MINIMUM_VARIANCE,
        description="Algoritmo de optimización: 'MINIMUM_VARIANCE' o 'RISK_PARITY'"
    )
    returns: Optional[List[List[float]]] = Field(
        default=None,
        description="Matriz opcional de retornos periódicos de dimensión (T observaciones x N activos)"
    )
    covariance_matrix: Optional[List[List[float]]] = Field(
        default=None,
        description="Matriz de covarianza opcional de dimensión (N x N)"
    )
    tickers: Optional[List[str]] = Field(
        default=None,
        description="Subconjunto opcional de tickers a optimizar. Por defecto toma todos los activos de la cartera."
    )
    use_ledoit_wolf: bool = Field(
        default=True,
        description="Si es True, aplica contracción de Ledoit-Wolf para garantizar matrices no singulares y definidas positivas."
    )
    confidence_level: float = Field(
        default=0.95,
        ge=0.5,
        lt=1.0,
        description="Nivel de confianza para el cálculo de VaR y CVaR (ej. 0.95)"
    )


class OptimizationResult(BaseModel):
    """Resultado canónico del motor de optimización de carteras."""
    model_config = ConfigDict(frozen=True)

    portfolio_id: str = Field(description="Identificador del portafolio analizado")
    method: str = Field(description="Método de optimización ejecutado")
    weights: Dict[str, float] = Field(description="Ponderaciones asignadas a cada ticker (suman 1.0, long-only)")
    expected_annual_volatility: float = Field(description="Volatilidad anualizada estimada del portafolio optimizado")
    risk_contributions: Optional[Dict[str, float]] = Field(
        default=None,
        description="Contribución porcentual de cada activo al riesgo total de la cartera (suman 1.0)"
    )
    diversification_ratio: Optional[float] = Field(
        default=None,
        description="Ratio de diversificación de Choueifaty (DR > 1.0 implica diversificación no nula)"
    )
    tail_metrics: Optional[TailRiskMetrics] = Field(
        default=None,
        description="Evaluación de riesgo de cola de la cartera con las nuevas ponderaciones"
    )
