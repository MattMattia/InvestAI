/**
 * Institutional Top Header Component for InvestAI Enterprise.
 * Features dynamic breadcrumbs, live backend connectivity telemetry,
 * and session state controls.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import {
  AlertCircle,
  ChevronRight,
  LogIn,
  LogOut,
  RefreshCw,
  User as UserIcon,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { navigateToPortfoliosList } from "@/lib/navigation";
import { systemKeys } from "@/lib/queryKeys";
import { NavSection } from "./Sidebar";

interface TopHeaderProps {
  activeSection: NavSection;
  portfolioId?: string | null;
  onOpenAuthModal: () => void;
}

interface HealthResponse {
  status: string;
  database: string;
  latency_ms: number;
  timestamp: string;
  environment: string;
}

export const TopHeader: React.FC<TopHeaderProps> = ({
  activeSection,
  portfolioId,
  onOpenAuthModal,
}) => {
  const { user, isAuthenticated, isLoading: authLoading, logout, isAdmin, isTrader } =
    useAuth();

  // Query Backend Health endpoint every 10 seconds
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

  const sectionTitles: Record<NavSection, { title: string; subtitle: string }> = {
    portfolios: {
      title: "Portafolios de Inversión",
      subtitle: "Posiciones, métricas de asignación y saldos monetarios",
    },
    health: {
      title: "Salud del Sistema y Servicios",
      subtitle: "Diagnóstico de conectividad asíncrona con PostgreSQL y SQLite",
    },
    metrics: {
      title: "Telemetría Prometheus RED",
      subtitle: "Scraping y monitoreo de peticiones, errores y latencia",
    },
    ingestion: {
      title: "Ingesta de Extractos Bursátiles",
      subtitle: "Carga de extractos CSV/Excel de brokers locales y conciliación transaccional",
    },
  };

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-40 px-6 flex items-center justify-between">
      {/* Dynamic Breadcrumbs */}
      <div className="flex items-center gap-2 text-xs">
        <span className="font-mono text-slate-400">InvestAI Enterprise</span>
        <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
        <span
          onClick={() => {
            if (portfolioId) navigateToPortfoliosList();
          }}
          className={`font-medium ${
            portfolioId
              ? "text-slate-400 hover:text-slate-200 cursor-pointer"
              : "text-slate-100"
          }`}
        >
          {sectionTitles[activeSection].title}
        </span>
        {portfolioId && (
          <>
            <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
            <span className="font-medium text-slate-100">
              Detalle y Tenencias
            </span>
          </>
        )}
      </div>

      {/* Right Controls: Health & Auth */}
      <div className="flex items-center gap-3">
        {/* Backend Connectivity Status Pill */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700/80 text-xs">
          <span className="text-slate-400 font-mono text-[11px]">API:</span>
          {healthQuery.isLoading ? (
            <span className="flex items-center gap-1.5 text-amber-400 font-medium">
              <RefreshCw className="h-3 w-3 animate-spin" />
              <span>Verificando...</span>
            </span>
          ) : healthQuery.isSuccess ? (
            <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>Online ({healthQuery.data.latency_ms}ms)</span>
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-rose-400 font-medium">
              <AlertCircle className="h-3 w-3" />
              <span>Desconectado</span>
            </span>
          )}
        </div>

        {/* Auth Session Controls */}
        {authLoading ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 text-xs text-slate-400 border border-slate-700">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-sky-400" />
            <span className="text-[11px]">Cargando sesión...</span>
          </div>
        ) : isAuthenticated && user ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/90 border border-slate-700 text-xs shadow-sm">
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
              title="Cerrar sesión institucional"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Salir</span>
            </button>
          </div>
        ) : (
          <button
            onClick={onOpenAuthModal}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-md shadow-sky-600/30 transition-all hover:shadow-sky-500/50 active:scale-95"
          >
            <LogIn className="h-3.5 w-3.5" />
            <span>Iniciar Sesión</span>
          </button>
        )}
      </div>
    </header>
  );
};

