/**
 * Institutional Sidebar Component for InvestAI Enterprise.
 * Features URL-first navigation via hash, financial branding, and user session status.
 */

import React from "react";
import {
  Activity,
  BarChart3,
  Briefcase,
  LineChart,
  ShieldCheck,
  TrendingUp,
  UploadCloud,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { NavSection } from "@/lib/navigation";

export type { NavSection };

interface SidebarProps {
  activeSection: NavSection;
  onNavigate: (section: NavSection) => void;
}

interface NavItem {
  id: NavSection;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  description: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    id: "portfolios",
    label: "Portafolios",
    icon: Briefcase,
    description: "Gestión de carteras y activos",
  },
  {
    id: "market",
    label: "Mercado en Vivo",
    icon: LineChart,
    badge: "BYMA",
    description: "Cotizaciones en tiempo real",
  },
  {
    id: "ingestion",
    label: "Ingesta de Extractos",
    icon: UploadCloud,
    badge: "CSV / Excel",
    description: "Carga y conciliación de ALyCs",
  },
  {
    id: "health",
    label: "Salud del Sistema",
    icon: Activity,
    description: "Sondas de latencia y backend",
  },
  {
    id: "metrics",
    label: "Telemetría RED",
    icon: BarChart3,
    badge: "Prometheus",
    description: "Métricas cuantitativas y RED",
  },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeSection,
  onNavigate,
}) => {
  const { user, isAuthenticated, isAdmin, isTrader } = useAuth();

  return (
    <aside className="w-64 bg-slate-950 border-r border-slate-800 flex flex-col justify-between shrink-0 select-none">
      {/* Top Branding Section */}
      <div className="flex flex-col">
        <div className="h-16 px-5 border-b border-slate-800/80 flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20 ring-1 ring-white/20">
            <TrendingUp className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-base tracking-tight text-white font-mono">
                InvestAI
              </span>
              <span className="text-[10px] font-semibold uppercase px-1.5 py-0.2 rounded bg-sky-500/20 text-sky-400 border border-sky-500/30">
                PRO
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-sans tracking-wide">
              Enterprise Risk Engine
            </p>
          </div>
        </div>

        {/* Navigation Section */}
        <div className="p-3 space-y-1">
          <div className="px-3 py-2 text-[10px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
            Módulos Principales
          </div>

          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeSection === item.id;

            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-xs font-medium transition-all group ${
                  isActive
                    ? "bg-sky-600/15 text-sky-400 border border-sky-500/30 shadow-sm"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/60 border border-transparent"
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon
                    className={`h-4 w-4 transition-colors ${
                      isActive
                        ? "text-sky-400"
                        : "text-slate-400 group-hover:text-slate-300"
                    }`}
                  />
                  <div className="text-left">
                    <span className="block leading-tight font-medium">
                      {item.label}
                    </span>
                    <span className="block text-[10px] text-slate-400 font-normal">
                      {item.description}
                    </span>
                  </div>
                </div>

                {item.badge && (
                  <span
                    className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${
                      isActive
                        ? "bg-sky-500/20 text-sky-300 border-sky-500/30"
                        : "bg-slate-800 text-slate-400 border-slate-700"
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Institutional Metadata & Footer */}
      <div className="p-3 border-t border-slate-800/80 bg-slate-950/60 flex flex-col gap-3">
        {/* User Identity Chip */}
        {isAuthenticated && user ? (
          <div className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-medium text-slate-200 truncate">
                {user.full_name || user.email}
              </span>
              <span
                className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded font-semibold ${
                  isAdmin
                    ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                    : isTrader
                    ? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                    : "bg-slate-800 text-slate-400 border border-slate-700"
                }`}
              >
                {user.role}
              </span>
            </div>
            <p className="text-[10px] text-slate-400 font-mono truncate">
              {user.email}
            </p>
          </div>
        ) : (
          <div className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/60 text-center">
            <span className="text-[11px] text-slate-400 block font-medium">
              Modo Invitado (Lectura)
            </span>
            <span className="text-[10px] text-slate-400 block">
              Inicia sesión para operar carteras
            </span>
          </div>
        )}

        <div className="flex items-center justify-between text-[10px] text-slate-400 px-1 font-mono">
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
            BYMA / Merval
          </span>
          <span>v1.0.0-p3</span>
        </div>
      </div>
    </aside>
  );
};
