/**
 * Pure SVG Accessible Donut Chart for Portfolio Asset Allocation.
 * Features institutional bimonetary toggle (ARS vs USD), integrated cash representation,
 * responsive synchronized hover, and strict zero/100% boundary handling.
 */

import React, { useMemo, useState } from "react";
import { Coins, DollarSign, PieChart as PieChartIcon } from "lucide-react";
import { formatMoney, parseDecimalSafe } from "@/lib/formatters";
import { Holding, Portfolio } from "@/types/api";

interface AssetAllocationDonutProps {
  portfolio: Portfolio;
  initialCurrency?: "ARS" | "USD";
}

interface AllocationSector {
  id: string;
  label: string;
  ticker: string;
  value: number;
  fraction: number;
  percentage: number;
  color: string;
  isCash: boolean;
}

const PALETTE = [
  "#38bdf8", // Sky
  "#10b981", // Emerald
  "#6366f1", // Indigo
  "#f59e0b", // Amber
  "#06b6d4", // Cyan
  "#8b5cf6", // Violet
  "#f43f5e", // Rose
  "#ec4899", // Pink
  "#14b8a6", // Teal
  "#64748b", // Slate
];

const RADIUS = 80;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS; // ~502.6548

export const AssetAllocationDonut: React.FC<AssetAllocationDonutProps> = ({
  portfolio,
  initialCurrency = "ARS",
}) => {
  const [selectedCurrency, setSelectedCurrency] = useState<"ARS" | "USD">(
    initialCurrency
  );
  const [hoveredSectorId, setHoveredSectorId] = useState<string | null>(null);

  // Compute sectors for the selected currency
  const { sectors, totalValue } = useMemo(() => {
    const isArs = selectedCurrency === "ARS";
    const cashValue = isArs
      ? parseDecimalSafe(portfolio.cash_balance_ars)
      : parseDecimalSafe(portfolio.cash_balance_usd);

    const holdings: Holding[] = portfolio.holdings || [];

    // Filter holdings belonging to the selected currency
    const relevantHoldings = holdings
      .map((h) => {
        const qty = parseDecimalSafe(h.quantity);
        const price = parseDecimalSafe(h.current_price);
        const marketVal = qty * price;
        const cur = h.asset?.currency?.toUpperCase() === "USD" ? "USD" : "ARS";
        return {
          ticker: h.asset_ticker,
          marketVal,
          currency: cur,
        };
      })
      .filter((h) => h.currency === selectedCurrency && h.marketVal > 0);

    const rawTotal =
      cashValue +
      relevantHoldings.reduce((acc, h) => acc + h.marketVal, 0);

    if (rawTotal <= 0) {
      return { sectors: [], totalValue: 0 };
    }

    const sectorItems: AllocationSector[] = [];
    let colorIndex = 0;

    // 1. Add Cash sector if > 0
    if (cashValue > 0) {
      const frac = cashValue / rawTotal;
      if (frac * 100 > 0.01) {
        sectorItems.push({
          id: `cash-${selectedCurrency}`,
          label: `Caja ${selectedCurrency}`,
          ticker: `EFECTIVO`,
          value: cashValue,
          fraction: frac,
          percentage: frac * 100,
          color: isArs ? "#10b981" : "#38bdf8",
          isCash: true,
        });
        colorIndex++;
      }
    }

    // 2. Add Holdings sectors
    relevantHoldings.forEach((h) => {
      const frac = h.marketVal / rawTotal;
      if (frac * 100 > 0.01) {
        sectorItems.push({
          id: `holding-${h.ticker}`,
          label: h.ticker,
          ticker: h.ticker,
          value: h.marketVal,
          fraction: frac,
          percentage: frac * 100,
          color: PALETTE[colorIndex % PALETTE.length],
          isCash: false,
        });
        colorIndex++;
      }
    });

    return { sectors: sectorItems, totalValue: rawTotal };
  }, [portfolio, selectedCurrency]);

  const hoveredSector = useMemo(() => {
    if (!hoveredSectorId) return null;
    return sectors.find((s) => s.id === hoveredSectorId) || null;
  }, [sectors, hoveredSectorId]);

  return (
    <div className="rounded-xl bg-slate-900 border border-slate-800 p-5 shadow-lg flex flex-col justify-between space-y-5">
      {/* Header with Currency Switcher */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <PieChartIcon className="h-4 w-4 text-sky-400" />
          <h3 className="font-semibold text-sm text-slate-100">
            Asignación por Activo
          </h3>
        </div>

        {/* Currency Toggle */}
        <div className="flex items-center p-0.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
          <button
            onClick={() => {
              setSelectedCurrency("ARS");
              setHoveredSectorId(null);
            }}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-md transition-all ${
              selectedCurrency === "ARS"
                ? "bg-emerald-600/20 text-emerald-300 font-semibold border border-emerald-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Coins className="h-3 w-3" />
            <span>ARS</span>
          </button>
          <button
            onClick={() => {
              setSelectedCurrency("USD");
              setHoveredSectorId(null);
            }}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-md transition-all ${
              selectedCurrency === "USD"
                ? "bg-sky-600/20 text-sky-300 font-semibold border border-sky-500/30 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <DollarSign className="h-3 w-3" />
            <span>USD</span>
          </button>
        </div>
      </div>

      {/* SVG Donut Centerpiece */}
      <div className="flex flex-col md:flex-row items-center justify-center gap-6">
        <div className="relative w-48 h-48 shrink-0 flex items-center justify-center select-none">
          <svg
            viewBox="0 0 200 200"
            className="w-full h-full transform -rotate-90"
          >
            {/* Background track circle */}
            <circle
              cx="100"
              cy="100"
              r={RADIUS}
              fill="transparent"
              stroke="#1e293b"
              strokeWidth="24"
            />

            {/* Render Sectors */}
            {totalValue > 0 && sectors.length > 0 ? (
              (() => {
                let accumulatedFraction = 0;
                return sectors.map((sector) => {
                  const isHovered = hoveredSectorId === sector.id;
                  const dash = (sector.fraction * CIRCUMFERENCE).toFixed(2);
                  const offset = (
                    -accumulatedFraction * CIRCUMFERENCE
                  ).toFixed(2);
                  accumulatedFraction += sector.fraction;

                  return (
                    <circle
                      key={sector.id}
                      cx="100"
                      cy="100"
                      r={RADIUS}
                      fill="transparent"
                      stroke={sector.color}
                      strokeWidth={isHovered ? 28 : 24}
                      strokeDasharray={`${dash} ${CIRCUMFERENCE.toFixed(2)}`}
                      strokeDashoffset={offset}
                      className="transition-all duration-200 cursor-pointer"
                      onMouseEnter={() => setHoveredSectorId(sector.id)}
                      onMouseLeave={() => setHoveredSectorId(null)}
                    />
                  );
                });
              })()
            ) : (
              <circle
                cx="100"
                cy="100"
                r={RADIUS}
                fill="transparent"
                stroke="#334155"
                strokeWidth="24"
                strokeDasharray="4 4"
              />
            )}
          </svg>

          {/* Central Hover Overlay */}
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-4 pointer-events-none">
            {hoveredSector ? (
              <>
                <span
                  className="text-[10px] font-mono uppercase tracking-wider font-semibold truncate max-w-[120px]"
                  style={{ color: hoveredSector.color }}
                >
                  {hoveredSector.label}
                </span>
                <span className="text-base font-bold font-mono text-white mt-0.5">
                  {hoveredSector.percentage.toFixed(1)}%
                </span>
                <span className="text-[10px] text-slate-400 font-mono mt-0.5 truncate max-w-[120px]">
                  {formatMoney(hoveredSector.value, selectedCurrency)}
                </span>
              </>
            ) : totalValue > 0 ? (
              <>
                <span className="text-[10px] uppercase font-mono tracking-wider text-slate-400">
                  Total {selectedCurrency}
                </span>
                <span className="text-sm font-bold font-mono text-slate-100 mt-0.5">
                  {formatMoney(totalValue, selectedCurrency)}
                </span>
                <span className="text-[10px] text-slate-400 font-mono mt-0.5">
                  {sectors.length} {sectors.length === 1 ? "sector" : "sectores"}
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-400 font-mono">
                Sin Posiciones
              </span>
            )}
          </div>
        </div>

        {/* Interactive Legend */}
        <div className="flex-1 w-full max-h-48 overflow-y-auto space-y-1.5 pr-1">
          {sectors.length > 0 ? (
            sectors.map((sector) => {
              const isHovered = hoveredSectorId === sector.id;

              return (
                <div
                  key={sector.id}
                  onMouseEnter={() => setHoveredSectorId(sector.id)}
                  onMouseLeave={() => setHoveredSectorId(null)}
                  className={`flex items-center justify-between p-2 rounded-lg text-xs font-mono transition-all cursor-pointer ${
                    isHovered
                      ? "bg-slate-800/90 border border-slate-700 shadow-sm"
                      : "hover:bg-slate-800/40 border border-transparent text-slate-300"
                  }`}
                >
                  <div className="flex items-center gap-2 truncate">
                    <span
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: sector.color }}
                    />
                    <span
                      className={`truncate font-medium ${
                        isHovered ? "text-white" : "text-slate-300"
                      }`}
                    >
                      {sector.label}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 shrink-0 ml-2">
                    <span className="text-slate-400 text-[11px]">
                      {formatMoney(sector.value, selectedCurrency)}
                    </span>
                    <span className="font-semibold text-slate-200 text-right w-12">
                      {sector.percentage.toFixed(1)}%
                    </span>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="text-center py-6 text-xs text-slate-400 font-mono">
              No hay tenencias ni saldo en {selectedCurrency} para este portafolio.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

