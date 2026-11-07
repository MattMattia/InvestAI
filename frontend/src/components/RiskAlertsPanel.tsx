import { AlertTriangle, CheckCircle2, Info, Play, ShieldAlert, ShieldCheck } from "lucide-react";
import type React from "react";
import type { RiskAssessmentReport, RuleResult } from "../types/portfolio";

interface RiskAlertsPanelProps {
  report: RiskAssessmentReport | null;
  onEvaluate: () => Promise<void>;
  loading: boolean;
}

export const RiskAlertsPanel: React.FC<RiskAlertsPanelProps> = ({
  report,
  onEvaluate,
  loading,
}) => {
  const getSeverityBadge = (severity: RuleResult["severity"], passed: boolean) => {
    if (passed) {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
          <CheckCircle2 className="w-3 h-3 mr-1" /> OK
        </span>
      );
    }
    switch (severity) {
      case "CRITICAL":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-rose-950 text-rose-300 border border-rose-800">
            <ShieldAlert className="w-3 h-3 mr-1" /> CRÍTICA
          </span>
        );
      case "WARNING":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-amber-950 text-amber-300 border border-amber-800">
            <AlertTriangle className="w-3 h-3 mr-1" /> ADVERTENCIA
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-950 text-sky-300 border border-sky-800">
            <Info className="w-3 h-3 mr-1" /> INFO
          </span>
        );
    }
  };

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-sm">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-5">
        <div>
          <div className="flex items-center space-x-2">
            <ShieldAlert className="w-5 h-5 text-sky-400" />
            <h3 className="text-base font-bold text-white">Evaluación Determinista de Riesgo</h3>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Límites de concentración, ratios contables (PEG, P/B, EPS), brecha FX y piso de renta
            fija
          </p>
        </div>

        <button
          type="button"
          onClick={onEvaluate}
          disabled={loading}
          className="flex items-center space-x-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-semibold px-4 py-2 rounded-lg transition shadow-md shadow-emerald-700/20"
        >
          <Play className="w-3.5 h-3.5 fill-current" />
          <span>{loading ? "Evaluando..." : "Evaluar Riesgo en Vivo"}</span>
        </button>
      </div>

      {!report ? (
        <div className="text-center py-10 bg-slate-900/40 rounded-xl border border-dashed border-slate-700">
          <ShieldCheck className="w-10 h-10 text-slate-500 mx-auto mb-2" />
          <p className="text-sm font-semibold text-slate-300">Portafolio listo para auditar</p>
          <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
            Haz clic en "Evaluar Riesgo en Vivo" para ejecutar las 5 reglas deterministas del Risk
            Engine.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Resumen Superior */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
            <div className="bg-slate-900 p-2.5 rounded-lg border border-slate-700/80">
              <span className="text-slate-400 block text-[11px]">Total Reglas</span>
              <span className="text-base font-bold text-white">{report.total_rules_evaluated}</span>
            </div>
            <div className="bg-slate-900 p-2.5 rounded-lg border border-slate-700/80">
              <span className="text-emerald-400 block text-[11px]">Reglas Cumplidas</span>
              <span className="text-base font-bold text-emerald-400">
                {report.passed_rules_count}
              </span>
            </div>
            <div className="bg-slate-900 p-2.5 rounded-lg border border-slate-700/80">
              <span className="text-amber-400 block text-[11px]">Advertencias</span>
              <span className="text-base font-bold text-amber-400">
                {report.warning_alerts_count}
              </span>
            </div>
            <div className="bg-slate-900 p-2.5 rounded-lg border border-slate-700/80">
              <span className="text-rose-400 block text-[11px]">Alertas Críticas</span>
              <span className="text-base font-bold text-rose-400">
                {report.critical_alerts_count}
              </span>
            </div>
          </div>

          {/* Lista de Reglas Evaluadas */}
          <div className="divide-y divide-slate-700/60 border border-slate-700 rounded-lg overflow-hidden bg-slate-900/40">
            {report.results.map((rule) => (
              <div key={rule.rule_id} className="p-3.5 hover:bg-slate-700/20 transition">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-bold text-white">{rule.rule_name}</span>
                    <span className="text-[10px] text-slate-400 font-mono">[{rule.rule_id}]</span>
                  </div>
                  <div>{getSeverityBadge(rule.severity, rule.passed)}</div>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{rule.message}</p>
                {rule.details && Object.keys(rule.details).length > 0 && (
                  <div className="mt-2 p-2 bg-slate-950/60 rounded text-[11px] font-mono text-slate-400 overflow-x-auto">
                    {JSON.stringify(rule.details, null, 2)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
