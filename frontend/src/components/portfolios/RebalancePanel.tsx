/**
 * Comprehensive Rebalancing Panel Component for InvestAI Enterprise.
 * Features 10-Year Multi-Strategy Quantitative Optimization (Min-Variance,
 * Spinu Risk Parity, Markowitz Max-Sharpe, and 1/N Equal Weight),
 * 10Y fundamental & quantitative metrics table, tolerance band configuration (tau),
 * idempotent dry-run FSM order simulation preview, and 1-click batch settlement.
 */

import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Coins,
  Cpu,
  DollarSign,
  Lock,
  Play,
  RefreshCw,
  Scale,
  Zap,
} from "lucide-react";
import type React from "react";
import { useId, useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { inferAssetNativeCurrency, parseDecimalSafe } from "@/lib/formatters";
import { orderKeys, portfolioKeys } from "@/lib/queryKeys";
import { marketService } from "@/services/marketService";
import { orderService } from "@/services/orderService";
import { portfolioService } from "@/services/portfolioService";
import type {
  AssetFundamentalQuantMetrics,
  Portfolio,
  RebalanceQuantStrategy,
  RebalanceSimulationResult,
  ToleranceBandItem,
} from "@/types/api";
import { FSMOrdersPreviewTable } from "./FSMOrdersPreviewTable";
import { ToleranceBandVisualizer } from "./ToleranceBandVisualizer";

interface RebalancePanelProps {
  portfolio: Portfolio;
}

const QUANT_STRATEGIES: {
  id: RebalanceQuantStrategy;
  label: string;
  formula: string;
  badge: string;
}[] = [
  {
    id: "AUTO",
    label: "Automático (Perfil)",
    formula: "Acoplado al Perfil de Riesgo de la Cartera",
    badge: "Recomendado",
  },
  {
    id: "CONSERVATIVE",
    label: "Conservador (Min-Var 10Y)",
    formula: "min wᵀ Σ₁₀ᵧ w + Premio Renta Fija / Baja Beta",
    badge: "Preservación",
  },
  {
    id: "MODERATE",
    label: "Moderado (Risk Parity 10Y)",
    formula: "Paridad de Riesgo Convexa (Spinu) ponderada por Sharpe y ROE/TIR",
    badge: "Balanceado",
  },
  {
    id: "AGGRESSIVE",
    label: "Agresivo (Max-Sharpe 10Y)",
    formula: "max (wᵀ μ_quant - r_f) / √(wᵀ Σ₁₀ᵧ w) + Crecimiento 10Y",
    badge: "Crecimiento",
  },
  {
    id: "EQUAL_WEIGHT",
    label: "Equiponderado (1/N)",
    formula: "Asignación Uniforme w_i = 100% / N",
    badge: "Base 1/N",
  },
];

function computeClientSide10YTargetWeights(
  metricsList: AssetFundamentalQuantMetrics[],
  strategy: RebalanceQuantStrategy,
  investorProfile: string,
): Record<string, number> {
  const n = metricsList.length;
  if (n === 0) return {};
  if (n === 1) return { [metricsList[0].ticker]: 100.0 };

  let resolved = strategy;
  if (strategy === "AUTO") {
    const prof = (investorProfile || "MODERATE").toUpperCase();
    if (prof === "CONSERVATIVE") resolved = "CONSERVATIVE";
    else if (prof === "AGGRESSIVE") resolved = "AGGRESSIVE";
    else resolved = "MODERATE";
  }

  let rawScores: number[] = [];
  if (resolved === "EQUAL_WEIGHT") {
    rawScores = metricsList.map(() => 1.0 / n);
  } else if (resolved === "CONSERVATIVE") {
    rawScores = metricsList.map((m) => {
      const sigma = Math.max(0.1, m.volatility_annualized || 0.3);
      const mdd = Math.max(0.1, m.max_drawdown || 0.35);
      const beta = Math.max(0.3, m.beta_market || 1.0);
      const typeBonus = m.asset_type === "BOND" ? 1.65 : beta < 0.95 ? 1.25 : 0.75;
      return (1.0 / (sigma * sigma)) * (1.0 / mdd) * (1.0 / beta) * typeBonus;
    });
  } else if (resolved === "MODERATE") {
    rawScores = metricsList.map((m) => {
      const sigma = Math.max(0.12, m.volatility_annualized || 0.28);
      const sharpe = Math.max(0.15, m.sharpe_ratio || 0.4);
      const muQ = Math.max(0.08, m.composite_quant_return || 0.14);
      const budget = Math.sqrt(sharpe * muQ);
      return budget / sigma;
    });
  } else {
    // AGGRESSIVE (Max-Sharpe + 10Y Growth / ROE)
    rawScores = metricsList.map((m) => {
      const cagr = Math.max(0.05, m.cagr_annualized || 0.14);
      const sharpe = Math.max(0.15, m.sharpe_ratio || 0.4);
      const roe = Math.max(8.0, m.roe_pct ?? 16.0) / 100.0;
      const growthMult = m.asset_type === "BOND" ? 0.55 : 1.35;
      return cagr ** 1.5 * sharpe * (1.0 + 0.6 * Math.min(1.0, roe)) * growthMult;
    });
  }

  const sumRaw = rawScores.reduce((a, b) => a + b, 0) || 1.0;
  const minFloor = Math.min(0.04, 0.5 / n);
  const clipped = rawScores.map((s) => Math.min(0.65, Math.max(minFloor, s / sumRaw)));
  const sumClipped = clipped.reduce((a, b) => a + b, 0) || 1.0;
  const rounded = clipped.map((c) => Number(((c / sumClipped) * 100.0).toFixed(2)));
  const diff = Number((100.0 - rounded.reduce((a, b) => a + b, 0)).toFixed(2));
  let maxIdx = 0;
  for (let i = 1; i < rounded.length; i++) {
    if (rounded[i] > rounded[maxIdx]) maxIdx = i;
  }
  rounded[maxIdx] = Number((rounded[maxIdx] + diff).toFixed(2));

  const map: Record<string, number> = {};
  metricsList.forEach((m, idx) => {
    map[m.ticker] = rounded[idx];
  });
  return map;
}

export const RebalancePanel: React.FC<RebalancePanelProps> = ({ portfolio }) => {
  const uid = useId();
  const queryClient = useQueryClient();
  const { isAuthenticated, isTrader, isAdmin, isViewer } = useAuth();
  const canRebalance = isAuthenticated && (isTrader || isAdmin);

  const [selectedStrategy, setSelectedStrategy] = useState<RebalanceQuantStrategy>("AUTO");
  const [tolerancePct, setTolerancePct] = useState<number>(5.0);
  const [cashBufferPct, setCashBufferPct] = useState<number>(2.0);
  const [baseCurrency, setBaseCurrency] = useState<"ARS" | "USD">("ARS");

  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [isExecutingBatch, setIsExecutingBatch] = useState<boolean>(false);
  const [simulationResult, setSimulationResult] = useState<RebalanceSimulationResult | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [executionSuccessMsg, setExecutionSuccessMsg] = useState<string | null>(null);

  const holdings = portfolio.holdings || [];
  const holdingsCount = holdings.length;

  // Compute 10Y metrics, optimal target weights, and tolerance bands for all active holdings
  const { bandItems, enrichedMetrics, totalValuation, anyBreach } = useMemo(() => {
    let total = 0;
    const values = holdings.map((h) => {
      const qty = parseDecimalSafe(h.quantity);
      const price = parseDecimalSafe(h.current_price);
      const val = qty * price;
      total += val;
      return { ticker: h.asset_ticker.trim().toUpperCase(), val };
    });

    if (total <= 0 || holdingsCount === 0) {
      return {
        bandItems: [],
        enrichedMetrics: [],
        totalValuation: 0,
        anyBreach: false,
      };
    }

    const rawMetrics = values.map((v) => marketService.getCalibrated10YMetricsSync(v.ticker));
    const clientWeightsMap = computeClientSide10YTargetWeights(
      rawMetrics,
      selectedStrategy,
      portfolio.investor_profile || "MODERATE",
    );

    let hasBreach = false;
    const metricsOut: AssetFundamentalQuantMetrics[] = [];

    const items: ToleranceBandItem[] = values.map((v, idx) => {
      const currentWeight = Number(((v.val / total) * 100).toFixed(2));
      // If backend returned asset_metrics for the current strategy, prefer backend target_weight
      const backendMetric = simulationResult?.asset_metrics?.find((am) => am.ticker === v.ticker);
      const targetWeight =
        backendMetric?.target_weight !== undefined
          ? Number(backendMetric.target_weight.toFixed(2))
          : (clientWeightsMap[v.ticker] ?? Number((100 / holdingsCount).toFixed(2)));

      const lower = Number(Math.max(0, targetWeight - tolerancePct).toFixed(2));
      const upper = Number(Math.min(100, targetWeight + tolerancePct).toFixed(2));
      const isBreached = currentWeight < lower || currentWeight > upper;
      if (isBreached) hasBreach = true;

      const breachDirection =
        currentWeight > upper ? "UPPER" : currentWeight < lower ? "LOWER" : "NONE";

      metricsOut.push({
        ...(backendMetric || rawMetrics[idx]),
        current_weight: currentWeight,
        target_weight: targetWeight,
      });

      return {
        ticker: v.ticker,
        current_weight: currentWeight,
        target_weight: targetWeight,
        lower_band: lower,
        upper_band: upper,
        is_breached: isBreached,
        breach_direction: breachDirection,
        delta_weight: Number((currentWeight - targetWeight).toFixed(2)),
      };
    });

    return {
      bandItems: items,
      enrichedMetrics: metricsOut,
      totalValuation: total,
      anyBreach: hasBreach,
    };
  }, [
    holdings,
    holdingsCount,
    tolerancePct,
    selectedStrategy,
    portfolio.investor_profile,
    simulationResult,
  ]);

  // Handle Idempotent Dry-Run Simulation Trigger with 10Y Quantitative Strategy
  const handleSimulate = async () => {
    if (!canRebalance || isSimulating) return;

    setIsSimulating(true);
    setSimulationError(null);
    setExecutionSuccessMsg(null);

    try {
      const result = await portfolioService.simulateRebalance(portfolio.id, {
        tolerance_pct: tolerancePct,
        cash_buffer_pct: cashBufferPct,
        base_currency: baseCurrency,
        strategy: selectedStrategy,
      });
      setSimulationResult(result);
    } catch (err: unknown) {
      setSimulationError(
        err instanceof Error
          ? err.message
          : "Error al simular el rebalanceo cuantitativo de la cartera.",
      );
    } finally {
      setIsSimulating(false);
    }
  };

  // Handle 1-Click Batch Execution & Settlement of Proposed Rebalance Orders
  const handleExecuteRebalanceOrders = async () => {
    if (
      !canRebalance ||
      isExecutingBatch ||
      !simulationResult ||
      simulationResult.orders.length === 0
    ) {
      return;
    }

    setIsExecutingBatch(true);
    setSimulationError(null);
    setExecutionSuccessMsg(null);

    try {
      let executedCount = 0;
      for (const proposed of simulationResult.orders) {
        if (proposed.side !== "BUY" && proposed.side !== "SELL") continue;
        const shares = Math.max(1, Math.round(parseDecimalSafe(proposed.estimated_shares) || 1));
        const price = Math.max(0.01, parseDecimalSafe(proposed.price_used) || 1.0);
        const cur = inferAssetNativeCurrency(proposed.ticker, "ARS");

        const created = await orderService.createOrder({
          portfolio_id: portfolio.id,
          ticker: proposed.ticker,
          side: proposed.side,
          order_type: "MARKET",
          quantity: shares,
          price,
          currency: cur,
          justification:
            proposed.justification ||
            `Rebalanceo cuantitativo 10Y (${selectedStrategy}, ±${tolerancePct.toFixed(1)}%)`,
        });
        await orderService.executeOrder(created.id);
        executedCount += 1;
      }

      setSimulationResult((prev) =>
        prev
          ? {
              ...prev,
              orders: prev.orders.map((o) => ({
                ...o,
                status: "EXECUTED",
              })),
            }
          : null,
      );

      setExecutionSuccessMsg(
        `Se ejecutaron y liquidaron ${executedCount} órdenes de rebalanceo cuantitativo en la cartera (Estado FSM: EXECUTED).`,
      );

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() }),
        queryClient.invalidateQueries({
          queryKey: portfolioKeys.detail(portfolio.id),
        }),
        queryClient.invalidateQueries({ queryKey: orderKeys.all }),
      ]);
    } catch (err: unknown) {
      setSimulationError(
        err instanceof Error
          ? err.message
          : "Error al ejecutar y liquidar las órdenes de rebalanceo.",
      );
    } finally {
      setIsExecutingBatch(false);
    }
  };

  if (holdingsCount === 0 || totalValuation <= 0) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-10 text-center space-y-4">
        <div className="h-12 w-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
          <Scale className="h-6 w-6" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-slate-200">Rebalanceo no disponible</h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto mt-1">
            Esta cartera no registra posiciones de títulos valores abiertas para evaluar desvíos
            respecto a bandas de tolerancia.
          </p>
        </div>
      </div>
    );
  }

  const activeStratInfo =
    QUANT_STRATEGIES.find((s) => s.id === selectedStrategy) || QUANT_STRATEGIES[0];

  return (
    <div className="space-y-6">
      {/* Control Configuration Bar */}
      <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          <div>
            <h2 className="text-base font-semibold text-white flex items-center gap-2">
              <Scale className="h-5 w-5 text-sky-400" />
              Motor Cuantitativo de Rebalanceo (10 Años de Historia + Fundamentales)
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Seleccione el modelo matemático (Σ₁₀ᵧ + indicadores fundamentales) y la banda de
              tolerancia (τ)
            </p>
          </div>

          {/* Currency Selector */}
          <div className="flex items-center p-0.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
            <button
              type="button"
              onClick={() => setBaseCurrency("ARS")}
              className={`flex items-center gap-1 px-3 py-1.5 rounded-md transition-all ${
                baseCurrency === "ARS"
                  ? "bg-emerald-600/20 text-emerald-300 font-semibold border border-emerald-500/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Coins className="h-3 w-3" />
              <span>ARS</span>
            </button>
            <button
              type="button"
              onClick={() => setBaseCurrency("USD")}
              className={`flex items-center gap-1 px-3 py-1.5 rounded-md transition-all ${
                baseCurrency === "USD"
                  ? "bg-sky-600/20 text-sky-300 font-semibold border border-sky-500/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <DollarSign className="h-3 w-3" />
              <span>USD</span>
            </button>
          </div>
        </div>

        {/* 10-Year Quantitative Strategy Selector */}
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5 text-sky-400" />
              <span>Modelo Cuantitativo de Optimización (Ventana 10 Años)</span>
            </span>
            <span className="text-[11px] font-mono text-sky-400 bg-sky-500/10 border border-sky-500/20 px-2.5 py-0.5 rounded-full">
              Fórmula Activa: {activeStratInfo.formula}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
            {QUANT_STRATEGIES.map((st) => {
              const active = selectedStrategy === st.id;
              return (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => {
                    setSelectedStrategy(st.id);
                    setSimulationResult(null);
                  }}
                  className={`p-3 rounded-xl border text-left transition-all flex flex-col justify-between gap-1.5 ${
                    active
                      ? "bg-sky-600/20 border-sky-500 text-white shadow-md shadow-sky-900/20"
                      : "bg-slate-950/60 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-semibold truncate">{st.label}</span>
                    <span
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                        active ? "bg-sky-500/30 text-sky-200" : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {st.badge}
                    </span>
                  </div>
                  <p className="text-[10px] font-mono text-slate-400 line-clamp-1">{st.formula}</p>
                </button>
              );
            })}
          </div>
        </div>

        {/* Configuration Sliders & Presets */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
          {/* Tolerance Band Preset Selector */}
          <div className="space-y-2">
            <span className="block text-xs font-medium text-slate-300 flex items-center justify-between">
              <span>Banda de Tolerancia (τ)</span>
              <span className="font-mono text-sky-400 font-bold">±{tolerancePct.toFixed(1)}%</span>
            </span>

            <div className="grid grid-cols-3 gap-2">
              {[2.0, 5.0, 10.0].map((val) => (
                <button
                  key={val}
                  type="button"
                  onClick={() => setTolerancePct(val)}
                  className={`py-2 px-3 text-xs font-mono font-medium rounded-lg border text-center transition-all ${
                    tolerancePct === val
                      ? "bg-sky-600/20 text-sky-300 border-sky-500 shadow-sm"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/40"
                  }`}
                >
                  ±{val}%
                </button>
              ))}
            </div>
          </div>

          {/* Cash Buffer */}
          <div className="space-y-2">
            <label
              htmlFor={`${uid}-cash-buffer`}
              className="block text-xs font-medium text-slate-300 flex items-center justify-between"
            >
              <span>Buffer de Liquidez Mínimo</span>
              <span className="font-mono text-emerald-400 font-bold">
                {cashBufferPct.toFixed(1)}%
              </span>
            </label>

            <div className="flex items-center gap-3">
              <input
                id={`${uid}-cash-buffer`}
                type="range"
                min="0"
                max="10"
                step="0.5"
                value={cashBufferPct}
                onChange={(e) => setCashBufferPct(Number(e.target.value))}
                className="w-full accent-sky-500 bg-slate-950 rounded-lg h-2 cursor-pointer"
              />
              <span className="text-xs font-mono text-slate-400 w-12 text-right">
                {cashBufferPct.toFixed(1)}%
              </span>
            </div>
          </div>
        </div>

        {/* Simulation Actions & RBAC Notice */}
        <div className="pt-3 border-t border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs">
            {anyBreach ? (
              <span className="text-amber-400 flex items-center gap-1.5 font-medium">
                <AlertTriangle className="h-4 w-4" />
                Se detectaron activos que perforan las bandas óptimas 10Y (τ = ±
                {tolerancePct.toFixed(1)}%)
              </span>
            ) : (
              <span className="text-emerald-400 flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="h-4 w-4" />
                Todas las posiciones se encuentran dentro de las bandas óptimas 10Y
              </span>
            )}
          </div>

          {canRebalance ? (
            <div className="flex flex-wrap items-center gap-2.5">
              <button
                type="button"
                onClick={handleSimulate}
                disabled={isSimulating || isExecutingBatch}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-lg shadow-sky-600/30 transition-all disabled:opacity-50 active:scale-95 shrink-0"
              >
                {isSimulating ? (
                  <>
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    <span>Optimizando Σ₁₀ᵧ (Dry-Run)...</span>
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" />
                    <span>Simular Rebalanceo 10Y</span>
                  </>
                )}
              </button>

              {simulationResult && simulationResult.orders.length > 0 && (
                <button
                  type="button"
                  onClick={handleExecuteRebalanceOrders}
                  disabled={isExecutingBatch || isSimulating}
                  className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-lg shadow-emerald-600/30 transition-all disabled:opacity-50 active:scale-95 shrink-0"
                >
                  {isExecutingBatch ? (
                    <>
                      <RefreshCw className="h-4 w-4 animate-spin" />
                      <span>Liquidando Órdenes...</span>
                    </>
                  ) : (
                    <>
                      <Zap className="h-4 w-4" />
                      <span>Ejecutar Órdenes de Rebalanceo ({simulationResult.orders.length})</span>
                    </>
                  )}
                </button>
              )}
            </div>
          ) : isAuthenticated && isViewer ? (
            <div
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-800 text-slate-400 text-xs cursor-not-allowed border border-slate-700"
              title="El rol VIEWER no tiene autorización para generar órdenes de rebalanceo"
            >
              <Lock className="h-3.5 w-3.5 text-amber-400" />
              <span>Simulación Bloqueada (Rol VIEWER)</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Lock className="h-3.5 w-3.5" />
              <span>Inicia sesión con rol TRADER o ADMIN para operar</span>
            </div>
          )}
        </div>
      </div>

      {/* Execution Success Banner */}
      {executionSuccessMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400" />
          <span>{executionSuccessMsg}</span>
        </div>
      )}

      {/* Error Banner */}
      {simulationError && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-3">
          <AlertCircle className="h-5 w-5 shrink-0 text-rose-400" />
          <span>{simulationError}</span>
        </div>
      )}

      {/* 10-Year Quantitative & Fundamental Matrix Table */}
      <div className="rounded-xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-emerald-400" />
              Matriz de Fundamentos Cuantitativos (10 Años) y Ponderaciones Óptimas
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Parámetros empíricos en moneda dura (USD/CCL) e indicadores fundamentales utilizados
              para derivar W_target
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-950 border border-slate-800 text-[11px] font-mono text-slate-300">
            <Activity className="h-3.5 w-3.5 text-sky-400" />
            <span>Estrategia: {simulationResult?.strategy_used || activeStratInfo.label}</span>
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                <th className="py-3 px-4">Instrumento</th>
                <th className="py-3 px-3">Ventana 10Y</th>
                <th className="py-3 px-3 text-right">Volatilidad (σ)</th>
                <th className="py-3 px-3 text-right">CAGR 10Y (USD)</th>
                <th className="py-3 px-3 text-right">Sharpe / Max DD</th>
                <th className="py-3 px-4">Indicadores Fundamentales</th>
                <th className="py-3 px-4 text-right">W_act → W_target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-xs font-mono">
              {enrichedMetrics.map((m) => {
                const currW = m.current_weight ?? 0;
                const targW = m.target_weight ?? 0;
                const delta = Number((targW - currW).toFixed(2));
                const isBond = m.asset_type === "BOND";
                return (
                  <tr key={m.ticker} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white">{m.ticker}</span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                            m.asset_type === "CEDEAR"
                              ? "bg-violet-500/15 text-violet-300 border border-violet-500/30"
                              : m.asset_type === "BOND"
                                ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                : "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                          }`}
                        >
                          {m.asset_type}
                        </span>
                      </div>
                      <p className="text-[11px] font-sans text-slate-400 truncate max-w-[180px]">
                        {m.name}
                      </p>
                    </td>
                    <td className="py-3 px-3 text-slate-300">
                      <div>{m.history_years_available.toFixed(1)} años</div>
                      <div className="text-[10px] text-slate-500">
                        {m.data_points_count} ruedas ({m.history_start_date})
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right text-amber-300">
                      {(m.volatility_annualized * 100).toFixed(1)}%
                      <div className="text-[10px] text-slate-500">
                        β = {m.beta_market.toFixed(2)}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right text-emerald-400 font-semibold">
                      +{(m.cagr_annualized * 100).toFixed(1)}%
                      <div className="text-[10px] text-slate-500">
                        μ_q = +{(m.composite_quant_return * 100).toFixed(1)}%
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right">
                      <span className="text-sky-300 font-semibold">
                        {m.sharpe_ratio.toFixed(2)}
                      </span>
                      <div className="text-[10px] text-rose-400">
                        DD: -{(m.max_drawdown * 100).toFixed(1)}%
                      </div>
                    </td>
                    <td className="py-3 px-4 text-[11px]">
                      {isBond ? (
                        <div className="flex flex-wrap gap-1.5">
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-amber-300">
                            TIR: {m.ytm_tir_pct?.toFixed(2) ?? "14.5"}%
                          </span>
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300">
                            Dur: {m.modified_duration?.toFixed(2) ?? "2.5"}y
                          </span>
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-emerald-300">
                            Paridad: {m.parity_pct?.toFixed(1) ?? "68.5"}%
                          </span>
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-sky-300">
                            P/E: {m.pe_ratio?.toFixed(1) ?? "12.0"}x
                          </span>
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-emerald-300">
                            ROE: {m.roe_pct?.toFixed(1) ?? "18.0"}%
                          </span>
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-slate-300">
                            P/B: {m.pb_ratio?.toFixed(1) ?? "1.8"}x
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <span className="text-slate-400">{currW.toFixed(2)}%</span>
                        <span className="text-slate-600">→</span>
                        <span className="text-white font-bold">{targW.toFixed(2)}%</span>
                      </div>
                      <div
                        className={`text-[10px] font-semibold ${
                          Math.abs(delta) > tolerancePct
                            ? delta > 0
                              ? "text-emerald-400"
                              : "text-rose-400"
                            : "text-slate-500"
                        }`}
                      >
                        {delta > 0 ? `+${delta.toFixed(2)}%` : `${delta.toFixed(2)}%`}{" "}
                        {Math.abs(delta) > tolerancePct
                          ? delta > 0
                            ? "(COMPRA)"
                            : "(VENTA)"
                          : "(EN BANDA)"}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Visualizer: Range Bands */}
      <ToleranceBandVisualizer items={bandItems} tolerancePct={tolerancePct} />

      {/* Simulation Result: Proposed FSM Orders */}
      {simulationResult && (
        <FSMOrdersPreviewTable orders={simulationResult.orders} baseCurrency={baseCurrency} />
      )}
    </div>
  );
};
