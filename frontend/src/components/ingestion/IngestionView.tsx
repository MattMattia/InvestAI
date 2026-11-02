/**
 * IngestionView Component for InvestAI Enterprise.
 * Interactive Broker Statement Ingestion Dashboard featuring multi-format dropzone,
 * destination portfolio selector, RBAC protection, and TanStack Query v5 cache invalidation.
 */

import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Briefcase,
  Database,
  FileSpreadsheet,
  Lock,
  ShieldAlert,
  UploadCloud,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePortfolios } from "@/hooks/usePortfolios";
import { navigateToPortfolioDetail } from "@/lib/navigation";
import { portfolioKeys, snapshotKeys } from "@/lib/queryKeys";
import { ingestionService } from "@/services/ingestionService";
import { BrokerReportUploadResponse } from "@/types/api";
import { ExtractDropzone } from "./ExtractDropzone";
import { IngestionSummaryCard } from "./IngestionSummaryCard";
import { UploadProgressBar } from "./UploadProgressBar";

export const IngestionView: React.FC = () => {
  const { isAuthenticated, isTrader, isAdmin, user } = useAuth();
  const queryClient = useQueryClient();

  const { data: portfolios = [], isLoading: portfoliosLoading } =
    usePortfolios();

  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string>("");
  const [reconciliationMode, setReconciliationMode] = useState<
    "SNAPSHOT" | "MERGE"
  >("SNAPSHOT");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [uploadResult, setUploadResult] =
    useState<BrokerReportUploadResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  // Set default portfolio when portfolios are loaded
  useEffect(() => {
    if (portfolios.length > 0 && !selectedPortfolioId) {
      setSelectedPortfolioId(portfolios[0].id);
    }
  }, [portfolios, selectedPortfolioId]);

  const canUpload = isAuthenticated && (isTrader || isAdmin);

  const uploadMutation = useMutation({
    mutationFn: async ({
      file,
      portfolioId,
      mode,
    }: {
      file: File;
      portfolioId: string;
      mode: "SNAPSHOT" | "MERGE";
    }) => {
      abortControllerRef.current = new AbortController();
      return await ingestionService.uploadBrokerReport({
        file,
        portfolioId,
        mode,
        onProgress: (pct) => setUploadProgress(pct),
        signal: abortControllerRef.current.signal,
      });
    },
    onSuccess: (data, variables) => {
      setUploadResult(data);
      setUploadProgress(100);
      setErrorMessage(null);

      // Invalidate relevant portfolio and snapshot query caches
      queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
      if (variables.portfolioId) {
        queryClient.invalidateQueries({
          queryKey: portfolioKeys.detail(variables.portfolioId),
        });
        queryClient.invalidateQueries({
          queryKey: snapshotKeys.byPortfolio(variables.portfolioId),
        });
      }
    },
    onError: (err: any) => {
      setUploadProgress(0);
      const detail =
        err?.response?.data?.detail ||
        err?.response?.data?.error?.message ||
        err?.message ||
        "Error al procesar el extracto. Verifique el formato y las columnas requeridas.";
      setErrorMessage(
        typeof detail === "string" ? detail : JSON.stringify(detail)
      );
    },
  });

  const handleStartUpload = () => {
    if (!selectedFile) {
      setErrorMessage("Por favor, seleccione un archivo para continuar.");
      return;
    }

    if (!selectedPortfolioId) {
      setErrorMessage("Debe seleccionar una cartera destino para conciliar.");
      return;
    }

    if (!canUpload) {
      setErrorMessage("No cuenta con permisos para operar conciliaciones de cartera.");
      return;
    }

    setErrorMessage(null);
    setUploadProgress(0);
    uploadMutation.mutate({
      file: selectedFile,
      portfolioId: selectedPortfolioId,
      mode: reconciliationMode,
    });
  };

  const handleCancelUpload = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setUploadProgress(0);
    setErrorMessage("Carga de extracto cancelada por el operador.");
  };

  const handleResetForNewUpload = () => {
    setSelectedFile(null);
    setUploadResult(null);
    setUploadProgress(0);
    setErrorMessage(null);
  };

  const isUploading = uploadMutation.isPending;

  return (
    <div className="space-y-6">
      {/* View Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <UploadCloud className="h-6 w-6 text-sky-400" />
            Ingesta de Extractos Bursátiles
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Carga y conciliación transaccional de reportes de posición y boletos de ALyCs locales (BYMA / Merval).
          </p>
        </div>

        {/* RBAC Security Badge */}
        <div className="flex items-center gap-2 self-start md:self-auto">
          {canUpload ? (
            <span className="text-xs font-mono px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              Operador Autorizado ({user?.role})
            </span>
          ) : (
            <span className="text-xs font-mono px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5" />
              Modo Solo Lectura ({user?.role || "GUEST"})
            </span>
          )}
        </div>
      </div>

      {/* RBAC Lockout Notification for Viewer Role */}
      {!canUpload && (
        <div className="p-4 rounded-xl bg-amber-950/30 border border-amber-800/40 flex items-start gap-3">
          <ShieldAlert className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="text-xs text-amber-200">
            <p className="font-semibold text-amber-300">
              Operación Restringida por Política de Control de Acceso (RBAC)
            </p>
            <p className="mt-1 text-amber-200/80 leading-relaxed">
              Su cuenta tiene asignado el rol <strong>{user?.role || "GUEST"}</strong>.
              La carga y conciliación transaccional de extractos modifica las tenencias y valuaciones mark-to-market,
              requiriendo credenciales activas con privilegios de <strong>TRADER</strong> o <strong>ADMIN</strong>.
            </p>
          </div>
        </div>
      )}

      {/* When upload has succeeded, show the summary report */}
      {uploadResult ? (
        <IngestionSummaryCard
          result={uploadResult}
          onUploadAnother={handleResetForNewUpload}
          onNavigateToPortfolio={(id) => navigateToPortfolioDetail(id)}
        />
      ) : (
        /* Upload & Configuration Form */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Dropzone & Upload Action Area (2 Cols) */}
          <div className="lg:col-span-2 space-y-4">
            <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-6">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
                <span className="text-xs font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-2">
                  <FileSpreadsheet className="h-4 w-4 text-sky-400" />
                  Archivo de Posición o Boleto
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  CSV • XLSX • XLS (hasta 15 MB)
                </span>
              </div>

              {/* Accessible Dropzone */}
              <ExtractDropzone
                selectedFile={selectedFile}
                onFileSelect={(file) => {
                  setSelectedFile(file);
                  setErrorMessage(null);
                }}
                disabled={!canUpload || isUploading}
                errorMessage={errorMessage}
                onClearError={() => setErrorMessage(null)}
              />

              {/* Upload Progress Bar */}
              <UploadProgressBar
                progress={uploadProgress}
                isUploading={isUploading}
                fileName={selectedFile?.name}
                onCancel={handleCancelUpload}
              />

              {/* Action Trigger */}
              <div className="flex items-center justify-between pt-2">
                <span className="text-xs text-slate-400 font-mono">
                  {selectedFile
                    ? `1 archivo listo (${(selectedFile.size / 1024).toFixed(1)} KB)`
                    : "Seleccione un archivo para habilitar la conciliación"}
                </span>

                <button
                  type="button"
                  onClick={handleStartUpload}
                  disabled={!selectedFile || !canUpload || isUploading}
                  className={`px-5 py-2.5 rounded-xl text-xs font-semibold shadow-lg transition-all flex items-center gap-2 ${
                    !selectedFile || !canUpload || isUploading
                      ? "bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700"
                      : "bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white shadow-sky-600/20 active:scale-[0.98]"
                  }`}
                >
                  <UploadCloud className="h-4 w-4" />
                  <span>
                    {isUploading ? "Conciliando Extracto..." : "Conciliar Extracto"}
                  </span>
                </button>
              </div>
            </div>
          </div>

          {/* Configuration & Destination Portfolio Sidebar (1 Col) */}
          <div className="space-y-4">
            {/* Destination Portfolio Card */}
            <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
              <span className="text-xs font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-2">
                <Briefcase className="h-4 w-4 text-sky-400" />
                Cartera Destino
              </span>

              {portfoliosLoading ? (
                <div className="h-10 bg-slate-800/60 rounded-xl animate-pulse" />
              ) : portfolios.length === 0 ? (
                <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-400 text-center">
                  No se encontraron carteras disponibles para este usuario.
                </div>
              ) : (
                <div className="space-y-2">
                  <label
                    htmlFor="portfolio-selector"
                    className="text-xs text-slate-300 block font-medium"
                  >
                    Seleccionar portafolio:
                  </label>
                  <select
                    id="portfolio-selector"
                    value={selectedPortfolioId}
                    onChange={(e) => setSelectedPortfolioId(e.target.value)}
                    disabled={!canUpload || isUploading}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 disabled:opacity-50"
                  >
                    {portfolios.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.investor_profile})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Mode Selector */}
              <div className="space-y-2 pt-2 border-t border-slate-800/60">
                <label className="text-xs text-slate-300 block font-medium">
                  Modo de Conciliación:
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setReconciliationMode("SNAPSHOT")}
                    disabled={!canUpload || isUploading}
                    className={`px-3 py-2 rounded-xl text-xs font-mono transition-all text-left ${
                      reconciliationMode === "SNAPSHOT"
                        ? "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                        : "bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-300"
                    }`}
                  >
                    <span className="font-bold block">SNAPSHOT</span>
                    <span className="text-[10px] text-slate-400 block mt-0.5">
                      Reemplazo total
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setReconciliationMode("MERGE")}
                    disabled={!canUpload || isUploading}
                    className={`px-3 py-2 rounded-xl text-xs font-mono transition-all text-left ${
                      reconciliationMode === "MERGE"
                        ? "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                        : "bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-300"
                    }`}
                  >
                    <span className="font-bold block">MERGE</span>
                    <span className="text-[10px] text-slate-400 block mt-0.5">
                      Fusión delta
                    </span>
                  </button>
                </div>
              </div>
            </div>

            {/* Ingestion Pipeline Specifications Card */}
            <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-3">
              <span className="text-xs font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-2">
                <Database className="h-4 w-4 text-indigo-400" />
                Pipeline Automatizado
              </span>

              <div className="space-y-2.5 text-xs text-slate-400">
                <div className="flex items-start gap-2">
                  <div className="h-1.5 w-1.5 rounded-full bg-sky-400 mt-1.5 shrink-0" />
                  <p>
                    <strong>Detección de Esquema:</strong> Fuzzy matching sobre cabeceras de columnas para identificar ALyC (Balanz, IOL, PPI, etc.).
                  </p>
                </div>
                <div className="flex items-start gap-2">
                  <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
                  <p>
                    <strong>Saneamiento de Precios:</strong> Conversión monetaria bimoneda ARS/USD y tratamiento de ratios patológicos (EPS &le; 0).
                  </p>
                </div>
                <div className="flex items-start gap-2">
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
                  <p>
                    <strong>Aislamiento Transaccional:</strong> Operación atómica con rollback completo en caso de inconsistencia contable.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
