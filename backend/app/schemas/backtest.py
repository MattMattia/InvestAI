import datetime as dt
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RebalanceFrequency(str, Enum):
    """Frecuencia para la ejecución del rebalanceo de cartera."""
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class BacktestFrictionConfig(BaseModel):
    """Parámetros de fricción de mercado y costos de intermediación."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    alyc_commission_rate: float = Field(
        default=0.005,
        ge=0.0,
        lt=1.0,
        description="Tasa de comisión base de la ALyC (ej. 0.005 = 0.50%)",
    )
    min_commission_fee: float = Field(
        default=0.0,
        ge=0.0,
        description="Comisión mínima fija por operación en moneda base",
    )
    include_vat: bool = Field(
        default=True,
        description="Aplica IVA (21%) sobre la comisión del broker",
    )
    vat_rate: float = Field(
        default=0.21,
        ge=0.0,
        description="Alícuota impositiva de IVA",
    )
    market_fee_rate: float = Field(
        default=0.0009,
        ge=0.0,
        lt=1.0,
        description="Derechos de mercado y custodia BYMA/CNV (ej. 0.0009 = 0.09%)",
    )
    slippage_rate: float = Field(
        default=0.001,
        ge=0.0,
        lt=1.0,
        description="Deslizamiento estimado de precio de ejecución (ej. 0.001 = 0.10%)",
    )


class BacktestConfig(BaseModel):
    """Configuración determinista para la simulación histórica de cartera."""
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    initial_capital: float = Field(
        default=100_000.0,
        gt=0.0,
        description="Capital inicial de la cartera en moneda base",
    )
    tickers: List[str] = Field(
        min_length=1,
        description="Lista de activos/tickers que integran el universo elegible",
    )
    start_date: Union[dt.date, str] = Field(
        description="Fecha de inicio de la simulación histórica (YYYY-MM-DD o date)",
    )
    end_date: Union[dt.date, str] = Field(
        description="Fecha de finalización de la simulación histórica (YYYY-MM-DD o date)",
    )
    rebalance_frequency: RebalanceFrequency = Field(
        default=RebalanceFrequency.MONTHLY,
        description="Frecuencia periódica de rebalanceo",
    )
    risk_free_rate: float = Field(
        default=0.0,
        ge=0.0,
        description="Tasa libre de riesgo anualizada para Sharpe y Sortino (ej. 0.04 = 4% anual)",
    )
    friction_config: BacktestFrictionConfig = Field(
        default_factory=BacktestFrictionConfig,
        description="Configuración de fricciones de mercado y comisiones",
    )
    optimization_method: str = Field(
        default="MINIMUM_VARIANCE",
        description="Método de optimización cuantitativa: 'MINIMUM_VARIANCE', 'RISK_PARITY' o 'EQUAL_WEIGHTS'",
    )

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, v: List[str]) -> List[str]:
        cleaned = [t.strip().upper() for t in v if t and t.strip()]
        if not cleaned:
            raise ValueError("La lista de tickers no puede estar vacía.")
        return sorted(list(set(cleaned)))


class BacktestRunRequest(BacktestConfig):
    """Esquema de solicitud de ejecución de backtest con soporte de precios personalizados opcionales."""
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    portfolio_id: Optional[str] = Field(
        default=None,
        description="ID opcional de cartera asociada para validación de aislamiento tenant",
    )
    custom_prices: Optional[Dict[str, Dict[str, float]]] = Field(
        default=None,
        description="Diccionario opcional de precios {ticker: {YYYY-MM-DD: precio}}. Si se omite, se generan mediante Movimiento Browniano Geométrico.",
    )


class DailySnapshot(BaseModel):
    """Snapshot diario consolidado del estado liquidativo y tenencias de la cartera."""
    model_config = ConfigDict(frozen=True)

    date: Union[dt.date, str] = Field(description="Fecha del snapshot")
    portfolio_value: float = Field(description="Valor total liquidativo de la cartera (NAV) a precios de cierre")
    cash: float = Field(description="Caja líquida disponible en moneda base")
    holdings: Dict[str, float] = Field(default_factory=dict, description="Tenencias nominales por ticker")
    daily_return: float = Field(default=0.0, description="Retorno porcentual de la cartera respecto al día anterior")
    drawdown: float = Field(default=0.0, description="Drawdown relativo acumulado respecto al pico histórico máximo (<= 0.0)")


class BacktestPerformanceMetrics(BaseModel):
    """Métricas cuantitativas institucionales de rendimiento y riesgo de la cartera."""
    model_config = ConfigDict(frozen=True)

    total_return: float = Field(description="Retorno total acumulado ((Valor Final / Valor Inicial) - 1)")
    cagr: float = Field(description="Tasa de Crecimiento Anual Compuesto (CAGR)")
    annualized_volatility: float = Field(description="Volatilidad anualizada de los retornos diarios (sigma * sqrt(252))")
    sharpe_ratio: float = Field(description="Ratio de Sharpe anualizado con tasa libre de riesgo")
    sortino_ratio: float = Field(description="Ratio de Sortino anualizado con downside deviation")
    max_drawdown: float = Field(description="Máximo Drawdown histórico en magnitud absoluta (>= 0.0)")
    calmar_ratio: float = Field(description="Ratio de Calmar (CAGR / |MDD|)")
    total_frictions: float = Field(default=0.0, ge=0.0, description="Costos acumulados de fricción (comisiones, IVA, aranceles, slippage)")


class BacktestResult(BaseModel):
    """Resultado canónico consolidado de la simulación de backtesting."""
    model_config = ConfigDict(frozen=True)

    config: BacktestConfig = Field(description="Configuración de la simulación ejecutada")
    metrics: BacktestPerformanceMetrics = Field(description="Métricas consolidadas de rendimiento y riesgo")
    snapshots: List[DailySnapshot] = Field(default_factory=list, description="Serie temporal completa de snapshots diarios")
    orders: List[Dict[str, Any]] = Field(default_factory=list, description="Registro cronológico de órdenes ejecutadas")
