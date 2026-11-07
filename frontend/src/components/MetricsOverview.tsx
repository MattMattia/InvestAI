import {
  AlertTriangle,
  DollarSign,
  PieChart,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  Wallet,
} from "lucide-react";
import type React from "react";
import type { Portfolio, RiskAssessmentReport } from "../types/portfolio";

interface MetricsOverviewProps {
  portfolio: Portfolio | null;
  riskReport: RiskAssessmentReport | null;
}

export const MetricsOverview: React.FC<MetricsOverviewProps> = ({ portfolio, riskReport }) => {
  if (!portfolio) {
    return null;
  }

  const complianceStatus = riskReport?.compliance_status || "COMPLIANT";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
      {/* 1. Total ARS */}
      <div className="bg-slate-800 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between text-slate-400 mb-2">
          <span className="text-xs font-medium uppercase tracking-wider">Patrimonio Total</span>
          <div className="p-1.5 rounded-lg bg-sky-950 text-sky-400">
            <TrendingUp className="w-4 h-4" />
          </div>
        </div>
        <div className="text-xl font-bold text-white tracking-tight">
          ${" "}
          {portfolio.total_market_value_ars.toLocaleString("es-AR", {
            minimumFractionDigits: 2,
          })}
        </div>
        <p className="text-xs text-slate-400 mt-1">Valuación en Pesos (ARS)</p>
      </div>

      {/* 2. Total USD */}
      <div className="bg-slate-800 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between text-slate-400 mb-2">
          <span className="text-xs font-medium uppercase tracking-wider">Patrimonio USD</span>
          <div className="p-1.5 rounded-lg bg-emerald-950 text-emerald-400">
            <DollarSign className="w-4 h-4" />
          </div>
        </div>
        <div className="text-xl font-bold text-emerald-400 tracking-tight">
          u$s{" "}
          {portfolio.total_market_value_usd.toLocaleString("en-US", {
            minimumFractionDigits: 2,
          })}
        </div>
        <p className="text-xs text-slate-400 mt-1">Dólar Implícito CCL (~$1300)</p>
      </div>

      {/* 3. Efectivo Líquido */}
      <div className="bg-slate-800 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between text-slate-400 mb-2">
          <span className="text-xs font-medium uppercase tracking-wider">Efectivo Disponible</span>
          <div className="p-1.5 rounded-lg bg-indigo-950 text-indigo-400">
            <Wallet className="w-4 h-4" />
          </div>
        </div>
        <div className="text-sm font-semibold text-white">
          $ {portfolio.cash_balance_ars.toLocaleString("es-AR")}
        </div>
        <div className="text-xs text-slate-400 mt-0.5">
          + u$s {portfolio.cash_balance_usd.toLocaleString("en-US")}
        </div>
      </div>

      {/* 4. Activos en Cartera */}
      <div className="bg-slate-800 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between text-slate-400 mb-2">
          <span className="text-xs font-medium uppercase tracking-wider">Activos en Cartera</span>
          <div className="p-1.5 rounded-lg bg-purple-950 text-purple-400">
            <PieChart className="w-4 h-4" />
          </div>
        </div>
        <div className="text-xl font-bold text-white tracking-tight">
          {portfolio.holdings_count}
        </div>
        <p className="text-xs text-slate-400 mt-1">CEDEARs, Bonos y Acciones</p>
      </div>

      {/* 5. Estado de Riesgo Determinista */}
      <div className="bg-slate-800 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between text-slate-400 mb-2">
          <span className="text-xs font-medium uppercase tracking-wider">Control de Riesgo</span>
          {complianceStatus === "COMPLIANT" && (
            <div className="p-1.5 rounded-lg bg-emerald-950 text-emerald-400">
              <ShieldCheck className="w-4 h-4" />
            </div>
          )}
          {complianceStatus === "WARNING" && (
            <div className="p-1.5 rounded-lg bg-amber-950 text-amber-400">
              <AlertTriangle className="w-4 h-4" />
            </div>
          )}
          {complianceStatus === "NON_COMPLIANT" && (
            <div className="p-1.5 rounded-lg bg-rose-950 text-rose-400">
              <ShieldAlert className="w-4 h-4" />
            </div>
          )}
        </div>
        <div>
          {complianceStatus === "COMPLIANT" && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-emerald-900/60 text-emerald-300 border border-emerald-700">
              APROBADO
            </span>
          )}
          {complianceStatus === "WARNING" && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-900/60 text-amber-300 border border-amber-700">
              ADVERTENCIAS
            </span>
          )}
          {complianceStatus === "NON_COMPLIANT" && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-rose-900/60 text-rose-300 border border-rose-700">
              INCUMPLIMIENTO
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mt-1">
          {riskReport
            ? `${riskReport.passed_rules_count}/${riskReport.total_rules_evaluated} reglas OK`
            : "Pendiente de evaluación"}
        </p>
      </div>
    </div>
  );
};
