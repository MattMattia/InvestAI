/**
 * MarketStatusBar Component for InvestAI Enterprise.
 * Displays official BYMA market session status (open/closed semaphores),
 * live Argentina Time (ART / UTC-3), next event countdown, and manual quote refresh trigger.
 */

import React, { useEffect, useState } from "react";
import { Clock, RefreshCw } from "lucide-react";
import { MarketStatusInfo } from "@/types/api";

interface MarketStatusBarProps {
  status: MarketStatusInfo | null | undefined;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export const MarketStatusBar: React.FC<MarketStatusBarProps> = ({
  status,
  onRefresh,
  isRefreshing = false,
}) => {
  const [artTime, setArtTime] = useState<string>("");

  // Live seconds ticker in America/Argentina/Buenos_Aires (ART)
  useEffect(() => {
    const updateTime = () => {
      const formatter = new Intl.DateTimeFormat("es-AR", {
        timeZone: "America/Argentina/Buenos_Aires",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
      setArtTime(`${formatter.format(new Date())} ART`);
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const isOpen = status?.is_open ?? false;

  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 p-4 shadow-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
      {/* Left: Semaphoric Status & Info */}
      <div className="flex items-center gap-3.5 flex-wrap">
        <div
          className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-mono font-bold uppercase tracking-wider shadow-sm transition-all ${
            isOpen
              ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30 shadow-emerald-500/10"
              : "bg-amber-500/15 text-amber-300 border-amber-500/30 shadow-amber-500/10"
          }`}
        >
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              isOpen ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
            }`}
          />
          <span>{isOpen ? "MERCADO ABIERTO" : "MERCADO CERRADO"}</span>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-300 font-sans">
          <span className="font-semibold text-white">
            BYMA (Bolsas y Mercados Argentinos)
          </span>
          <span className="text-slate-400">•</span>
          <span className="text-slate-400 font-mono text-[11px]">
            {status?.next_change || "Horario regular: 11:00 a 17:00 ART"}
          </span>
        </div>
      </div>

      {/* Right: Live ART Clock & Refresh Button */}
      <div className="flex items-center gap-3 w-full md:w-auto justify-between md:justify-end">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800/80 font-mono text-xs text-sky-400">
          <Clock className="h-3.5 w-3.5 text-slate-400" />
          <span>{artTime || "Cargando hora ART..."}</span>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 hover:border-slate-600 text-xs font-medium transition-all flex items-center gap-1.5 shadow-sm active:scale-95 disabled:opacity-50"
          title="Actualizar cotizaciones en vivo"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 text-sky-400 ${
              isRefreshing ? "animate-spin" : ""
            }`}
          />
          <span className="hidden sm:inline">Actualizar</span>
        </button>
      </div>
    </div>
  );
};

