/**
 * QuotesTable Component for InvestAI Enterprise.
 * High-density institutional dark table for real-time BYMA market data.
 * Displays tickers, asset classifications, tabular pricing, semaphoric daily changes,
 * intradiary highs/lows, and volume with interactive row selection.
 */

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type React from "react";
import { formatMoney } from "@/lib/formatters";
import type { MarketQuote } from "@/types/api";

interface QuotesTableProps {
  quotes: MarketQuote[];
  selectedTicker: string;
  onSelectTicker: (ticker: string) => void;
  onTradeTicker?: (quote: MarketQuote) => void;
  isLoading?: boolean;
}

export const QuotesTable: React.FC<QuotesTableProps> = ({
  quotes,
  selectedTicker,
  onSelectTicker,
  onTradeTicker,
  isLoading = false,
}) => {
  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden flex flex-col">
      {/* Table Container with Horizontal Scroll */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-slate-800/80 bg-slate-950/60 font-mono uppercase text-[11px] text-slate-400 tracking-wider">
              <th className="py-3 px-4">Especie</th>
              <th className="py-3 px-4">Denominación</th>
              <th className="py-3 px-3">Tipo</th>
              <th className="py-3 px-4 text-right">Último Precio</th>
              <th className="py-3 px-4 text-right">Var. Diaria</th>
              <th className="py-3 px-4 text-right">Máx / Mín Día</th>
              <th className="py-3 px-4 text-right">Volumen</th>
              <th className="py-3 px-4 text-center">Acción</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {isLoading && quotes.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-12 text-center text-slate-400 font-sans">
                  <div className="flex items-center justify-center gap-2">
                    <span className="h-4 w-4 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
                    <span>Cargando cotizaciones de mercado en tiempo real...</span>
                  </div>
                </td>
              </tr>
            ) : quotes.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-12 text-center text-slate-400 font-sans">
                  No se encontraron especies coincidentes con el criterio de búsqueda.
                </td>
              </tr>
            ) : (
              quotes.map((q) => {
                const isSelected = q.ticker === selectedTicker;
                const isPositive = q.change_pct > 0;
                const isZero = Math.abs(q.change_pct) < 0.001;
                const sign = isPositive ? "+" : "";

                return (
                  <tr
                    key={q.ticker}
                    onClick={() => onSelectTicker(q.ticker)}
                    className={`cursor-pointer transition-all select-none ${
                      isSelected
                        ? "bg-sky-500/15 border-l-4 border-l-sky-500 text-slate-100"
                        : "hover:bg-slate-800/50 text-slate-300 border-l-4 border-l-transparent"
                    }`}
                  >
                    {/* Ticker */}
                    <td className="py-3 px-4 font-bold text-white text-xs tracking-tight">
                      {q.ticker}
                    </td>

                    {/* Company / Instrument Name */}
                    <td className="py-3 px-4 font-sans text-slate-300 text-xs truncate max-w-xs">
                      {q.name}
                    </td>

                    {/* Asset Type Chip */}
                    <td className="py-3 px-3">
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded border tracking-wider ${
                          q.asset_type === "STOCK"
                            ? "bg-sky-500/15 text-sky-400 border-sky-500/30"
                            : q.asset_type === "CEDEAR"
                              ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
                              : "bg-amber-500/15 text-amber-300 border-amber-500/30"
                        }`}
                      >
                        {q.asset_type}
                      </span>
                    </td>

                    {/* Last Price */}
                    <td className="py-3 px-4 text-right font-bold text-slate-100 tabular-nums">
                      {formatMoney(q.last_price, q.currency)}
                    </td>

                    {/* Daily Variation (% and Nominal) */}
                    <td className="py-3 px-4 text-right tabular-nums">
                      <div
                        className={`inline-flex items-center gap-1 font-semibold ${
                          isZero
                            ? "text-slate-400"
                            : isPositive
                              ? "text-emerald-400"
                              : "text-rose-400"
                        }`}
                      >
                        {isZero ? (
                          <Minus className="h-3 w-3" />
                        ) : isPositive ? (
                          <ArrowUpRight className="h-3.5 w-3.5" />
                        ) : (
                          <ArrowDownRight className="h-3.5 w-3.5" />
                        )}
                        <span>
                          {sign}
                          {q.change_pct.toFixed(2)}%
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {sign}
                        {formatMoney(q.change_nominal, q.currency)}
                      </div>
                    </td>

                    {/* Intradiary Range (High / Low) */}
                    <td className="py-3 px-4 text-right tabular-nums text-slate-400">
                      <div>{q.high_price ? q.high_price.toFixed(2) : "—"}</div>
                      <div className="text-[10px] text-slate-400">
                        {q.low_price ? q.low_price.toFixed(2) : "—"}
                      </div>
                    </td>

                    {/* Volume (Shares & Millions ARS/USD) */}
                    <td className="py-3 px-4 text-right tabular-nums text-slate-300">
                      <div>{q.volume_shares ? q.volume_shares.toLocaleString() : "—"}</div>
                      {q.volume_amount && (
                        <div className="text-[10px] text-slate-400">
                          {q.volume_amount >= 1_000_000
                            ? `$ ${(q.volume_amount / 1_000_000).toFixed(1)}M`
                            : `$ ${q.volume_amount.toLocaleString()}`}
                        </div>
                      )}
                    </td>

                    {/* Action: Operar */}
                    <td className="py-3 px-4 text-center">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onTradeTicker) onTradeTicker(q);
                        }}
                        className="px-2.5 py-1 rounded-lg bg-sky-600/20 hover:bg-sky-600 text-sky-300 hover:text-white border border-sky-500/30 text-[11px] font-medium transition-all shadow-sm active:scale-95"
                      >
                        Operar
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Table Footer info */}
      <div className="px-4 py-3 border-t border-slate-800 bg-slate-950/40 flex items-center justify-between text-xs text-slate-400 font-mono">
        <span>Mostrando {quotes.length} especies de BYMA</span>
        <span>Precios en ARS / USD diferidos &lt; 15s</span>
      </div>
    </div>
  );
};
