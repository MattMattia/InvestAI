/**
 * MarketStatusBar Component for InvestAI Enterprise.
 * Displays official BYMA market session status (open/closed semaphores), the active
 * official trading window, live Argentina Time (ART / UTC-3) and the manual quote
 * refresh trigger with auto-sync feedback.
 */

import { Clock, RefreshCw } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import type { MarketStatusInfo } from "@/types/api";

interface MarketStatusBarProps {
  status: MarketStatusInfo | null | undefined;
  onRefresh: () => void;
  isRefreshing?: boolean;
  dataSource?: string;
  cclRate?: number;
  mepRate?: number;
  marketOpenTime?: string;
  marketCloseTime?: string;
}

export const MarketStatusBar: React.FC<MarketStatusBarProps> = ({
  status,
  onRefresh,
  isRefreshing = false,
  dataSource = "YAHOO_LIVE",
  cclRate = 1668.0,
  mepRate = 1581.0,
  marketOpenTime = "10:30",
  marketCloseTime = "18:00",
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
  const isLive =
    dataSource === "YAHOO_LIVE" ||
    dataSource === "GOOGLE_BCBA_LIVE" ||
    dataSource === "YAHOO_BCBA_LIVE_5S";
  const safeCcl = Number(cclRate) > 0 ? Number(cclRate) : 1668.8;
  const safeMep = Number(mepRate) > 0 ? Number(mepRate) : 1581.1;

  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 p-4 shadow-xl flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
      {/* Left: Semaphoric Status, BYMA info & Live Feed Badge */}
      <div className="flex items-center gap-3 flex-wrap">
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
          <span>
            {isOpen ? "MERCADO ABIERTO" : "MERCADO CERRADO (MODO CONTINUO / AFTER-HOURS ACTIVO)"}
          </span>
        </div>

        {/* Official trading window currently in force */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950 border border-sky-500/30 font-mono text-xs text-sky-300 shadow-sm">
          <span className="font-semibold tracking-wide tabular-nums">
            🕒 RUEDA BYMA: {marketOpenTime} – {marketCloseTime} ART
          </span>
        </div>

        {/* Live Multi-source Feed Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950 border border-emerald-500/30 font-mono text-xs text-emerald-400 shadow-sm">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
          <span className="font-semibold tracking-wide">
            {isLive
              ? "⚡ LIVE FEED (AUTO-SYNC 5s): YAHOO .BA / GOOGLE BCBA"
              : "⚡ FEED CALIBRADO (FALLBACK 5s)"}
          </span>
        </div>

        {/* Real-time FX Rates (CCL & MEP) */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800 font-mono text-xs text-slate-300">
          <span className="text-slate-400">CCL:</span>
          <span className="font-bold text-sky-400">
            $
            {safeCcl.toLocaleString("es-AR", {
              minimumFractionDigits: 1,
              maximumFractionDigits: 1,
            })}
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-400">MEP:</span>
          <span className="font-bold text-emerald-400">
            $
            {safeMep.toLocaleString("es-AR", {
              minimumFractionDigits: 1,
              maximumFractionDigits: 1,
            })}
          </span>
        </div>
      </div>

      {/* Right: Live ART Clock & Refresh Button */}
      <div className="flex items-center gap-3 w-full lg:w-auto justify-between lg:justify-end">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800/80 font-mono text-xs text-sky-400 tabular-nums">
          <Clock className="h-3.5 w-3.5 text-slate-400" />
          <span>{artTime || "Cargando hora ART..."}</span>
        </div>

        <div className="flex flex-col items-end gap-1">
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-busy={isRefreshing}
            className="min-w-[176px] px-4 py-2 rounded-xl bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 border border-sky-400/30 text-white font-semibold text-xs transition-all flex items-center justify-center gap-2 shadow-lg shadow-sky-600/25 active:scale-95 disabled:opacity-80 disabled:cursor-progress cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
            title="Actualizar cotizaciones en vivo y sincronizar portafolios (MTM)"
          >
            <RefreshCw className={`h-3.5 w-3.5 text-white ${isRefreshing ? "animate-spin" : ""}`} />
            <span>{isRefreshing ? "Sincronizando MTM..." : "Actualizar"}</span>
          </button>
          <span className="flex items-center gap-1.5 text-[10px] font-mono text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span>Auto-sync cada 5s</span>
          </span>
        </div>
      </div>
    </div>
  );
};
