/**
 * IngestionSummaryCard Component for InvestAI Enterprise.
 * Renders post-ingestion reconciliation reports with detected broker badges,
 * structured KPI tiles, and direct navigation into the affected portfolio.
 */

import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  CheckCircle2,
  FileSpreadsheet,
  Layers,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import type React from "react";
import type { BrokerReportUploadResponse } from "@/types/api";

interface IngestionSummaryCardProps {
  result: BrokerReportUploadResponse;
  onUploadAnother: () => void;
  onNavigateToPortfolio: (portfolioId: string) => void;
}

export const IngestionSummaryCard: React.FC<IngestionSummaryCardProps> = ({
  result,
  onUploadAnother,
  onNavigateToPortfolio,
}) => {
  const hasWarnings = (result.warnings && result.warnings.length > 0) || false;
  const reconciliation = result.reconciliation;

  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 p-6 shadow-xl space-y-6">
      {/* Executive Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-slate-800/80">
        <div className="flex items-start gap-3.5">
          <div className="h-12 w-12 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-bold text-white tracking-tight">
                Extracto Conciliado con Éxito
              </h3>
              {result.detected_broker && (
                <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30 flex items-center gap-1">
                  <Sparkles className="h-3 w-3" />
                  {result.detected_broker}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-1 flex items-center gap-2 flex-wrap font-mono">
              <span className="flex items-center gap-1 text-slate-300">
                <FileSpreadsheet className="h-3.5 w-3.5 text-slate-400" />
                {result.filename}
              </span>
              {result.created_at && (
                <>
                  <span>•</span>
                  <span>{new Date(result.created_at).toLocaleString()}</span>
                </>
              )}
            </p>
          </div>
        </div>

        {result.portfolio_id && (
          <button
            type="button"
            onClick={() => onNavigateToPortfolio(result.portfolio_id!)}
            className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs shadow-lg shadow-sky-600/20 transition-all flex items-center justify-center gap-2 group self-start sm:self-auto"
          >
            <span>Ver Cartera Impactada</span>
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
        )}
      </div>

      {/* KPI Tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* KPI 1: Filas Totales */}
        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 flex items-center gap-3.5">
          <div className="h-10 w-10 rounded-lg bg-slate-800/80 flex items-center justify-center text-slate-300 shrink-0">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <span className="text-[11px] uppercase tracking-wider font-mono text-slate-400 block">
              Filas Procesadas
            </span>
            <span className="text-lg font-bold font-mono text-white">
              {result.total_rows_parsed.toLocaleString()}
            </span>
          </div>
        </div>

        {/* KPI 2: Operaciones Válidas */}
        <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-900/40 flex items-center gap-3.5">
          <div className="h-10 w-10 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div>
            <span className="text-[11px] uppercase tracking-wider font-mono text-emerald-400/80 block">
              Tenencias Válidas
            </span>
            <span className="text-lg font-bold font-mono text-emerald-400">
              {result.valid_records_count.toLocaleString()}
            </span>
          </div>
        </div>

        {/* KPI 3: Descartados / Avisos */}
        <div
          className={`p-4 rounded-xl border flex items-center gap-3.5 ${
            result.rejected_records_count > 0
              ? "bg-amber-950/20 border-amber-900/40"
              : "bg-slate-950/60 border-slate-800"
          }`}
        >
          <div
            className={`h-10 w-10 rounded-lg flex items-center justify-center shrink-0 ${
              result.rejected_records_count > 0
                ? "bg-amber-500/20 text-amber-400"
                : "bg-slate-800/80 text-slate-400"
            }`}
          >
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <span
              className={`text-[11px] uppercase tracking-wider font-mono block ${
                result.rejected_records_count > 0 ? "text-amber-400/80" : "text-slate-400"
              }`}
            >
              Registros Descartados
            </span>
            <span
              className={`text-lg font-bold font-mono ${
                result.rejected_records_count > 0 ? "text-amber-400" : "text-slate-400"
              }`}
            >
              {result.rejected_records_count.toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      {/* Reconciliation Delta Details (if available) */}
      {reconciliation && (
        <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800/80 space-y-2">
          <div className="flex items-center justify-between text-xs font-mono text-slate-400">
            <span className="font-semibold text-slate-300">
              Desglose de Conciliación ({reconciliation.mode || "SNAPSHOT"})
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs font-mono">
            <div className="p-2 rounded bg-slate-900/60 border border-slate-800">
              <span className="text-slate-400 block text-[10px]">Agregadas</span>
              <span className="text-emerald-400 font-bold">
                +{reconciliation.holdings_added ?? 0}
              </span>
            </div>
            <div className="p-2 rounded bg-slate-900/60 border border-slate-800">
              <span className="text-slate-400 block text-[10px]">Actualizadas</span>
              <span className="text-sky-400 font-bold">
                ~{reconciliation.holdings_updated ?? 0}
              </span>
            </div>
            <div className="p-2 rounded bg-slate-900/60 border border-slate-800">
              <span className="text-slate-400 block text-[10px]">Removidas</span>
              <span className="text-rose-400 font-bold">
                -{reconciliation.holdings_removed ?? 0}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Warnings Section (if any) */}
      {hasWarnings && (
        <div className="p-3.5 rounded-xl bg-amber-950/30 border border-amber-800/40 text-xs text-amber-300 space-y-1.5">
          <div className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            <span>Advertencias durante el saneamiento contable:</span>
          </div>
          <ul className="list-disc list-inside space-y-1 text-amber-200/90 font-mono text-[11px] pl-1">
            {result.warnings!.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Action Footer */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-slate-800/80">
        <p className="text-xs text-slate-400 font-mono">
          ID de Transacción:{" "}
          <span className="text-slate-300">{result.job_id || "LOCAL-INGEST"}</span>
        </p>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          <button
            type="button"
            onClick={onUploadAnother}
            className="w-full sm:w-auto px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors flex items-center justify-center gap-2"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span>Cargar Otro Extracto</span>
          </button>
          {result.portfolio_id && (
            <button
              type="button"
              onClick={() => onNavigateToPortfolio(result.portfolio_id!)}
              className="w-full sm:w-auto px-4 py-2 rounded-xl bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 border border-sky-500/40 text-xs font-medium transition-colors flex items-center justify-center gap-2"
            >
              <Briefcase className="h-3.5 w-3.5" />
              <span>Ir a Cartera</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
