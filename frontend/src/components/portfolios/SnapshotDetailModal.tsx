/**
 * Executive Forensic Snapshot Detail Modal for InvestAI Enterprise.
 * Transforms raw risk audit telemetry into an institutional Compliance Report
 * with visual rule-by-rule evaluation cards, certificate export (.json), and
 * collapsible technical payload inspector.
 */

import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  FileCode,
  ShieldAlert,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";
import { formatDate, normalizeSnapshotPayload } from "@/lib/formatters";
import { RiskAuditSnapshot } from "@/types/api";

interface SnapshotDetailModalProps {
  snapshot: RiskAuditSnapshot | null;
  isOpen: boolean;
  onClose: () => void;
}

interface ParsedRuleResult {
  rule_id: string;
  rule_name: string;
  severity: string;
  passed: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export const SnapshotDetailModal: React.FC<SnapshotDetailModalProps> = ({
  snapshot,
  isOpen,
  onClose,
}) => {
  const [copied, setCopied] = useState<boolean>(false);
  const [showRawJson, setShowRawJson] = useState<boolean>(false);

  // Handle ESC key dismiss
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !snapshot) return null;

  const payload = normalizeSnapshotPayload(snapshot.report_payload);
  const jsonString = JSON.stringify(payload, null, 2);

  const isOk = snapshot.compliance_status === "COMPLIANCE_OK";
  const criticalCount = snapshot.critical_alerts_count || 0;
  const warningCount = Number(payload.warning_alerts_count ?? 0);

  const rawResults = Array.isArray(payload.results) ? payload.results : [];
  const rulesList: ParsedRuleResult[] = rawResults.map((r: any, idx: number) => ({
    rule_id: String(r?.rule_id || `RULE_${idx + 1}`),
    rule_name: String(r?.rule_name || r?.rule_id || `Regla Normativa #${idx + 1}`),
    severity: String(r?.severity || "INFO").toUpperCase(),
    passed: Boolean(r?.passed ?? true),
    message: String(
      r?.message ||
        (r?.passed
          ? "Parámetro validado dentro de los umbrales institucionales."
          : "Se detectó un desvío respecto al umbral normativo configurado.")
    ),
    details:
      r?.details && typeof r.details === "object"
        ? (r.details as Record<string, unknown>)
        : undefined,
  }));

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonString);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback ignored
    }
  };

  const handleDownloadCertificate = () => {
    const blob = new Blob([jsonString], {
      type: "application/json;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute(
      "download",
      `certificado_forense_${snapshot.id.slice(0, 8)}.json`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-3xl rounded-2xl bg-slate-900 border border-slate-800 p-6 shadow-2xl z-10 space-y-5 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-start justify-between pb-3 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-3">
            <div
              className={`h-10 w-10 rounded-xl flex items-center justify-center border shrink-0 ${
                isOk
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  : "bg-rose-500/10 text-rose-400 border-rose-500/30"
              }`}
            >
              {isOk ? (
                <ShieldCheck className="h-5 w-5" />
              ) : (
                <ShieldAlert className="h-5 w-5" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-bold text-white">
                  Dictamen Ejecutivo de Auditoría Forense
                </h2>
                <span
                  className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded font-bold border ${
                    isOk
                      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                      : "bg-rose-500/15 text-rose-300 border-rose-500/30"
                  }`}
                >
                  {snapshot.compliance_status}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                Snapshot ID: {snapshot.id} • Emitido: {formatDate(snapshot.created_at)} ART
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="space-y-5 overflow-y-auto pr-1">
          {/* Quick Stats Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Reglas Evaluadas
              </span>
              <span className="text-base font-bold font-mono text-white mt-0.5 block">
                {String(
                  payload.total_rules_evaluated ??
                    snapshot.total_rules_evaluated ??
                    rulesList.length
                )}
              </span>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Reglas Aprobadas
              </span>
              <span className="text-base font-bold font-mono text-emerald-400 mt-0.5 block">
                {String(
                  payload.passed_rules_count ??
                    rulesList.filter((r) => r.passed).length
                )}
              </span>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Alertas Críticas / Warn
              </span>
              <span
                className={`text-base font-bold font-mono mt-0.5 block ${
                  criticalCount > 0
                    ? "text-rose-400"
                    : warningCount > 0
                    ? "text-amber-400"
                    : "text-slate-300"
                }`}
              >
                {criticalCount} Crít. / {warningCount} Adv.
              </span>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Estado Trazabilidad
              </span>
              <span className="text-xs font-bold font-mono text-sky-400 mt-1 block truncate">
                {snapshot.notification_status || "INMUTABLE (SHA)"}
              </span>
            </div>
          </div>

          {/* Visual Rule-by-Rule Evaluation Cards */}
          <div className="space-y-2.5">
            <h3 className="text-xs font-mono uppercase tracking-wider text-slate-300 font-semibold">
              Desglose de Reglas Cuantitativas y Límites Normativos
            </h3>

            {rulesList.length > 0 ? (
              <div className="space-y-2.5">
                {rulesList.map((rule, index) => {
                  const isRulePassed = rule.passed;
                  const isCritical =
                    !isRulePassed && rule.severity === "CRITICAL";

                  return (
                    <div
                      key={`${rule.rule_id}-${index}`}
                      className={`p-4 rounded-xl border transition-colors ${
                        isRulePassed
                          ? "bg-slate-950/60 border-slate-800/90"
                          : isCritical
                          ? "bg-rose-950/25 border-rose-500/40"
                          : "bg-amber-950/20 border-amber-500/40"
                      }`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          {isRulePassed ? (
                            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                          ) : isCritical ? (
                            <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
                          ) : (
                            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                          )}
                          <span className="text-xs font-bold text-white">
                            {rule.rule_name}
                          </span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
                            {rule.rule_id}
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 font-mono text-[10px]">
                          <span
                            className={`px-2 py-0.5 rounded border font-semibold ${
                              isRulePassed
                                ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                                : isCritical
                                ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
                                : "bg-amber-500/15 text-amber-300 border-amber-500/30"
                            }`}
                          >
                            {isRulePassed ? "APROBADA" : `INFRACCIÓN (${rule.severity})`}
                          </span>
                        </div>
                      </div>

                      <p className="text-xs text-slate-300 mt-2 leading-relaxed">
                        {rule.message}
                      </p>

                      {rule.details && Object.keys(rule.details).length > 0 && (
                        <div className="mt-2.5 pt-2 border-t border-slate-800/80 flex flex-wrap gap-2">
                          {Object.entries(rule.details).map(([k, v]) => {
                            if (v === null || v === undefined) return null;
                            const valStr =
                              typeof v === "object"
                                ? JSON.stringify(v)
                                : String(v);
                            return (
                              <span
                                key={k}
                                className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-800"
                              >
                                <strong className="text-slate-400">{k}:</strong>{" "}
                                {valStr.slice(0, 60)}
                              </span>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-xs text-slate-400 font-mono">
                Snapshot registrado con estado {snapshot.compliance_status}. Todas las
                reglas del motor cuantitativo fueron verificadas.
              </div>
            )}
          </div>

          {/* Collapsible Technical JSON Payload Inspector */}
          <div className="rounded-xl bg-slate-950 border border-slate-800 overflow-hidden">
            <div className="px-4 py-2.5 flex items-center justify-between bg-slate-900/60">
              <button
                type="button"
                onClick={() => setShowRawJson((prev) => !prev)}
                className="text-xs font-mono text-slate-300 hover:text-white flex items-center gap-2 font-medium"
              >
                <FileCode className="h-4 w-4 text-sky-400" />
                <span>
                  {showRawJson
                    ? "Ocultar Payload Técnico Crudo (JSON)"
                    : "Ver Payload Técnico Crudo (JSON)"}
                </span>
                {showRawJson ? (
                  <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                )}
              </button>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-[11px] font-mono text-slate-300 transition-colors"
                >
                  {copied ? (
                    <>
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                      <span className="text-emerald-400">¡Copiado!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-3.5 w-3.5 text-slate-400" />
                      <span>Copiar JSON</span>
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={handleDownloadCertificate}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 text-[11px] font-mono text-sky-300 border border-sky-500/30 transition-colors"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Descargar (.json)</span>
                </button>
              </div>
            </div>

            {showRawJson && (
              <pre className="p-4 border-t border-slate-800 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-60 overflow-y-auto leading-relaxed select-all">
                {jsonString}
              </pre>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="pt-3 border-t border-slate-800 flex items-center justify-between shrink-0">
          <span className="text-[11px] font-mono text-slate-400">
            Registro de Auditoría Inmutable • InvestAI Compliance Engine
          </span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
          >
            Cerrar Dictamen
          </button>
        </div>
      </div>
    </div>
  );
};
