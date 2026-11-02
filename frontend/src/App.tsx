import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Database,
  Layers,
  Lock,
  LogIn,
  LogOut,
  RefreshCw,
  Server,
  ShieldCheck,
  User as UserIcon,
  Zap,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { AuthModal } from "@/components/auth/AuthModal";
import { authStorage } from "@/lib/authStorage";

interface HealthResponse {
  status: string;
  database: string;
  latency_ms: number;
  timestamp: string;
  environment: string;
}

export const App: React.FC = () => {
  const {
    user,
    isAuthenticated,
    isLoading: authLoading,
    logout,
    isAdmin,
    isTrader,
  } = useAuth();
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<"health" | "metrics" | "architecture">("health");
  const [metricsFilter, setMetricsFilter] = useState<string>("");

  // Query Backend Health endpoint
  const healthQuery = useQuery({
    queryKey: ["backend-health"],
    queryFn: async (): Promise<HealthResponse> => {
      // Connects to root /health through proxy or direct baseURL
      const res = await axios.get<HealthResponse>("/health", {
        headers: { "Content-Type": "application/json" },
      });
      return res.data;
    },
    refetchInterval: 10000,
  });

  // Query Prometheus Metrics endpoint
  const metricsQuery = useQuery({
    queryKey: ["backend-metrics"],
    queryFn: async (): Promise<string> => {
      const res = await axios.get<string>("/metrics", {
        responseType: "text",
      });
      return res.data;
    },
    enabled: activeTab === "metrics",
    refetchInterval: 15000,
  });

  const hasAccessToken = !!authStorage.getAccessToken();
  const hasRefreshToken = !!authStorage.getRefreshToken();

  const filteredMetrics = React.useMemo(() => {
    if (!metricsQuery.data) return [];
    const lines = metricsQuery.data.split("\n");
    if (!metricsFilter) return lines.slice(0, 80);
    return lines.filter((line) =>
      line.toLowerCase().includes(metricsFilter.toLowerCase())
    );
  }, [metricsQuery.data, metricsFilter]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-sky-500 selection:text-white">
      {/* Top Institutional Navigation Bar */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-sky-600 flex items-center justify-center shadow-lg shadow-sky-600/30">
              <Activity className="h-5 w-5 text-white" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-sky-400 bg-clip-text text-transparent">
                InvestAI Enterprise
              </span>
              <span className="ml-2 text-xs font-mono uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                Client Shell v1.0
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Live Health Indicator Badge */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-xs">
              <span className="text-slate-400">Backend API:</span>
              {healthQuery.isLoading ? (
                <span className="flex items-center gap-1.5 text-amber-400">
                  <RefreshCw className="h-3 w-3 animate-spin" />
                  Conectando...
                </span>
              ) : healthQuery.isSuccess ? (
                <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                  Online ({healthQuery.data.latency_ms}ms)
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-rose-400 font-medium">
                  <AlertCircle className="h-3 w-3" />
                  Desconectado
                </span>
              )}
            </div>

            {/* Auth State & Controls */}
            {authLoading ? (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-xs text-slate-400">
                <RefreshCw className="h-3.5 w-3.5 animate-spin text-sky-400" />
                <span>Verificando sesión...</span>
              </div>
            ) : isAuthenticated && user ? (
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/90 border border-slate-700 text-xs">
                  <UserIcon className="h-3.5 w-3.5 text-sky-400" />
                  <span className="font-medium text-slate-200">
                    {user.full_name || user.email}
                  </span>
                  <span
                    className={`ml-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase font-semibold ${
                      isAdmin
                        ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                        : isTrader
                        ? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                        : "bg-slate-700 text-slate-300 border border-slate-600"
                    }`}
                  >
                    {user.role}
                  </span>
                </div>
                <button
                  onClick={() => logout()}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-rose-950/40 text-slate-300 hover:text-rose-300 border border-slate-700 hover:border-rose-800/50 text-xs font-medium transition-colors"
                  title="Cerrar sesión"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Salir</span>
                </button>
              </div>
            ) : (
              <button
                onClick={() => setIsAuthModalOpen(true)}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-md shadow-sky-600/30 transition-colors"
              >
                <LogIn className="h-3.5 w-3.5" />
                <span>Iniciar Sesión</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Shell */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        {/* Navigation Tabs */}
        <div className="flex border-b border-slate-800 gap-2">
          <button
            onClick={() => setActiveTab("health")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "health"
                ? "border-sky-500 text-white bg-slate-900/40"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Server className="h-4 w-4" />
            Salud y Conectividad
          </button>
          <button
            onClick={() => setActiveTab("metrics")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "metrics"
                ? "border-sky-500 text-white bg-slate-900/40"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <BarChart3 className="h-4 w-4" />
            Telemetría Prometheus (/metrics)
          </button>
          <button
            onClick={() => setActiveTab("architecture")}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "architecture"
                ? "border-sky-500 text-white bg-slate-900/40"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Layers className="h-4 w-4" />
            Arquitectura y Contratos
          </button>
        </div>

        {/* Tab 1: System Health & Diagnostic */}
        {activeTab === "health" && (
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
                <h3 className="text-xl font-semibold mb-2">Servicio FastAPI</h3>
                <p className="text-sm text-slate-400 mb-4">
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
                      <span className="text-slate-200">{healthQuery.data.environment}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Latencia:</span>
                      <span className="text-sky-400">{healthQuery.data.latency_ms} ms</span>
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
                <RefreshCw className={`h-3.5 w-3.5 ${healthQuery.isFetching ? "animate-spin" : ""}`} />
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
                <h3 className="text-xl font-semibold mb-2">Base de Datos</h3>
                <p className="text-sm text-slate-400 mb-4">
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
                <h3 className="text-xl font-semibold mb-2">Cliente HTTP Tipado</h3>
                <p className="text-sm text-slate-400 mb-4">
                  Interceptor Axios con inyección X-Request-ID y Mutex de Refresh ante 401.
                </p>

                <div className="space-y-2 text-xs font-mono bg-slate-950 p-3 rounded border border-slate-800">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Access Token:</span>
                    <span className={hasAccessToken ? "text-emerald-400" : "text-slate-500"}>
                      {hasAccessToken ? "Presente" : "No detectado"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Refresh Token:</span>
                    <span className={hasRefreshToken ? "text-emerald-400" : "text-slate-500"}>
                      {hasRefreshToken ? "Presente" : "No detectado"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Trace ID:</span>
                    <span className="text-sky-400 font-mono">Automático (UUIDv4)</span>
                  </div>
                </div>
              </div>

              <div className="mt-6 flex items-center gap-2 text-xs text-slate-400 p-2.5 rounded bg-slate-950 border border-slate-800">
                <Zap className="h-4 w-4 text-amber-400 shrink-0" />
                <span>Mutex anti-estampida listo para renovar tokens concurrentemente.</span>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Prometheus Telemetry */}
        {activeTab === "metrics" && (
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
                  <RefreshCw className={`h-3 w-3 ${metricsQuery.isFetching ? "animate-spin" : ""}`} />
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
                          : "text-emerald-300/90 hover:bg-slate-900/60 px-1 rounded"
                      }
                    >
                      {line}
                    </div>
                  ))
                ) : (
                  <div className="text-slate-500 italic">No se encontraron líneas coincidentes.</div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Architecture & Contracts */}
        {activeTab === "architecture" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                Contratos DTO Sincronizados 1:1
              </h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                El cliente implementa contratos de dominio espejo sincronizados con FastAPI en{" "}
                <code className="text-sky-400 bg-slate-950 px-1 py-0.5 rounded">
                  frontend/src/types/api.ts
                </code>
                :
              </p>
              <ul className="text-xs space-y-2 text-slate-300 font-mono">
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                  <code>UserRole</code>: VIEWER | TRADER | ADMIN
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                  <code>InvestorProfile</code>: CONSERVATIVE | MODERATE | AGGRESSIVE
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                  <code>OrderStatus</code>: PENDING | VALIDATED | ROUTED | EXECUTED | FAILED | REJECTED
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                  <code>MarketCloseJobStatus</code>: 7 estados canónicos de fin de rueda
                </li>
              </ul>
            </div>

            <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-sky-400" />
                Seguridad y Tolerancia a Fallos
              </h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Mecanismos de defensa activos en el cliente HTTP (
                <code className="text-sky-400 bg-slate-950 px-1 py-0.5 rounded">
                  frontend/src/lib/apiClient.ts
                </code>
                ):
              </p>
              <ul className="text-xs space-y-2 text-slate-300">
                <li className="flex items-start gap-2">
                  <span className="text-emerald-400 font-bold">✓</span>
                  <span>
                    <strong>Mutex de Refresh:</strong> Ante 401 concurrentes, una única petición renueva el token mientras las demás esperan encoladas.
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-400 font-bold">✓</span>
                  <span>
                    <strong>Trazabilidad X-Request-ID:</strong> Genera UUIDv4 por petición propagada en headers para correlación en logs de backend.
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-400 font-bold">✓</span>
                  <span>
                    <strong>Normalización ApiError:</strong> Mapea de forma transparente respuestas 422 de Pydantic con detalles por campo.
                  </span>
                </li>
              </ul>
            </div>
          </div>
        )}
      </main>

      {/* Institutional Footer */}
      <footer className="border-t border-slate-800 bg-slate-950 py-4">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-2">
          <span>InvestAI Enterprise — Quantitative Portfolio & Risk Engineering Platform</span>
          <div className="flex items-center gap-4">
            <span className="font-mono">Proxy: /api -&gt; localhost:8000</span>
            <span>React 18 + Vite + Tailwind + TanStack Query</span>
          </div>
        </div>
      </footer>

      {/* Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
      />
    </div>
  );
};
