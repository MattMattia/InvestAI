/**
 * Forensic Snapshot Detail Modal for InvestAI Enterprise.
 * Displays evaluation KPIs, rule-by-rule status, and interactive formatted JSON viewer.
 */

import React, { useEffect, useState } from "react";
import {
  Check,
  Copy,
  FileCode,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { formatDate, normalizeSnapshotPayload } from "@/lib/formatters";
import { RiskAuditSnapshot } from "@/types/api";

interface SnapshotDetailModalProps {
  snapshot: RiskAuditSnapshot | null;
  isOpen: boolean;
  onClose: () => void;
}

export const SnapshotDetailModal: React.FC<SnapshotDetailModalProps> = ({
  snapshot,
  isOpen,
  onClose,
}) => {
  const [copied, setCopied] = useState<boolean>(false);

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

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonString);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-2xl rounded-2xl bg-slate-900 border border-slate-800 p-6 shadow-2xl z-10 space-y-5 flex flex-col max-h-[90vh]">
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
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-white">
                  Inspección de Snapshot Forense
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
                ID: {snapshot.id} • {formatDate(snapshot.created_at)}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="space-y-4 overflow-y-auto pr-1">
          {/* Quick Stats Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Reglas Evaluadas
              </span>
              <span className="text-sm font-bold font-mono text-white mt-0.5 block">
                {String(payload.total_rules_evaluated ?? 5)}
              </span>
            </div>

            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Reglas Aprobadas
              </span>
              <span className="text-sm font-bold font-mono text-emerald-400 mt-0.5 block">
                {String(payload.passed_rules_count ?? (isOk ? 5 : 4))}
              </span>
            </div>

            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Alertas Críticas
              </span>
              <span
                className={`text-sm font-bold font-mono mt-0.5 block ${
                  criticalCount > 0 ? "text-rose-400" : "text-slate-400"
                }`}
              >
                {criticalCount}
              </span>
            </div>

            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800">
              <span className="text-[10px] uppercase font-mono text-slate-400 block">
                Notificación
              </span>
              <span className="text-sm font-bold font-mono text-sky-400 mt-0.5 block truncate">
                {snapshot.notification_status || "EVALUATED"}
              </span>
            </div>
          </div>

          {/* JSON Payload Inspector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-300 flex items-center gap-1.5 font-mono">
                <FileCode className="h-4 w-4 text-sky-400" />
                Report Payload (JSON Estructurado)
              </span>

              <button
                type="button"
                onClick={handleCopy}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[11px] font-mono text-slate-300 transition-colors"
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
            </div>

            <pre className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-64 overflow-y-auto leading-relaxed select-all">
              {jsonString}
            </pre>
          </div>
        </div>

        {/* Footer */}
        <div className="pt-3 border-t border-slate-800 flex justify-end shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
          >
            Cerrar Inspección
          </button>
        </div>
      </div>
    </div>
  );
};
