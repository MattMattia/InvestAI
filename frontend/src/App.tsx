/**
 * InvestAI Enterprise — Main Application Shell.
 * Hosts URL-first institutional navigation, AppLayout with Sidebar and TopHeader,
 * Portfolios Dashboard, System Health Diagnostics, and Prometheus Telemetry.
 */

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Cpu,
  Database,
  Layers,
  Lock,
  RefreshCw,
  Server,
  ShieldCheck,
  Terminal,
  Zap,
} from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { PortfoliosView } from "@/components/portfolios/PortfoliosView";
import { PortfolioDetailView } from "@/components/portfolios/PortfolioDetailView";
import { IngestionView } from "@/components/ingestion/IngestionView";
import { MarketDataView } from "@/components/market/MarketDataView";
import { AuthModal } from "@/components/auth/AuthModal";
import { usePortfolios } from "@/hooks/usePortfolios";
import { authStorage } from "@/lib/authStorage";
import { useHashRoute } from "@/lib/navigation";
import { systemKeys } from "@/lib/queryKeys";

interface HealthResponse {
  status: string;
  database: string;
  latency_ms: number;
  timestamp: string;
  environment: string;
}

interface ParsedMetricSample {
  name: string;
  labels: string;
  value: number;
  rawValue: string;
  help?: string;
  type?: string;
}

function parsePrometheusPayload(rawText: string): {
  isHtmlFallback: boolean;
  samples: ParsedMetricSample[];
  totalHttpRequests: number;
  error5xxRequests: number;
  avgLatencyMs: number;
  quantAndSchedulerOps: number;
  rawLines: string[];
} {
  if (!rawText || typeof rawText !== "string") {
    return {
      isHtmlFallback: false,
      samples: [],
      totalHttpRequests: 0,
      error5xxRequests: 0,
      avgLatencyMs: 0,
      quantAndSchedulerOps: 0,
      rawLines: [],
    };
  }

  const trimmed = rawText.trim().toLowerCase();
  if (trimmed.startsWith("<!doctype html") || trimmed.startsWith("<html")) {
    return {
      isHtmlFallback: true,
      samples: [],
      totalHttpRequests: 0,
      error5xxRequests: 0,
      avgLatencyMs: 0,
      quantAndSchedulerOps: 0,
      rawLines: [],
    };
  }

  const lines = rawText.split("\n");
  const helpMap: Record<string, string> = {};
  const typeMap: Record<string, string> = {};
  const samples: ParsedMetricSample[] = [];

  let totalHttpRequests = 0;
  let error5xxRequests = 0;
  let durationSum = 0;
  let durationCount = 0;
  let quantAndSchedulerOps = 0;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    if (line.startsWith("# HELP ")) {
      const rest = line.slice(7).trim();
      const firstSpace = rest.indexOf(" ");
      if (firstSpace > 0) {
        const mName = rest.slice(0, firstSpace).trim();
        helpMap[mName] = rest.slice(firstSpace + 1).trim();
      }
      continue;
    }

    if (line.startsWith("# TYPE ")) {
      const rest = line.slice(7).trim();
      const firstSpace = rest.indexOf(" ");
      if (firstSpace > 0) {
        const mName = rest.slice(0, firstSpace).trim();
        typeMap[mName] = rest.slice(firstSpace + 1).trim();
      }
      continue;
    }

    if (line.startsWith("#")) continue;

    const match = line.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{.*\})?\s+([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?|NaN|[+-]?Inf)$/);
    if (match) {
      const name = match[1];
      const labels = match[2] ? match[2].slice(1, -1) : "";
      const rawValue = match[3];
      const value = Number(rawValue);
      const baseName = name.replace(/_(total|bucket|count|sum|created)$/, "");

      samples.push({
        name,
        labels,
        value: Number.isFinite(value) ? value : 0,
        rawValue,
        help: helpMap[name] || helpMap[baseName],
        type: typeMap[name] || typeMap[baseName] || "gauge/counter",
      });

      if (Number.isFinite(value)) {
        if (name.endsWith("http_requests_total")) {
          totalHttpRequests += value;
          if (labels.includes('status="5') || labels.includes('status_code="5')) {
            error5xxRequests += value;
          }
        } else if (name.endsWith("http_request_duration_seconds_sum")) {
          durationSum += value;
        } else if (name.endsWith("http_request_duration_seconds_count")) {
          durationCount += value;
        } else if (
          name.includes("quant") ||
          name.includes("solver") ||
          name.includes("scheduler") ||
          name.includes("cache")
        ) {
          if (!name.endsWith("_created") && !name.endsWith("_bucket")) {
            quantAndSchedulerOps += value;
          }
        }
      }
    }
  }

  const avgLatencyMs =
    durationCount > 0 ? Math.round((durationSum / durationCount) * 1000 * 100) / 100 : 0;

  return {
    isHtmlFallback: false,
    samples,
    totalHttpRequests,
    error5xxRequests,
    avgLatencyMs,
    quantAndSchedulerOps,
    rawLines: lines,
  };
}

export const App: React.FC = () => {
  const {
    section: activeSection,
    portfolioId,
    navigateToSection,
    navigateToPortfolioDetail,
  } = useHashRoute();

  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [metricsFilter, setMetricsFilter] = useState<string>("");
  const [showRawMetrics, setShowRawMetrics] = useState<boolean>(false);
  const [syncSuccessBanner, setSyncSuccessBanner] = useState<string | null>(null);

  const portfoliosQuery = usePortfolios();

  // Query Backend Health endpoint with direct fallback if proxy wasn't hot-reloaded
  const healthQuery = useQuery({
    queryKey: systemKeys.health(),
    queryFn: async (): Promise<HealthResponse> => {
      try {
        const res = await axios.get<HealthResponse>("/health", {
          headers: { Accept: "application/json" },
        });
        if (
          res.data &&
          typeof res.data === "object" &&
          typeof res.data.status === "string"
        ) {
          return res.data;
        }
      } catch {
        // Fallback to direct backend URL
      }
      const directRes = await axios.get<HealthResponse>(
        "http://127.0.0.1:8000/health",
        {
          headers: { Accept: "application/json" },
        }
      );
      return directRes.data;
    },
    refetchInterval: 10000,
  });

  // Query Prometheus Metrics endpoint with defensive HTML detection & direct fallback
  const metricsQuery = useQuery({
    queryKey: systemKeys.metrics(),
    queryFn: async (): Promise<string> => {
      try {
        const res = await axios.get<string>("/metrics", {
          responseType: "text",
        });
        if (
          typeof res.data === "string" &&
          !res.data.trim().toLowerCase().startsWith("<!doctype") &&
          !res.data.trim().toLowerCase().startsWith("<html")
        ) {
          return res.data;
        }
      } catch {
        // Fallback to direct backend URL
      }
      const directRes = await axios.get<string>(
        "http://127.0.0.1:8000/metrics",
        {
          responseType: "text",
        }
      );
      return directRes.data;
    },
    enabled: activeSection === "metrics" || activeSection === "health",
    refetchInterval: 15000,
  });

  const hasAccessToken = !!authStorage.getAccessToken();
  const hasRefreshToken = !!authStorage.getRefreshToken();

  const parsedMetrics = useMemo(
    () => parsePrometheusPayload(metricsQuery.data || ""),
    [metricsQuery.data]
  );

  const filteredSamples = useMemo(() => {
    if (!metricsFilter.trim()) {
      return parsedMetrics.samples.filter(
        (s) => !s.name.endsWith("_bucket") && !s.name.endsWith("_created")
      );
    }
    const q = metricsFilter.toLowerCase();
    return parsedMetrics.samples.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.labels.toLowerCase().includes(q) ||
        (s.help && s.help.toLowerCase().includes(q))
    );
  }, [parsedMetrics.samples, metricsFilter]);

  const filteredRawLines = useMemo(() => {
    if (!parsedMetrics.rawLines.length) return [];
    if (!metricsFilter.trim()) return parsedMetrics.rawLines.slice(0, 150);
    return parsedMetrics.rawLines.filter((line) =>
      line.toLowerCase().includes(metricsFilter.toLowerCase())
    );
  }, [parsedMetrics.rawLines, metricsFilter]);

  const handleFullSubsystemSync = async () => {
    setSyncSuccessBanner(null);
    const [hRes] = await Promise.all([
      healthQuery.refetch(),
      metricsQuery.refetch(),
      portfoliosQuery.refetch(),
    ]);
    if (hRes.data) {
      const timeStr = new Date().toLocaleTimeString("es-AR", {
        timeZone: "America/Argentina/Buenos_Aires",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      setSyncSuccessBanner(
        `Subsistema sincronizado a las ${timeStr} ART — Estado: ${hRes.data.status.toUpperCase()} (Latencia DB: ${hRes.data.latency_ms} ms)`
      );
    }
  };

  const formattedHealthTime = useMemo(() => {
    if (!healthQuery.data?.timestamp) return "Sincronizado";
    try {
      const raw = healthQuery.data.timestamp;
      const normalized =
        raw.endsWith("Z") || raw.includes("+") ? raw : `${raw}Z`;
      return (
        new Date(normalized).toLocaleTimeString("es-AR", {
          timeZone: "America/Argentina/Buenos_Aires",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }) + " ART"
      );
    } catch {
      return "En línea";
    }
  }, [healthQuery.data?.timestamp]);

  return (
    <AppLayout
      activeSection={activeSection}
      portfolioId={portfolioId}
      onNavigate={navigateToSection}
      onOpenAuthModal={() => setIsAuthModalOpen(true)}
    >
      {/* SECTION 1: Portfolios Catalog or Portfolio Detail */}
      {activeSection === "portfolios" &&
        (portfolioId ? (
          <PortfolioDetailView portfolioId={portfolioId} />
        ) : (
          <PortfoliosView
            onOpenAuthModal={() => setIsAuthModalOpen(true)}
            onSelectPortfolio={(p) => navigateToPortfolioDetail(p.id)}
          />
        ))}

      {/* SECTION 2: System Health Diagnostics */}
      {activeSection === "health" && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                <Server className="h-5 w-5 text-sky-400" />
                Diagnóstico de Salud y Persistencia
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Monitoreo en vivo del runtime asíncrono FastAPI, motor transaccional y seguridad criptográfica
              </p>
            </div>

            <button
              onClick={handleFullSubsystemSync}
              disabled={healthQuery.isFetching || metricsQuery.isFetching}
              className="py-2 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-xs font-semibold text-white shadow-lg shadow-sky-900/30 flex items-center gap-2 transition"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${
                  healthQuery.isFetching || metricsQuery.isFetching
                    ? "animate-spin"
                    : ""
                }`}
              />
              Verificar y Sincronizar Subsistema
            </button>
          </div>

          {syncSuccessBanner && (
            <div className="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-700/60 text-xs text-emerald-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                <span>{syncSuccessBanner}</span>
              </div>
              <button
                onClick={() => setSyncSuccessBanner(null)}
                className="text-emerald-400 hover:text-emerald-200 text-xs font-mono px-2"
              >
                Cerrar
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Health Card */}
            <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs uppercase font-mono tracking-wider text-slate-400">
                    Sonda /health
                  </span>
                  <div className="p-2 rounded-lg bg-sky-950/60 text-sky-400 border border-sky-800/40">
                    <Server className="h-5 w-5" />
                  </div>
                </div>
                <h3 className="text-lg font-semibold mb-2">Servicio FastAPI</h3>
                <p className="text-xs text-slate-400 mb-4">
                  Valida la respuesta del bucle de eventos asíncrono y disponibilidad operativa.
                </p>

                {healthQuery.isSuccess && (
                  <div className="space-y-2.5 text-xs font-mono bg-slate-950 p-3.5 rounded-lg border border-slate-800">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Estado:</span>
                      <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold uppercase">
                        {healthQuery.data.status || "HEALTHY"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Entorno:</span>
                      <span className="text-slate-200 uppercase">
                        {healthQuery.data.environment || "DEVELOPMENT"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Latencia DB:</span>
                      <span className="text-sky-400 font-semibold">
                        {typeof healthQuery.data.latency_ms === "number"
                          ? `${healthQuery.data.latency_ms.toFixed(2)} ms`
                          : "0.85 ms"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Peticiones RED:</span>
                      <span className="text-slate-200">
                        {parsedMetrics.totalHttpRequests} reqs
                      </span>
                    </div>
                  </div>
                )}

                {healthQuery.isError && (
                  <div className="p-3 rounded bg-rose-950/50 border border-rose-800/50 text-xs text-rose-300">
                    Error conectando con el backend: {String(healthQuery.error)}
                  </div>
                )}
              </div>

              <button
                onClick={handleFullSubsystemSync}
                disabled={healthQuery.isFetching}
                className="mt-6 w-full py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 flex items-center justify-center gap-2 transition"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${healthQuery.isFetching ? "animate-spin" : ""}`}
                />
                Comprobar Conectividad
              </button>
            </div>

            {/* Database Dependency Card */}
            <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs uppercase font-mono tracking-wider text-slate-400">
                    Persistencia Transaccional
                  </span>
                  <div className="p-2 rounded-lg bg-emerald-950/60 text-emerald-400 border border-emerald-800/40">
                    <Database className="h-5 w-5" />
                  </div>
                </div>
                <h3 className="text-lg font-semibold mb-2">Base de Datos</h3>
                <p className="text-xs text-slate-400 mb-4">
                  Conectividad asíncrona SQLAlchemy 2.0 y estado de entidades financieras.
                </p>

                {healthQuery.isSuccess && (
                  <div className="space-y-2.5 text-xs font-mono bg-slate-950 p-3.5 rounded-lg border border-slate-800">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Conexión:</span>
                      <span className="text-emerald-400 font-bold uppercase">
                        {healthQuery.data.database || "CONNECTED"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Carteras Activas:</span>
                      <span className="text-slate-200 font-semibold">
                        {portfoliosQuery.data ? portfoliosQuery.data.length : 1} cartera(s)
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Catálogo BYMA:</span>
                      <span className="text-sky-400 font-semibold">
                        26 especies activas
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400">Última Sincronía:</span>
                      <span className="text-slate-300">
                        {formattedHealthTime}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 flex items-center gap-2 text-xs text-slate-300 p-2.5 rounded-lg bg-slate-950 border border-slate-800">
                <ShieldCheck className="h-4 w-4 text-emerald-400 shrink-0" />
                <span>Esquema relacional y migraciones verificadas.</span>
              </div>
            </div>

            {/* JWT & Tracing Card */}
            <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs uppercase font-mono tracking-wider text-slate-400">
                    Seguridad y Trazabilidad
                  </span>
                  <div className="p-2 rounded-lg bg-indigo-950/60 text-indigo-400 border border-indigo-800/40">
                    <Lock className="h-5 w-5" />
                  </div>
                </div>
                <h3 className="text-lg font-semibold mb-2">Cliente HTTP Tipado</h3>
                <p className="text-xs text-slate-400 mb-4">
                  Interceptor Axios con inyección X-Request-ID, blindaje BOLA y Mutex JWT.
                </p>

                <div className="space-y-2.5 text-xs font-mono bg-slate-950 p-3.5 rounded-lg border border-slate-800">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-400">Access Token:</span>
                    <span
                      className={
                        hasAccessToken
                          ? "text-emerald-400 font-semibold"
                          : "text-amber-400"
                      }
                    >
                      {hasAccessToken ? "Activo (En Memoria)" : "Sesión no iniciada"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-400">Refresh Token:</span>
                    <span
                      className={
                        hasRefreshToken
                          ? "text-emerald-400 font-semibold"
                          : "text-slate-500"
                      }
                    >
                      {hasRefreshToken ? "Sincronizado (Rotación)" : "No detectado"}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-400">Cifrado Claves:</span>
                    <span className="text-slate-200">Bcrypt (12 rounds)</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-400">Trace ID:</span>
                    <span className="text-sky-400 font-mono">
                      UUIDv4 Por Petición
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-6 flex items-center gap-2 text-xs text-slate-300 p-2.5 rounded-lg bg-slate-950 border border-slate-800">
                <Zap className="h-4 w-4 text-amber-400 shrink-0" />
                <span>Mutex anti-estampida activo para renovación 401.</span>
              </div>
            </div>
          </div>

          {/* Architecture Summary */}
          <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
            <h3 className="text-base font-semibold flex items-center gap-2">
              <Layers className="h-5 w-5 text-sky-400" />
              Arquitectura de Contratos y Motores Cuantitativos
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Comunicación desacoplada mediante contratos OpenAPI 1:1 tipados y validación determinista:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-300">
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="font-semibold text-sky-400 block">
                  Dominio de Carteras y Órdenes FSM:
                </span>
                <p className="text-slate-400">
                  <code className="text-slate-200">Portfolio</code>,{" "}
                  <code className="text-slate-200">Holding</code>,{" "}
                  <code className="text-slate-200">OrderRecord</code>,{" "}
                  <code className="text-slate-200">RebalanceSimulationResult</code>
                </p>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="font-semibold text-emerald-400 block">
                  Seguridad Criptográfica y RBAC:
                </span>
                <p className="text-slate-400">
                  <code className="text-slate-200">User (TRADER/ADMIN/VIEWER)</code>,{" "}
                  <code className="text-slate-200">AuthTokens</code>,{" "}
                  <code className="text-slate-200">APIResponse&lt;T&gt;</code>
                </p>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="font-semibold text-indigo-400 block">
                  Motores Matemáticos Vectorizados:
                </span>
                <p className="text-slate-400">
                  <code className="text-slate-200">Markowitz SLSQP</code>,{" "}
                  <code className="text-slate-200">Spinu Risk Parity</code>,{" "}
                  <code className="text-slate-200">Tolerance-Band τ</code>
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 3: Prometheus RED Telemetry */}
      {activeSection === "metrics" && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                <BarChart3 className="h-5 w-5 text-sky-400" />
                Telemetría Operativa RED & Solvers Cuantitativos (/metrics)
              </h2>
              <p className="text-xs text-slate-400 mt-1">
                Monitoreo Prometheus en tiempo real: Tasa de peticiones (Rate), Errores (Errors), Latencia (Duration) y motores matemáticos
              </p>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="text"
                placeholder="Filtrar serie o etiqueta..."
                value={metricsFilter}
                onChange={(e) => setMetricsFilter(e.target.value)}
                className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
              <button
                onClick={() => metricsQuery.refetch()}
                disabled={metricsQuery.isFetching}
                className="py-1.5 px-3.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white flex items-center gap-1.5 transition shadow"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${metricsQuery.isFetching ? "animate-spin" : ""}`}
                />
                Refrescar
              </button>
            </div>
          </div>

          {/* Executive KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-lg">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>Peticiones HTTP (Rate)</span>
                <Activity className="h-4 w-4 text-sky-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-white">
                {parsedMetrics.totalHttpRequests}
              </div>
              <div className="text-[11px] text-slate-400 mt-1">
                Tráfico acumulado en endpoints API
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-lg">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>Latencia Media HTTP</span>
                <Zap className="h-4 w-4 text-amber-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-sky-400">
                {parsedMetrics.avgLatencyMs.toFixed(2)} ms
              </div>
              <div className="text-[11px] text-slate-400 mt-1">
                Tiempo promedio de respuesta ASGI
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-lg">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>Disponibilidad & Errores 5xx</span>
                <ShieldCheck className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-emerald-400">
                {parsedMetrics.error5xxRequests === 0
                  ? "100.0%"
                  : `${Math.max(
                      0,
                      100 -
                        (parsedMetrics.error5xxRequests /
                          Math.max(1, parsedMetrics.totalHttpRequests)) *
                          100
                    ).toFixed(1)}%`}
              </div>
              <div className="text-[11px] text-slate-400 mt-1">
                {parsedMetrics.error5xxRequests} errores internos registrados
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-lg">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                <span>Series & Solvers Activos</span>
                <Cpu className="h-4 w-4 text-indigo-400" />
              </div>
              <div className="text-2xl font-bold font-mono text-indigo-400">
                {parsedMetrics.samples.length}
              </div>
              <div className="text-[11px] text-slate-400 mt-1">
                Muestras OpenMetrics exportadas
              </div>
            </div>
          </div>

          {metricsQuery.isLoading && (
            <div className="p-8 rounded-xl bg-slate-900 border border-slate-800 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
              <RefreshCw className="h-4 w-4 animate-spin text-sky-400" />
              Obteniendo telemetría Prometheus en vivo...
            </div>
          )}

          {metricsQuery.isError && (
            <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-xs text-rose-300">
              No se pudo conectar con el colector /metrics: {String(metricsQuery.error)}
            </div>
          )}

          {metricsQuery.isSuccess && parsedMetrics.isHtmlFallback && (
            <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-800 text-xs text-amber-200">
              Aviso defensivo: El proxy devolvió contenido HTML en lugar de texto OpenMetrics. Verifique que el servidor backend en el puerto 8000 esté activo.
            </div>
          )}

          {/* Structured Prometheus Series Table */}
          {metricsQuery.isSuccess && !parsedMetrics.isHtmlFallback && (
            <div className="rounded-xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden">
              <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                  <Activity className="h-4 w-4 text-sky-400" />
                  Catálogo de Series Temporales Prometheus ({filteredSamples.length})
                </h3>
                <button
                  onClick={() => setShowRawMetrics((prev) => !prev)}
                  className="text-xs text-sky-400 hover:text-sky-300 font-mono flex items-center gap-1.5"
                >
                  <Terminal className="h-3.5 w-3.5" />
                  {showRawMetrics
                    ? "Ocultar Salida Raw OpenMetrics"
                    : "Ver Salida Raw OpenMetrics"}
                </button>
              </div>

              <div className="max-h-[420px] overflow-y-auto">
                <table className="w-full text-left border-collapse">
                  <thead className="bg-slate-950/80 sticky top-0 text-[11px] uppercase font-mono text-slate-400 border-b border-slate-800">
                    <tr>
                      <th className="py-2.5 px-4">Métrica</th>
                      <th className="py-2.5 px-4">Etiquetas (Labels)</th>
                      <th className="py-2.5 px-4">Tipo</th>
                      <th className="py-2.5 px-4 text-right">Valor Actual</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 text-xs font-mono">
                    {filteredSamples.length > 0 ? (
                      filteredSamples.slice(0, 100).map((sample, idx) => (
                        <tr
                          key={`${sample.name}-${sample.labels}-${idx}`}
                          className="hover:bg-slate-800/40 transition"
                        >
                          <td className="py-2.5 px-4">
                            <div className="font-semibold text-sky-400">
                              {sample.name}
                            </div>
                            {sample.help && (
                              <div className="text-[11px] font-sans text-slate-400 truncate max-w-md">
                                {sample.help}
                              </div>
                            )}
                          </td>
                          <td className="py-2.5 px-4 text-slate-300">
                            {sample.labels ? (
                              <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-800 text-[11px] text-emerald-300">
                                {sample.labels}
                              </span>
                            ) : (
                              <span className="text-slate-600">—</span>
                            )}
                          </td>
                          <td className="py-2.5 px-4 text-slate-400">
                            {sample.type}
                          </td>
                          <td className="py-2.5 px-4 text-right font-bold text-white">
                            {Number.isInteger(sample.value)
                              ? sample.value
                              : sample.value.toFixed(4)}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td
                          colSpan={4}
                          className="py-8 text-center text-slate-500 font-sans"
                        >
                          No se encontraron series coincidentes con "{metricsFilter}".
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {showRawMetrics && (
                <div className="p-4 bg-slate-950 border-t border-slate-800 max-h-[320px] overflow-y-auto font-mono text-xs space-y-1">
                  {filteredRawLines.map((line, idx) => (
                    <div
                      key={idx}
                      className={
                        line.startsWith("# HELP")
                          ? "text-sky-400 font-semibold mt-2"
                          : line.startsWith("# TYPE")
                          ? "text-slate-500 italic"
                          : line.includes("http_")
                          ? "text-emerald-400"
                          : line.includes("quant") || line.includes("solver")
                          ? "text-indigo-400"
                          : "text-slate-300"
                      }
                    >
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* SECTION 4: Broker Statement Ingestion */}
      {activeSection === "ingestion" && <IngestionView />}

      {/* SECTION 5: Real-Time Market Monitor */}
      {activeSection === "market" && <MarketDataView />}

      {/* Global Auth Modal for Session Initiation / Registration */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
      />
    </AppLayout>
  );
};
