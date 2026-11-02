/**
 * RecentOrdersTable Component for InvestAI Enterprise.
 * High-density chronological order audit table displaying FSM states,
 * operations, traded prices, net settlements, and portfolio provenance.
 */

import React from "react";
import {
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  RotateCw,
} from "lucide-react";
import { formatDate, formatMoney } from "@/lib/formatters";
import { OrderRecord } from "@/types/api";

interface RecentOrdersTableProps {
  orders: OrderRecord[];
  isLoading?: boolean;
}

export const RecentOrdersTable: React.FC<RecentOrdersTableProps> = ({
  orders,
  isLoading = false,
}) => {
  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden flex flex-col">
      <div className="px-5 py-4 border-b border-slate-800/80 bg-slate-950/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-sky-400" />
          <h3 className="text-xs font-mono uppercase tracking-wider text-slate-200 font-semibold">
            Registro Histórico de Órdenes FSM
          </h3>
        </div>
        <span className="text-[11px] font-mono text-slate-400">
          {orders.length} órdenes registradas
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-slate-800/80 bg-slate-950/60 font-mono uppercase text-[11px] text-slate-400 tracking-wider">
              <th className="py-3 px-4">Fecha / Hora</th>
              <th className="py-3 px-4">Especie</th>
              <th className="py-3 px-3">Tipo</th>
              <th className="py-3 px-4">Operación</th>
              <th className="py-3 px-4 text-right">Cantidad</th>
              <th className="py-3 px-4 text-right">Precio Ref.</th>
              <th className="py-3 px-4 text-right">Total Neto</th>
              <th className="py-3 px-4 text-center">Estado FSM</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {isLoading && orders.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="py-12 text-center text-slate-400 font-sans"
                >
                  <div className="flex items-center justify-center gap-2">
                    <span className="h-4 w-4 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
                    <span>Cargando órdenes de negociación...</span>
                  </div>
                </td>
              </tr>
            ) : orders.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="py-12 text-center text-slate-400 font-sans"
                >
                  No se registran órdenes enviadas al mercado en esta sesión.
                </td>
              </tr>
            ) : (
              orders.map((o) => {
                const isBuy = o.side === "BUY";

                const statusBadgeStyle = {
                  EXECUTED: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
                  VALIDATED: "bg-sky-500/15 text-sky-400 border-sky-500/30",
                  ROUTED: "bg-indigo-500/15 text-indigo-400 border-indigo-500/30",
                  PENDING: "bg-amber-500/15 text-amber-300 border-amber-500/30",
                  FAILED: "bg-rose-500/15 text-rose-400 border-rose-500/30",
                  REJECTED: "bg-rose-500/15 text-rose-400 border-rose-500/30",
                }[o.status] || "bg-slate-800 text-slate-300 border-slate-700";

                return (
                  <tr
                    key={o.id}
                    className="hover:bg-slate-800/40 transition-colors text-slate-300"
                  >
                    {/* Date / Time */}
                    <td className="py-3 px-4 text-slate-400 tabular-nums">
                      {formatDate(o.created_at)}
                    </td>

                    {/* Ticker */}
                    <td className="py-3 px-4 font-bold text-white tracking-tight">
                      {o.ticker}
                    </td>

                    {/* Order Type */}
                    <td className="py-3 px-3">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                        {o.order_type}
                      </span>
                    </td>

                    {/* Operation (BUY/SELL) */}
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex items-center gap-1 font-bold ${
                          isBuy ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {isBuy ? (
                          <ArrowUpRight className="h-3.5 w-3.5" />
                        ) : (
                          <ArrowDownRight className="h-3.5 w-3.5" />
                        )}
                        <span>{isBuy ? "COMPRA" : "VENTA"}</span>
                      </span>
                    </td>

                    {/* Quantity */}
                    <td className="py-3 px-4 text-right tabular-nums text-slate-100 font-semibold">
                      {o.quantity.toLocaleString()}
                    </td>

                    {/* Price */}
                    <td className="py-3 px-4 text-right tabular-nums text-slate-300">
                      {formatMoney(o.price, "ARS")}
                    </td>

                    {/* Net Total */}
                    <td className="py-3 px-4 text-right tabular-nums font-bold text-white">
                      {formatMoney(o.net_amount, "ARS")}
                    </td>

                    {/* FSM Status */}
                    <td className="py-3 px-4 text-center">
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded border inline-flex items-center gap-1 ${statusBadgeStyle}`}
                      >
                        {o.status === "EXECUTED" ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : o.status === "FAILED" || o.status === "REJECTED" ? (
                          <AlertCircle className="h-3 w-3" />
                        ) : (
                          <RotateCw className="h-3 w-3" />
                        )}
                        <span>{o.status}</span>
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

