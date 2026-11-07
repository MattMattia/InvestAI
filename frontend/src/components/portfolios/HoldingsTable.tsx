/**
 * Institutional Financial Holdings Table for InvestAI Enterprise.
 * Displays positions, mark-to-market valuations, unrealized P&L chips, and weight progress bars.
 */

import { ArrowDownRight, ArrowUpRight, Inbox, Layers, Minus } from "lucide-react";
import type React from "react";
import { useMemo } from "react";
import {
  calculateHoldingMetrics,
  formatMoney,
  formatNumber,
  formatSignedPercent,
  parseDecimalSafe,
} from "@/lib/formatters";
import type { Holding, HoldingWithMetrics, Portfolio } from "@/types/api";

interface HoldingsTableProps {
  portfolio: Portfolio;
}

export const HoldingsTable: React.FC<HoldingsTableProps> = ({ portfolio }) => {
  const holdings: Holding[] = portfolio.holdings || [];

  // Compute total valuation across portfolio for accurate weights
  const totalValuation = useMemo(() => {
    const totalArs = parseDecimalSafe(portfolio.total_market_value_ars);
    if (totalArs > 0) return totalArs;

    return holdings.reduce((sum, h) => {
      const qty = parseDecimalSafe(h.quantity);
      const price = parseDecimalSafe(h.current_price);
      return sum + qty * price;
    }, 0);
  }, [portfolio, holdings]);

  const computedHoldings: HoldingWithMetrics[] = useMemo(() => {
    return holdings.map((h) => calculateHoldingMetrics(h, totalValuation));
  }, [holdings, totalValuation]);

  if (computedHoldings.length === 0) {
    return (
      <div className="rounded-xl bg-slate-900 border border-slate-800 p-10 text-center space-y-3">
        <div className="h-12 w-12 rounded-full bg-slate-800/80 flex items-center justify-center mx-auto text-slate-400">
          <Inbox className="h-6 w-6" />
        </div>
        <h3 className="text-sm font-semibold text-slate-200">Sin Posiciones Abiertas</h3>
        <p className="text-xs text-slate-400 max-w-sm mx-auto">
          Esta cartera aún no registra compras ni tenencias de títulos valores. Los saldos en
          efectivo están disponibles en tesorería.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden">
      {/* Table Title Bar */}
      <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-sky-400" />
          <h3 className="font-semibold text-sm text-slate-100">
            Detalle de Tenencias y Rendimiento MTM
          </h3>
        </div>
        <span className="text-xs font-mono text-slate-400">
          {computedHoldings.length}{" "}
          {computedHoldings.length === 1 ? "posición activa" : "posiciones activas"}
        </span>
      </div>

      {/* Responsive Table Container */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-mono uppercase text-slate-400 tracking-wider">
              <th className="py-3 px-4">Ticker / Activo</th>
              <th className="py-3 px-3 text-center">Moneda</th>
              <th className="py-3 px-4 text-right">Cantidad</th>
              <th className="py-3 px-4 text-right">P. Promedio</th>
              <th className="py-3 px-4 text-right">Cotización</th>
              <th className="py-3 px-4 text-right">Valuación MTM</th>
              <th className="py-3 px-4 text-right">P&L No Realizado</th>
              <th className="py-3 px-4 text-right">Ponderación</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {computedHoldings.map((h) => {
              const pnlMetrics = formatSignedPercent(h.unrealized_pnl_pct);
              const isProfit = pnlMetrics.isPositive;
              const isLoss = !isProfit && !pnlMetrics.isZero;

              return (
                <tr
                  key={h.id || h.asset_ticker}
                  className="hover:bg-slate-800/40 transition-colors"
                >
                  {/* Ticker & Name */}
                  <td className="py-3.5 px-4">
                    <div className="flex flex-col">
                      <span className="font-bold text-slate-100 text-sm tracking-tight">
                        {h.asset_ticker}
                      </span>
                      <span className="text-[10px] text-slate-400 font-sans truncate max-w-[150px]">
                        {h.asset?.name || h.asset?.asset_type || "Bursátil BYMA"}
                      </span>
                    </div>
                  </td>

                  {/* Currency Badge */}
                  <td className="py-3.5 px-3 text-center">
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded font-semibold uppercase ${
                        h.currency === "USD"
                          ? "bg-sky-500/10 text-sky-400 border border-sky-500/30"
                          : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                      }`}
                    >
                      {h.currency}
                    </span>
                  </td>

                  {/* Quantity */}
                  <td className="py-3.5 px-4 text-right tabular-nums text-slate-200">
                    {formatNumber(h.quantity, 2)}
                  </td>

                  {/* Average Buy Price */}
                  <td className="py-3.5 px-4 text-right tabular-nums text-slate-400">
                    {formatMoney(h.average_buy_price, h.currency)}
                  </td>

                  {/* Current Market Price */}
                  <td className="py-3.5 px-4 text-right tabular-nums font-semibold text-slate-100">
                    {formatMoney(h.current_price, h.currency)}
                  </td>

                  {/* Total Market Value */}
                  <td className="py-3.5 px-4 text-right tabular-nums font-bold text-white">
                    {formatMoney(h.market_value, h.currency)}
                  </td>

                  {/* Unrealized P&L */}
                  <td className="py-3.5 px-4 text-right">
                    <div className="flex flex-col items-end">
                      <span
                        className={`font-semibold tabular-nums ${
                          isProfit
                            ? "text-emerald-400"
                            : isLoss
                              ? "text-rose-400"
                              : "text-slate-400"
                        }`}
                      >
                        {formatMoney(h.unrealized_pnl, h.currency)}
                      </span>
                      <span
                        className={`inline-flex items-center gap-0.5 px-1.5 py-0.2 rounded text-[10px] mt-0.5 font-bold ${
                          isProfit
                            ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                            : isLoss
                              ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                              : "bg-slate-800 text-slate-400 border border-slate-700"
                        }`}
                      >
                        {isProfit && <ArrowUpRight className="h-3 w-3" />}
                        {isLoss && <ArrowDownRight className="h-3 w-3" />}
                        {pnlMetrics.isZero && <Minus className="h-3 w-3" />}
                        {pnlMetrics.text}
                      </span>
                    </div>
                  </td>

                  {/* Weight Progress Bar */}
                  <td className="py-3.5 px-4 text-right">
                    <div className="flex flex-col items-end gap-1">
                      <span className="font-semibold text-slate-300 tabular-nums">
                        {h.weight_pct.toFixed(2)}%
                      </span>
                      <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-sky-500 rounded-full transition-all duration-300"
                          style={{
                            width: `${Math.min(100, Math.max(0, h.weight_pct))}%`,
                          }}
                        />
                      </div>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
