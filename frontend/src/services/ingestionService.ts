/**
 * Broker Statement Ingestion Service for InvestAI Enterprise Frontend.
 * Interacts with FastAPI POST /api/v1/ingestion/upload-report via multipart form data.
 */

import { apiClient } from "@/lib/apiClient";
import type { APIResponse, BrokerReportUploadResponse } from "@/types/api";

/** Loose backend payload: every field is optional until sanitized below. */
type RawUploadPayload = Partial<BrokerReportUploadResponse> & {
  invalid_records_count?: number;
};

export interface UploadBrokerReportParams {
  file: File;
  portfolioId?: string;
  mode?: "SNAPSHOT" | "MERGE";
  onProgress?: (pct: number) => void;
  signal?: AbortSignal;
}

/**
 * Heuristic detector for local Argentine broker extract formats based on filename patterns.
 */
function detectBrokerFromFilename(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.includes("balanz")) return "Balanz Capital";
  if (lower.includes("iol") || lower.includes("invertironline")) return "InvertirOnline (IOL)";
  if (lower.includes("ppi") || lower.includes("portfoliopersonal"))
    return "PPI (Portfolio Personal Inversiones)";
  if (lower.includes("bull") || lower.includes("bmb")) return "Bull Market Brokers";
  if (lower.includes("caja") || lower.includes("cvsa") || lower.includes("cajadevalores"))
    return "Caja de Valores";
  if (lower.includes("allaria")) return "Allaria Ledesma";
  if (lower.includes("galicia")) return "Banco Galicia";
  if (lower.includes("santander")) return "Santander Valores";
  return "Broker Local BYMA";
}

export const ingestionService = {
  /**
   * Uploads and reconciles a broker statement (.csv, .xlsx, .xls) into a portfolio.
   * Leverages browser automatic boundary calculation for multipart/form-data.
   */
  async uploadBrokerReport({
    file,
    portfolioId,
    mode = "SNAPSHOT",
    onProgress,
    signal,
  }: UploadBrokerReportParams): Promise<BrokerReportUploadResponse> {
    const formData = new FormData();
    formData.append("file", file);

    if (portfolioId && portfolioId.trim()) {
      formData.append("portfolio_id", portfolioId.trim());
    }

    if (mode) {
      formData.append("mode", mode);
    }

    const response = await apiClient.post<APIResponse<RawUploadPayload> | RawUploadPayload>(
      "/ingestion/upload-report",
      formData,
      {
        signal,
        params: {
          ...(portfolioId && portfolioId.trim() ? { portfolio_id: portfolioId.trim() } : {}),
          ...(mode ? { mode } : {}),
        },
        headers: {
          "Content-Type": undefined as unknown as string,
        },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total && onProgress) {
            const pct = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            onProgress(Math.min(100, Math.max(0, pct)));
          }
        },
      },
    );

    const rawData = response.data;
    const meta =
      rawData && typeof rawData === "object" && "meta" in rawData
        ? (rawData as APIResponse<RawUploadPayload>).meta
        : undefined;

    const data =
      rawData && typeof rawData === "object" && "data" in rawData
        ? (rawData as APIResponse<RawUploadPayload>).data
        : (rawData as RawUploadPayload);

    const totalRows = Number(data?.total_rows_parsed ?? 0);
    const validCount = Number(data?.valid_records_count ?? 0);
    const rejectedCount = Number(data?.invalid_records_count ?? data?.rejected_records_count ?? 0);

    const brokerDetected = data?.detected_broker || detectBrokerFromFilename(file.name);

    const reconciliation = data?.reconciliation
      ? {
          mode: data.reconciliation.mode || mode,
          holdings_added: Number(data.reconciliation.holdings_added ?? 0),
          holdings_updated: Number(data.reconciliation.holdings_updated ?? 0),
          holdings_removed: Number(data.reconciliation.holdings_removed ?? 0),
          warnings: data.reconciliation.warnings || [],
        }
      : undefined;

    const formattedMessage =
      data?.message ||
      `Extracto procesado con éxito. Se conciliarion ${validCount} tenencias válidas en la cartera.`;

    return {
      job_id: meta?.request_id || data?.job_id,
      filename: data?.filename || file.name,
      detected_broker: brokerDetected,
      total_rows_parsed: totalRows,
      valid_records_count: validCount,
      rejected_records_count: rejectedCount,
      message: formattedMessage,
      portfolio_id: data?.portfolio_id || portfolioId,
      created_at: meta?.timestamp || new Date().toISOString(),
      reconciliation,
      warnings: data?.warnings || [],
    };
  },
};
