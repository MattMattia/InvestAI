import React, { useState, useEffect } from "react";
import { Holding, RebalanceOrder, RebalancePlan, TargetAllocationInput } from "../types/portfolio";
import { Scale, ArrowRight, CheckCircle2, AlertTriangle, X } from "lucide-react";

interface RebalanceModalProps {
  isOpen: boolean;
  onClose: () => void;
  holdings: Holding[];
  onGeneratePlan: (targets: TargetAllocationInput[]) => Promise<RebalancePlan>;
}

export const RebalanceModal: React.FC<RebalanceModalProps> = ({
  isOpen,
  onClose,
  holdings,
  onGeneratePlan,
}) => {
  const [targets, setTargets] = useState<TargetAllocationInput[]>([]);
  const [plan, setPlan] = useState<RebalancePlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize targets based on existing holdings
  useEffect(() => {
    if (holdings.length > 0) {
      const equalWeight = parseFloat((100 / holdings.length).toFixed(1));
      setTargets(
        holdings.map((h) => ({
          ticker: h.asset_ticker,
          target_weight: equalWeight,
          tolerance_band: 5.0,
        }))
      );
    }
  }, [holdings]);

  if (!isOpen) return null;

  const handleWeightChange = (index: number, val: number) => {
    const updated = [...targets];
    updated[index].target_weight = val;
    setTargets(updated);
  };

  const handleBandChange = (index: number, val: number) => {
    const updated = [...targets];
    updated[index].tolerance_band = val;
    setTargets(updated);
  };

  const totalTargetWeight = targets.reduce((acc, t) => acc + (t.target_weight || 0), 0);

  const handleCalculate = async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await onGeneratePlan(targets);
      setPlan(res);
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || "Error al calcular el rebalanceo.");
    } finally {
      setLoading(false);
    }
  };

  const getSideBadge = (side: RebalanceOrder["side"]) => {
    switch (side) {
      case "BUY":
        return <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">COMPRAR</span>;
      case "SELL":
        return <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-rose-950 text-rose-300 border border-rose-800">VENDER</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">MANTENER</span>;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-3xl w-full shadow-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-700">
          <div className="flex items-center space-x-2">
            <Scale className="w-5 h-5 text-sky-400" />
            <h3 className="text-lg font-bold text-white">Rebalanceo por Bandas de Tolerancia</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="overflow-y-auto space-y-5 py-4 flex-1">
          {/* Targets Configuration Table */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                1. Asignaciones Objetivo (% Target) y Bandas de Tolerancia (+/- %)
              </h4>
              <div
                className={`text-xs font-mono font-bold ${
                  Math.abs(totalTargetWeight - 100) < 0.1 ? "text-emerald-400" : "text-amber-400"
                }`}
              >
                Suma Target: {totalTargetWeight.toFixed(1)}% {Math.abs(totalTargetWeight - 100) >= 0.1 && "(Sugerido: 100%)"}
              </div>
            </div>

            <div className="border border-slate-700 rounded-lg overflow-hidden bg-slate-900/50">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-900 text-slate-400 font-semibold border-b border-slate-700">
                  <tr>
                    <th className="py-2.5 px-3">Ticker</th>
                    <th className="py-2.5 px-3">Peso Actual</th>
                    <th className="py-2.5 px-3">Ponderación Objetivo (%)</th>
                    <th className="py-2.5 px-3">Banda Tolerancia (+/- %)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/60">
                  {targets.map((t, idx) => {
                    const h = holdings.find((item) => item.asset_ticker === t.ticker);
                    return (
                      <tr key={t.ticker}>
                        <td className="py-2.5 px-3 font-bold text-white">{t.ticker}</td>
                        <td className="py-2.5 px-3 font-mono text-slate-300">
                          {h?.weight_pct ? `${h.weight_pct.toFixed(1)}%` : "0.0%"}
                        </td>
                        <td className="py-2.5 px-3">
                          <input
                            type="number"
                            min="0"
                            max="100"
                            step="0.5"
                            value={t.target_weight}
                            onChange={(e) => handleWeightChange(idx, parseFloat(e.target.value) || 0)}
                            className="w-24 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono focus:outline-none focus:border-sky-500"
                          />
                        </td>
                        <td className="py-2.5 px-3">
                          <input
                            type="number"
                            min="0"
                            max="20"
                            step="0.5"
                            value={t.tolerance_band}
                            onChange={(e) => handleBandChange(idx, parseFloat(e.target.value) || 0)}
                            className="w-20 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono focus:outline-none focus:border-sky-500"
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={handleCalculate}
              disabled={loading || targets.length === 0}
              className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-semibold px-4 py-2 rounded-lg transition flex items-center space-x-1.5"
            >
              <span>{loading ? "Calculando Órdenes..." : "Calcular Plan de Rebalanceo"}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>

          {error && (
            <div className="p-3 bg-rose-950/60 border border-rose-800 rounded-lg text-rose-300 text-xs">
              {error}
            </div>
          )}

          {/* Results: Generated Orders */}
          {plan && (
            <div className="space-y-3 pt-2 border-t border-slate-700">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                2. Órdenes Deterministas Sugeridas ({plan.orders.length})
              </h4>

              {/* Liquidity Check Card */}
              <div
                className={`p-3 rounded-lg border text-xs flex items-center justify-between ${
                  plan.is_liquidity_sufficient
                    ? "bg-emerald-950/40 border-emerald-800 text-emerald-200"
                    : "bg-amber-950/40 border-amber-800 text-amber-200"
                }`}
              >
                <div className="flex items-center space-x-2">
                  {plan.is_liquidity_sufficient ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  ) : (
                    <AlertTriangle className="w-5 h-5 text-amber-400" />
                  )}
                  <div>
                    <span className="font-bold">
                      {plan.is_liquidity_sufficient
                        ? "Conservación de Liquidez: Suficiente"
                        : "Alerta de Liquidez Insuficiente"}
                    </span>
                    <p className="text-[11px] text-slate-400">
                      Total Compras: $ {plan.total_buy_amount.toLocaleString("es-AR")} | Total Ventas: $ {plan.total_sell_amount.toLocaleString("es-AR")} | Efectivo Disponible: $ {plan.available_cash.toLocaleString("es-AR")}
                    </p>
                  </div>
                </div>
              </div>

              {/* Orders Table */}
              <div className="border border-slate-700 rounded-lg overflow-hidden bg-slate-900/60">
                <table className="w-full text-left text-xs text-slate-300">
                  <thead className="bg-slate-900 text-slate-400 font-semibold border-b border-slate-700">
                    <tr>
                      <th className="py-2.5 px-3">Ticker</th>
                      <th className="py-2.5 px-3">Acción</th>
                      <th className="py-2.5 px-3 text-right">Peso Actual / Target</th>
                      <th className="py-2.5 px-3 text-right">Nominales Enteros</th>
                      <th className="py-2.5 px-3 text-right">Monto Estimado</th>
                      <th className="py-2.5 px-3">Justificación</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/60 font-medium">
                    {plan.orders.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-6 text-center text-slate-400">
                          Todos los activos se encuentran dentro de las bandas de tolerancia permitidas. No se requieren órdenes.
                        </td>
                      </tr>
                    ) : (
                      plan.orders.map((o, idx) => (
                        <tr key={idx} className="hover:bg-slate-800/40">
                          <td className="py-2.5 px-3 font-bold text-white">{o.ticker}</td>
                          <td className="py-2.5 px-3">{getSideBadge(o.side)}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-slate-300">
                            {o.current_weight.toFixed(1)}% → {o.target_weight.toFixed(1)}%
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono font-bold text-white">
                            {o.estimated_shares.toLocaleString("es-AR")}
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-slate-200">
                            $ {Math.abs(o.delta_amount).toLocaleString("es-AR", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="py-2.5 px-3 text-slate-400 text-[11px] max-w-xs truncate" title={o.justification}>
                            {o.justification}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-3 border-t border-slate-700">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-xs font-semibold rounded-lg transition"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
};
