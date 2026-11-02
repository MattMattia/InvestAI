/**
 * Analytical KPI Header for Portfolio Detail View in InvestAI Enterprise.
 * Displays navigation back-button, risk profile badge, bimonetary valuations,
 * and aggregated unrealized P&L telemetry.
 */

import React, { useMemo } from "react";
import {
  ArrowDownRight,
  ArrowLeft,
  ArrowUpRight,
  Briefcase,
  Coins,
  DollarSign,
  Minus,
  Plus,
  TrendingUp,
  Wallet,
} from "lucide-react";
import {
  formatMoney,
  formatSignedPercent,
  parseDecimalSafe,
} from "@/lib/formatters";
import { navigateToPortfoliosList } from "@/lib/navigation";
import { InvestorProfile, Portfolio } from "@/types/api";

interface PortfolioKPIHeaderProps {
  portfolio: Portfolio;
  onNewOrder?: () => void;
}

export const PortfolioKPIHeader: React.FC<PortfolioKPIHeaderProps> = ({
  portfolio,
  onNewOrder,
}) => {
  const profile = (
    portfolio.investor_profile || "MODERATE"
  ).toString().toUpperCase() as InvestorProfile;

  const profileBadgeStyle = {
    CONSERVATIVE: "bg-sky-500/10 text-sky-400 border-sky-500/30",
    MODERATE: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    AGGRESSIVE: "bg-purple-500/10 text-purple-400 border-purple-500/30",
  }[profile] || "bg-slate-800 text-slate-300 border-slate-700";

  // Compute aggregated KPIs
  const kpis = useMemo(() => {
    const holdings = portfolio.holdings || [];

    let totalCostBasis = 0;
    let totalMarketHoldings = 0;

    holdings.forEach((h) => {
      const qty = parseDecimalSafe(h.quantity);
      const buyPrice = parseDecimalSafe(h.average_buy_price);
      const curPrice = parseDecimalSafe(h.current_price);

      totalCostBasis += qty * buyPrice;
      totalMarketHoldings += qty * curPrice;
    });

    const netPnl = totalMarketHoldings - totalCostBasis;
    const netPnlPct = totalCostBasis > 0 ? netPnl / totalCostBasis : 0;

    return {
      totalCostBasis,
      totalMarketHoldings,
      netPnl,
      netPnlPct,
      holdingsCount: holdings.length,
    };
  }, [portfolio]);

  const pnlMetrics = formatSignedPercent(kpis.netPnlPct);
  const isProfit = pnlMetrics.isPositive;
  const isLoss = !isProfit && !pnlMetrics.isZero;

  return (
    <div className="space-y-5">
      {/* Top Bar: Back Button, Title, ID, Risk Badge */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigateToPortfoliosList()}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-colors shadow-sm flex items-center gap-1.5 text-xs"
            title="Volver al catálogo de portafolios"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="hidden sm:inline font-medium">Portafolios</span>
          </button>

          <div className="h-6 w-px bg-slate-800 hidden sm:block" />

          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold tracking-tight text-white">
                {portfolio.name}
              </h1>
              <span
                className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border font-semibold tracking-wider ${profileBadgeStyle}`}
              >
                {profile}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-slate-400 font-mono mt-0.5">
              <span>ID: {portfolio.id}</span>
              <span>•</span>
              <span>{kpis.holdingsCount} activos en cartera</span>
            </div>
          </div>
        </div>

        {onNewOrder && (
          <button
            type="button"
            onClick={onNewOrder}
            className="px-3.5 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs shadow-lg shadow-sky-600/20 transition-all flex items-center gap-1.5 self-start sm:self-auto active:scale-95"
          >
            <Plus className="h-4 w-4" />
            <span>Nueva Orden</span>
          </button>
        )}
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* Valuación ARS */}
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
          <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Coins className="h-3 w-3 text-emerald-400" />
            Valuación ARS
          </span>
          <div className="text-base font-bold font-mono text-emerald-400 mt-1 tabular-nums">
            {formatMoney(
              portfolio.total_market_value_ars ?? portfolio.cash_balance_ars,
              "ARS"
            )}
          </div>
          <span className="text-[9px] text-slate-400 font-mono mt-0.5">
            Total MTM Implícito
          </span>
        </div>

        {/* Valuación USD */}
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
          <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <DollarSign className="h-3 w-3 text-sky-400" />
            Valuación USD
          </span>
          <div className="text-base font-bold font-mono text-sky-400 mt-1 tabular-nums">
            {formatMoney(
              portfolio.total_market_value_usd ?? portfolio.cash_balance_usd,
              "USD"
            )}
          </div>
          <span className="text-[9px] text-slate-400 font-mono mt-0.5">
            Divisa Dura Cable
          </span>
        </div>

        {/* Caja ARS */}
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
          <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Wallet className="h-3 w-3 text-emerald-400" />
            Caja ARS
          </span>
          <div className="text-base font-bold font-mono text-slate-200 mt-1 tabular-nums">
            {formatMoney(portfolio.cash_balance_ars, "ARS")}
          </div>
          <span className="text-[9px] text-slate-400 font-mono mt-0.5">
            Liquidación T+1/T+2
          </span>
        </div>

        {/* Caja USD */}
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
          <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Wallet className="h-3 w-3 text-sky-400" />
            Caja USD
          </span>
          <div className="text-base font-bold font-mono text-slate-200 mt-1 tabular-nums">
            {formatMoney(portfolio.cash_balance_usd, "USD")}
          </div>
          <span className="text-[9px] text-slate-400 font-mono mt-0.5">
            Saldo Disponible
          </span>
        </div>

        {/* Total Invertido */}
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
          <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <Briefcase className="h-3 w-3 text-slate-400" />
            Total Invertido
          </span>
          <div className="text-base font-bold font-mono text-slate-200 mt-1 tabular-nums">
            {formatMoney(kpis.totalCostBasis, "ARS")}
          </div>
          <span className="text-[9px] text-slate-400 font-mono mt-0.5">
            Costo Base Contable
          </span>
        </div>

        {/* P&L no Realizado */}
        <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
          <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
            <TrendingUp className="h-3 w-3 text-slate-400" />
            P&L no Realizado
          </span>
          <div
            className={`text-base font-bold font-mono mt-1 tabular-nums ${
              isProfit
                ? "text-emerald-400"
                : isLoss
                ? "text-rose-400"
                : "text-slate-200"
            }`}
          >
            {formatMoney(kpis.netPnl, "ARS")}
          </div>
          <div className="flex items-center gap-1 mt-0.5">
            <span
              className={`text-[10px] font-mono font-semibold flex items-center ${
                isProfit
                  ? "text-emerald-400"
                  : isLoss
                  ? "text-rose-400"
                  : "text-slate-400"
              }`}
            >
              {isProfit && <ArrowUpRight className="h-3 w-3 inline" />}
              {isLoss && <ArrowDownRight className="h-3 w-3 inline" />}
              {pnlMetrics.isZero && <Minus className="h-3 w-3 inline" />}
              {pnlMetrics.text}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
