/**
 * InvestAI Enterprise — Main Application Shell.
 * Hosts URL-first institutional navigation, AppLayout with Sidebar and TopHeader,
 * Portfolios Dashboard, System Health Diagnostics, and Prometheus Telemetry.
 */

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import {
  BarChart3,
  Database,
  Layers,
  Lock,
  RefreshCw,
  Server,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { PortfoliosView } from "@/components/portfolios/PortfoliosView";
import { PortfolioDetailView } from "@/components/portfolios/PortfolioDetailView";
import { IngestionView } from "@/components/ingestion/IngestionView";
import { AuthModal } from "@/components/auth/AuthModal";
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

export const App: React.FC = () => {
  const {
    section: activeSection,
    portfolioId,
    navigateToSection,
    navigateToPortfolioDetail,
  } = useHashRoute();

  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [metricsFilter, setMetricsFilter] = useState<string>("");

  // Query Backend Health endpoint
  const healthQuery = useQuery({
    queryKey: systemKeys.health(),
    queryFn: async (): Promise<HealthResponse> => {
      const res = await axios.get<HealthResponse>("/health", {
        headers: { "Content-Type": "application/json" },
      });
      return res.data;
    },
    refetchInterval: 10000,
  });

  // Query Prometheus Metrics endpoint
  const metricsQuery = useQuery({
    queryKey: systemKeys.metrics(),
    queryFn: async (): Promise<string> => {
      const res = await axios.get<string>("/metrics", {
        responseType: "text",
      });
      return res.data;
    },
    enabled: activeSection === "metrics",
    refetchInterval: 15000,
  });

  const hasAccessToken = !!authStorage.getAccessToken();
  const hasRefreshToken = !!authStorage.getRefreshToken();

  const filteredMetrics = useMemo(() => {
    if (!metricsQuery.data) return [];
    const lines = metricsQuery.data.split("\n");
    if (!metricsFilter) return lines.slice(0, 80);
    return lines.filter((line) =>
      line.toLowerCase().includes(metricsFilter.toLowerCase())
    );
  }, [metricsQuery.data, metricsFilter]);

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
          <div>
            <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              <Server className="h-5 w-5 text-sky-400" />
              Diagnóstico de Salud y Persistencia
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Monitoreo del runtime asíncrono, estado de base de datos y verificación de tokens
            </p>
          </div>

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
                  Valida la respuesta del bucle de eventos asíncrono y disponibilidad general.
                </p>

                {healthQuery.isSuccess && (
                  <div className="space-y-2 text-xs font-mono bg-slate-950 p-3 rounded border border-slate-800">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Estado:</span>
                      <span className="text-emerald-400 font-bold uppercase">
                        {healthQuery.data.status}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Entorno:</span>
                      <span className="text-slate-200">
                        {healthQuery.data.environment}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Latencia:</span>
                      <span className="text-sky-400">
                        {healthQuery.data.latency_ms} ms
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
                onClick={() => healthQuery.refetch()}
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
                    Persistencia
                  </span>
                  <div className="p-2 rounded-lg bg-emerald-950/60 text-emerald-400 border border-emerald-800/40">
                    <Database className="h-5 w-5" />
                  </div>
                </div>
                <h3 className="text-lg font-semibold mb-2">Base de Datos</h3>
                <p className="text-xs text-slate-400 mb-4">
                  Conectividad asíncrona con PostgreSQL / SQLite y estado de migraciones Alembic.
                </p>

                {healthQuery.isSuccess && (
                  <div className="space-y-2 text-xs font-mono bg-slate-950 p-3 rounded border border-slate-800">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Conexión:</span>
                      <span className="text-emerald-400 font-bold uppercase">
                        {healthQuery.data.database}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Última Sincronía:</span>
                      <span className="text-slate-300 truncate max-w-[140px]">
                        {new Date(healthQuery.data.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 flex items-center gap-2 text-xs text-slate-400 p-2.5 rounded bg-slate-950 border border-slate-800">
                <ShieldCheck className="h-4 w-4 text-emerald-400 shrink-0" />
                <span>Migración Base 001_initial_schema certificada.</span>
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
                  Interceptor Axios con inyección X-Request-ID y Mutex de Refresh ante 401.
                </p>

                <div className="space-y-2 text-xs font-mono bg-slate-950 p-3 rounded border border-slate-800">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Access Token:</span>
                    <span
                      className={
                        hasAccessToken ? "text-emerald-400" : "text-slate-500"
                      }
                    >
                      {hasAccessToken ? "Presente" : "No detectado"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Refresh Token:</span>
                    <span
                      className={
                        hasRefreshToken ? "text-emerald-400" : "text-slate-500"
                      }
                    >
                      {hasRefreshToken ? "Presente" : "No detectado"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Trace ID:</span>
                    <span className="text-sky-400 font-mono">
                      Automático (UUIDv4)
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-6 flex items-center gap-2 text-xs text-slate-400 p-2.5 rounded bg-slate-950 border border-slate-800">
                <Zap className="h-4 w-4 text-amber-400 shrink-0" />
                <span>Mutex anti-estampida listo para renovar tokens.</span>
              </div>
            </div>
          </div>

          {/* Architecture Summary */}
          <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
            <h3 className="text-base font-semibold flex items-center gap-2">
              <Layers className="h-5 w-5 text-sky-400" />
              Arquitectura de Contratos y Espejado DTO
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              El frontend se comunica con los routers de FastAPI mediante contratos
              TypeScript 1:1 tipados:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs text-slate-300">
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="font-semibold text-sky-400 block">
                  Contratos de Cartera y Órdenes:
                </span>
                <p className="text-slate-400">
                  <code className="text-slate-200">Portfolio</code>,{" "}
                  <code className="text-slate-200">Holding</code>,{" "}
                  <code className="text-slate-200">PortfolioCreateInput</code>
                </p>
              </div>
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1">
                <span className="font-semibold text-emerald-400 block">
                  Contratos de Seguridad y Sesión:
                </span>
                <p className="text-slate-400">
                  <code className="text-slate-200">User</code>,{" "}
                  <code className="text-slate-200">AuthTokens</code>,{" "}
                  <code className="text-slate-200">APIResponse&lt;T&gt;</code>
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 3: Prometheus RED Telemetry */}
      {activeSection === "metrics" && (
        <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col gap-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <BarChart3 className="h-5 w-5 text-sky-400" />
                Exposición de Métricas Prometheus (/metrics)
              </h3>
              <p className="text-xs text-slate-400">
                Captura métricas RED (Rate, Errors, Duration), contadores de Scheduler y Solvers cuantitativos.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="text"
                placeholder="Filtrar métricas..."
                value={metricsFilter}
                onChange={(e) => setMetricsFilter(e.target.value)}
                className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
              <button
                onClick={() => metricsQuery.refetch()}
                disabled={metricsQuery.isFetching}
                className="py-1.5 px-3 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 flex items-center gap-1.5 transition"
              >
                <RefreshCw
                  className={`h-3 w-3 ${metricsQuery.isFetching ? "animate-spin" : ""}`}
                />
                Actualizar
              </button>
            </div>
          </div>

          {metricsQuery.isLoading && (
            <div className="p-8 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
              <RefreshCw className="h-4 w-4 animate-spin text-sky-400" />
              Obteniendo telemetría en vivo...
            </div>
          )}

          {metricsQuery.isError && (
            <div className="p-4 rounded bg-rose-950/40 border border-rose-800 text-xs text-rose-300">
              Error al leer métricas: {String(metricsQuery.error)}
            </div>
          )}

          {metricsQuery.isSuccess && (
            <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 max-h-[500px] overflow-y-auto font-mono text-xs text-slate-300 space-y-1">
              {filteredMetrics.length > 0 ? (
                filteredMetrics.map((line, idx) => (
                  <div
                    key={idx}
                    className={
                      line.startsWith("# HELP")
                        ? "text-sky-400 font-semibold mt-2"
                        : line.startsWith("# TYPE")
                        ? "text-slate-500 italic"
                        : line.startsWith("http_")
                        ? "text-emerald-400"
                        : line.startsWith("quant_")
                        ? "text-indigo-400"
                        : "text-slate-300"
                    }
                  >
                    {line}
                  </div>
                ))
              ) : (
                <div className="text-slate-500 italic">
                  No se encontraron métricas coincidentes con "{metricsFilter}".
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* SECTION 4: Broker Statement Ingestion */}
      {activeSection === "ingestion" && <IngestionView />}

      {/* Global Auth Modal for Session Initiation / Registration */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
      />
    </AppLayout>
  );
};
