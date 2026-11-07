import { AlertCircle, CheckCircle2, FileSpreadsheet, UploadCloud, X } from "lucide-react";
import type React from "react";
import { useRef, useState } from "react";
import { extractErrorMessage } from "../lib/apiClient";
import type { IngestionReport } from "../types/portfolio";

interface FileUploaderProps {
  portfolioId: string | null;
  onUploadFile: (file: File) => Promise<IngestionReport>;
  onUploadSuccess: () => void;
}

export const FileUploader: React.FC<FileUploaderProps> = ({
  portfolioId,
  onUploadFile,
  onUploadSuccess,
}) => {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [report, setReport] = useState<IngestionReport | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => {
    setDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["csv", "xlsx", "xls"].includes(ext || "")) {
      setErrorMessage("Formato no soportado. Por favor sube un archivo .CSV o .XLSX");
      return;
    }
    setSelectedFile(file);
    setErrorMessage(null);
    setReport(null);
  };

  const handleUpload = async () => {
    if (!selectedFile || !portfolioId) return;
    setUploading(true);
    setErrorMessage(null);
    try {
      const res = await onUploadFile(selectedFile);
      setReport(res);
      if (res.valid_records_count > 0) {
        onUploadSuccess();
      }
    } catch (err: unknown) {
      setErrorMessage(
        extractErrorMessage(err, "Error al procesar el archivo en el servidor.", ["message"]),
      );
    } finally {
      setUploading(false);
    }
  };

  const clearSelection = () => {
    setSelectedFile(null);
    setReport(null);
    setErrorMessage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-bold text-white flex items-center space-x-2">
            <FileSpreadsheet className="w-5 h-5 text-sky-400" />
            <span>Ingesta Universal de Portafolio</span>
          </h3>
          <p className="text-xs text-slate-400">
            Importa reportes tabulares (.CSV, .XLSX) con saneamiento automático y tolerancia a
            fallos
          </p>
        </div>
      </div>

      <div
        className={`relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition ${
          dragOver
            ? "border-sky-500 bg-sky-950/20"
            : "border-slate-700 hover:border-slate-600 bg-slate-900/40"
        }`}
      >
        <button
          type="button"
          aria-label="Examinar y seleccionar un reporte"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className="absolute inset-0 h-full w-full rounded-xl cursor-pointer"
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={handleFileChange}
          className="hidden"
        />

        <UploadCloud className="w-10 h-10 text-slate-400 mx-auto mb-2" />
        <p className="text-sm font-semibold text-slate-200">
          Arrastra tu reporte de Balanz / Broker aquí o haz clic para examinar
        </p>
        <p className="text-xs text-slate-400 mt-1">
          Soporta CSV, XLSX con coma o punto decimal y nombres adaptativos
        </p>
      </div>

      {/* Selected file preview */}
      {selectedFile && (
        <div className="mt-4 p-3 bg-slate-900 border border-slate-700 rounded-lg flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <FileSpreadsheet className="w-5 h-5 text-sky-400" />
            <div>
              <div className="text-xs font-semibold text-white">{selectedFile.name}</div>
              <div className="text-[11px] text-slate-400">
                {(selectedFile.size / 1024).toFixed(1)} KB
              </div>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={clearSelection}
              className="text-slate-400 hover:text-white p-1 rounded transition"
              title="Quitar archivo"
            >
              <X className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={handleUpload}
              disabled={uploading || !portfolioId}
              className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-semibold px-4 py-2 rounded-lg transition flex items-center space-x-1"
            >
              {uploading ? "Procesando..." : "Subir e Ingerir"}
            </button>
          </div>
        </div>
      )}

      {/* Error Message */}
      {errorMessage && (
        <div className="mt-4 p-3 bg-rose-950/60 border border-rose-800 rounded-lg flex items-start space-x-2 text-rose-200 text-xs">
          <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Ingestion Report Feedback */}
      {report && (
        <div
          className={`mt-4 p-4 rounded-lg border ${
            report.is_successful
              ? "bg-emerald-950/40 border-emerald-800 text-emerald-200"
              : "bg-amber-950/40 border-amber-800 text-amber-200"
          }`}
        >
          <div className="flex items-center space-x-2 font-bold text-sm mb-2">
            {report.is_successful ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            ) : (
              <AlertCircle className="w-5 h-5 text-amber-400" />
            )}
            <span>
              {report.is_successful
                ? "Ingesta Exitosa y Saneada"
                : "Ingesta Completada con Advertencias"}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs font-medium my-2">
            <div className="bg-slate-900/60 p-2 rounded">
              <span className="text-slate-400 block">Total Filas:</span>
              <span className="font-bold text-white text-sm">{report.total_rows}</span>
            </div>
            <div className="bg-slate-900/60 p-2 rounded">
              <span className="text-emerald-400 block">Válidas Ingeridas:</span>
              <span className="font-bold text-emerald-400 text-sm">
                {report.valid_records_count}
              </span>
            </div>
            <div className="bg-slate-900/60 p-2 rounded">
              <span className="text-rose-400 block">Descartadas / Corruptas:</span>
              <span className="font-bold text-rose-400 text-sm">
                {report.discarded_records_count}
              </span>
            </div>
          </div>

          {report.errors.length > 0 && (
            <div className="mt-3 pt-2 border-t border-amber-800/60">
              <span className="text-xs font-bold block mb-1 text-amber-300">
                Detalle de anomalías descartadas ({report.errors.length}):
              </span>
              <ul className="list-disc list-inside space-y-1 text-[11px] text-slate-300 max-h-32 overflow-y-auto">
                {report.errors.map((e) => (
                  <li
                    key={`${e.row ?? "general"}-${e.ticker ?? ""}-${e.error_type}-${e.detail ?? e.message ?? ""}`}
                  >
                    {e.row ? `Fila ${e.row}` : "General"} ({e.ticker || "Sin ticker"}):{" "}
                    {e.detail || e.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
