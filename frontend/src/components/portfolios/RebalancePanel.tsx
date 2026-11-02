/**
 * Comprehensive Rebalancing Panel Component for InvestAI Enterprise.
 * Features tolerance band configuration (tau), cash buffer controls,
 * RBAC authorization checks, and visual FSM order simulation preview.
 */

import React, { useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Coins,
  DollarSign,
  Lock,
  Play,
  RefreshCw,
  Scale,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { parseDecimalSafe } from "@/lib/formatters";
import { portfolioService } from "@/services/portfolioService";
import {
  Portfolio,
  RebalanceSimulationResult,
  ToleranceBandItem,
} from "@/types/api";
import { FSMOrdersPreviewTable } from "./FSMOrdersPreviewTable";
import { ToleranceBandVisualizer } from "./ToleranceBandVisualizer";

interface RebalancePanelProps {
  portfolio: Portfolio;
}

export const RebalancePanel: React.FC<RebalancePanelProps> = ({ portfolio }) => {
  const { isAuthenticated, isTrader, isAdmin, isViewer } = useAuth();
  const canRebalance = isAuthenticated && (isTrader || isAdmin);

  const [tolerancePct, setTolerancePct] = useState<number>(5.0);
  const [cashBufferPct, setCashBufferPct] = useState<number>(2.0);
  const [baseCurrency, setBaseCurrency] = useState<"ARS" | "USD">("ARS");

  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [simulationResult, setSimulationResult] =
    useState<RebalanceSimulationResult | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);

  const holdings = portfolio.holdings || [];
  const holdingsCount = holdings.length;

  // Compute total valuation and tolerance bands items for all active holdings
  const { bandItems, totalValuation, anyBreach } = useMemo(() => {
    let total = 0;
    const values = holdings.map((h) => {
      const qty = parseDecimalSafe(h.quantity);
      const price = parseDecimalSafe(h.current_price);
      const val = qty * price;
      total += val;
      return { ticker: h.asset_ticker, val };
    });

    if (total <= 0 || holdingsCount === 0) {
      return { bandItems: [], totalValuation: 0, anyBreach: false };
    }

    const equalTarget = Number((100 / holdingsCount).toFixed(2));
    let hasBreach = false;

    const items: ToleranceBandItem[] = values.map((v) => {
      const currentWeight = Number(((v.val / total) * 100).toFixed(2));
      const lower = Math.max(0, equalTarget - tolerancePct);
      const upper = Math.min(100, equalTarget + tolerancePct);
      const isBreached = currentWeight < lower || currentWeight > upper;
      if (isBreached) hasBreach = true;

      const breachDirection =
        currentWeight > upper
          ? "UPPER"
          : currentWeight < lower
          ? "LOWER"
          : "NONE";

      return {
        ticker: v.ticker,
        current_weight: currentWeight,
        target_weight: equalTarget,
        lower_band: lower,
        upper_band: upper,
        is_breached: isBreached,
        breach_direction: breachDirection,
        delta_weight: currentWeight - equalTarget,
      };
    });

    return { bandItems: items, totalValuation: total, anyBreach: hasBreach };
  }, [holdings, holdingsCount, tolerancePct]);

  // Handle Simulation Trigger
  const handleSimulate = async () => {
    if (!canRebalance || isSimulating) return;

    setIsSimulating(true);
    setSimulationError(null);

    try {
      const result = await portfolioService.simulateRebalance(portfolio.id, {
        tolerance_pct: tolerancePct,
        cash_buffer_pct: cashBufferPct,
        base_currency: baseCurrency,
      });
      setSimulationResult(result);
    } catch (err: unknown) {
      setSimulationError(
        err instanceof Error
          ? err.message
          : "Error al simular el rebalanceo de la cartera."
      );
    } finally {
      setIsSimulating(false);
    }
  };

  // Guardian: Portfolio without holdings or zero value
  if (holdingsCount === 0 || totalValuation <= 0) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-10 text-center space-y-4">
        <div className="h-12 w-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
          <Scale className="h-6 w-6" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-slate-200">
            Rebalanceo no disponible
          </h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto mt-1">
            Esta cartera no registra posiciones de títulos valores abiertas para evaluar desvíos respecto a bandas de tolerancia.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Control Configuration Bar */}
      <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          <div>
            <h2 className="text-base font-semibold text-white flex items-center gap-2">
              <Scale className="h-5 w-5 text-sky-400" />
              Parámetros de Rebalanceo por Bandas de Tolerancia
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Ajuste el rango de tolerancia ($\tau$) y el colchón de liquidez antes de simular la FSM
            </p>
          </div>

          {/* Currency Selector */}
          <div className="flex items-center p-0.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
            <button
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

        {/* Configuration Sliders & Presets */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Tolerance Band Preset Selector */}
          <div className="space-y-2">
            <label className="block text-xs font-medium text-slate-300 flex items-center justify-between">
              <span>Banda de Tolerancia ($\tau$)</span>
              <span className="font-mono text-sky-400 font-bold">
                ±{tolerancePct.toFixed(1)}%
              </span>
            </label>

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
            <label className="block text-xs font-medium text-slate-300 flex items-center justify-between">
              <span>Buffer de Liquidez Mínimo</span>
              <span className="font-mono text-emerald-400 font-bold">
                {cashBufferPct.toFixed(1)}%
              </span>
            </label>

            <div className="flex items-center gap-3">
              <input
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
                Se detectaron activos que perforan las bandas de tolerancia
              </span>
            ) : (
              <span className="text-emerald-400 flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="h-4 w-4" />
                Todas las posiciones se encuentran calibradas dentro de las bandas
              </span>
            )}
          </div>

          {canRebalance ? (
            <button
              onClick={handleSimulate}
              disabled={isSimulating}
              className="flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-lg shadow-sky-600/30 transition-all disabled:opacity-50 active:scale-95 shrink-0"
            >
              {isSimulating ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Simulando FSM...</span>
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  <span>Simular Rebalanceo</span>
                </>
              )}
            </button>
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

      {/* Error Banner */}
      {simulationError && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-3">
          <AlertCircle className="h-5 w-5 shrink-0 text-rose-400" />
          <span>{simulationError}</span>
        </div>
      )}

      {/* Visualizer: Range Bands */}
      <ToleranceBandVisualizer items={bandItems} tolerancePct={tolerancePct} />

      {/* Simulation Result: Proposed FSM Orders */}
      {simulationResult && (
        <FSMOrdersPreviewTable
          orders={simulationResult.orders}
          baseCurrency={baseCurrency}
        />
      )}
    </div>
  );
};
