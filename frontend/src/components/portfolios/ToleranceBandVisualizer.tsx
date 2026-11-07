/**
 * Tolerance Band Visualizer for Portfolio Holdings in InvestAI Enterprise.
 * Renders horizontal range intervals [W_target - tau, W_target + tau],
 * clamped current positions, and real-time breach detection chips.
 */

import { AlertCircle, AlertTriangle, CheckCircle2, Sliders } from "lucide-react";
import type React from "react";
import type { ToleranceBandItem } from "@/types/api";

interface ToleranceBandVisualizerProps {
  items: ToleranceBandItem[];
  tolerancePct: number;
}

export const ToleranceBandVisualizer: React.FC<ToleranceBandVisualizerProps> = ({
  items,
  tolerancePct,
}) => {
  if (items.length === 0) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-8 text-center text-xs text-slate-400 font-mono">
        No hay posiciones para evaluar bandas de tolerancia en este portafolio.
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-6 shadow-xl space-y-6">
      {/* Title & Legend Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-800">
        <div>
          <h3 className="font-semibold text-sm text-slate-100 flex items-center gap-2">
            <Sliders className="h-4 w-4 text-sky-400" />
            Bandas de Tolerancia Cuantitativas (τ = ±{tolerancePct.toFixed(1)}%)
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Monitoreo continuo de desvíos respecto a la ponderación objetivo
          </p>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 text-[11px] font-mono text-slate-400 select-none">
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-5 rounded bg-emerald-500/20 border border-emerald-500/40 inline-block" />
            <span>Banda Permitida</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-1 bg-sky-400 rounded inline-block" />
            <span>Target ($W_t$)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-white ring-2 ring-sky-500 inline-block" />
            <span>Actual ($W_c$)</span>
          </div>
        </div>
      </div>

      {/* Items List */}
      <div className="space-y-5">
        {items.map((item) => {
          const clampedCurrent = Math.min(100, Math.max(0, item.current_weight));
          const clampedTarget = Math.min(100, Math.max(0, item.target_weight));
          const lower = Math.max(0, item.lower_band);
          const upper = Math.min(100, item.upper_band);
          const bandWidth = Math.max(0, upper - lower);

          return (
            <div
              key={item.ticker}
              className="p-3.5 rounded-lg bg-slate-950/70 border border-slate-800/80 space-y-2.5"
            >
              {/* Header: Ticker, Numeric Weights & Semaphoric Chip */}
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2.5">
                  <span className="font-bold text-white font-mono text-sm">{item.ticker}</span>
                  <span className="text-slate-400 font-mono text-[11px]">
                    Target: {item.target_weight.toFixed(1)}% ({item.lower_band.toFixed(1)}% -{" "}
                    {item.upper_band.toFixed(1)}
                    %)
                  </span>
                </div>

                <div className="flex items-center gap-3 font-mono">
                  <span className="text-slate-200 font-semibold text-xs">
                    Actual: {item.current_weight.toFixed(1)}%
                  </span>

                  {item.is_breached && item.breach_direction === "UPPER" ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30">
                      <AlertCircle className="h-3 w-3 text-rose-400" />
                      BREACH (Exceso +{item.delta_weight.toFixed(1)}%)
                    </span>
                  ) : item.is_breached && item.breach_direction === "LOWER" ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30">
                      <AlertTriangle className="h-3 w-3 text-amber-400" />
                      BREACH (Déficit {item.delta_weight.toFixed(1)}%)
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                      <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                      CALIBRADO
                    </span>
                  )}
                </div>
              </div>

              {/* Horizontal Range Visualization */}
              <div className="relative w-full h-5 bg-slate-900 rounded-md overflow-hidden border border-slate-800">
                {/* Allowed Band Range (Shaded green zone) */}
                <div
                  className="absolute top-0 bottom-0 bg-emerald-500/20 border-x border-emerald-500/50"
                  style={{
                    left: `${lower}%`,
                    width: `${bandWidth}%`,
                  }}
                  title={`Banda permitida: ${lower.toFixed(1)}% a ${upper.toFixed(1)}%`}
                />

                {/* Target Marker (Sky vertical tick) */}
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-sky-400 z-10"
                  style={{ left: `${clampedTarget}%` }}
                  title={`Objetivo: ${clampedTarget.toFixed(1)}%`}
                />

                {/* Current Weight Marker */}
                <div
                  className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-20"
                  style={{ left: `${clampedCurrent}%` }}
                  title={`Ponderación Actual: ${clampedCurrent.toFixed(1)}%`}
                >
                  <div
                    className={`h-3.5 w-3.5 rounded-full border-2 shadow-md ${
                      item.is_breached && item.breach_direction === "UPPER"
                        ? "bg-rose-500 border-white ring-2 ring-rose-500/40"
                        : item.is_breached && item.breach_direction === "LOWER"
                          ? "bg-amber-500 border-white ring-2 ring-amber-500/40"
                          : "bg-emerald-500 border-white ring-2 ring-emerald-500/40"
                    }`}
                  />
                </div>
              </div>

              {/* Axis 0% to 100% indicators */}
              <div className="flex justify-between text-[9px] font-mono text-slate-400 px-0.5">
                <span>0%</span>
                <span>25%</span>
                <span>50%</span>
                <span>75%</span>
                <span>100%</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
