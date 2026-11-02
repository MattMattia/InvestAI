/**
 * FinancialTimeSeriesChart Component for InvestAI Enterprise.
 * High-performance pure SVG financial charting without external bundle bloat.
 * Features semaphoric area gradients, zero-division immunity, interactive crosshair,
 * adaptive timeframe selectors, and proportional volume histogram.
 */

import React, { useMemo, useRef, useState } from "react";
import { formatMoney, formatSignedPercent } from "@/lib/formatters";
import { HistoricalBar, MarketQuote } from "@/types/api";

export type ChartTimeframe = "1D" | "1W" | "1M" | "1Y";

interface FinancialTimeSeriesChartProps {
  bars: HistoricalBar[];
  activeTicker: string;
  timeframe: ChartTimeframe;
  onTimeframeChange: (tf: ChartTimeframe) => void;
  quote?: MarketQuote;
}

const TIMEFRAME_LABELS: { id: ChartTimeframe; label: string }[] = [
  { id: "1D", label: "1D" },
  { id: "1W", label: "1S" },
  { id: "1M", label: "1M" },
  { id: "1Y", label: "1A" },
];

export const FinancialTimeSeriesChart: React.FC<
  FinancialTimeSeriesChartProps
> = ({
  bars,
  activeTicker,
  timeframe,
  onTimeframeChange,
  quote,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // SVG dimensions
  const viewWidth = 800;
  const viewHeight = 360;
  const paddingLeft = 15;
  const paddingRight = 75; // Space for right Y-axis price labels
  const paddingTop = 25;
  const priceChartHeight = 220; // Price area: Y: 25 to 245
  const volumeChartTop = 265;
  const volumeChartHeight = 55; // Volume area: Y: 265 to 320
  const chartWidth = viewWidth - paddingLeft - paddingRight;

  // Price calculations and strict zero-division protection
  const {
    points,
    firstPrice,
    lastPrice,
    isPositive,
    pathD,
    areaD,
    yTicks,
    maxVolume,
  } = useMemo(() => {
    if (!bars || bars.length === 0) {
      return {
        points: [],
        firstPrice: 0,
        lastPrice: 0,
        isPositive: true,
        pathD: "",
        areaD: "",
        yTicks: [],
        maxVolume: 1,
      };
    }

    const prices = bars.map((b) => b.close);
    let min = Math.min(...prices);
    let max = Math.max(...prices);

    // Defense against flat prices (zero division)
    if (min === max || max - min < 0.0001) {
      const padding = min > 0 ? min * 0.05 : 1.0;
      min -= padding;
      max += padding;
    } else {
      // Add 4% vertical margin
      const margin = (max - min) * 0.04;
      min -= margin;
      max += margin;
    }

    const priceRange = max - min;
    const n = bars.length;
    const stepX = n > 1 ? chartWidth / (n - 1) : chartWidth;

    const computedPoints = bars.map((b, idx) => {
      const x = paddingLeft + idx * stepX;
      const normalizedPrice = (b.close - min) / priceRange;
      const y = paddingTop + priceChartHeight - normalizedPrice * priceChartHeight;
      return { x, y, bar: b };
    });

    const first = bars[0].close;
    const last = bars[bars.length - 1].close;
    const pos = last >= first;

    // SVG Path assembly
    const path = computedPoints
      .map((p, idx) => (idx === 0 ? `M ${p.x.toFixed(1)} ${p.y.toFixed(1)}` : `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`))
      .join(" ");

    // Area closed path
    const area = `${path} L ${computedPoints[computedPoints.length - 1].x.toFixed(
      1
    )} ${(paddingTop + priceChartHeight).toFixed(1)} L ${computedPoints[0].x.toFixed(
      1
    )} ${(paddingTop + priceChartHeight).toFixed(1)} Z`;

    // 4 Y-Axis price tick levels
    const ticks = [0, 0.33, 0.66, 1].map((pct) => {
      const val = min + priceRange * pct;
      const y = paddingTop + priceChartHeight - pct * priceChartHeight;
      return { val, y };
    });

    const maxVol = Math.max(...bars.map((b) => b.volume), 1);

    return {
      points: computedPoints,
      minPrice: min,
      maxPrice: max,
      firstPrice: first,
      lastPrice: last,
      isPositive: pos,
      pathD: path,
      areaD: area,
      yTicks: ticks,
      maxVolume: maxVol,
    };
  }, [bars, chartWidth]);

  // Mouse hover event handler on SVG surface
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || points.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const clientX = e.clientX - rect.left;
    const scaleX = viewWidth / rect.width;
    const svgX = clientX * scaleX;

    // Nearest point search
    let closestIdx = 0;
    let minDistance = Infinity;

    points.forEach((p, idx) => {
      const dist = Math.abs(p.x - svgX);
      if (dist < minDistance) {
        minDistance = dist;
        closestIdx = idx;
      }
    });

    setHoverIndex(closestIdx);
  };

  const handleMouseLeave = () => {
    setHoverIndex(null);
  };

  const activePoint = hoverIndex !== null && points[hoverIndex] ? points[hoverIndex] : null;
  const activeBar = activePoint ? activePoint.bar : bars[bars.length - 1] || null;

  const currency = quote?.currency || "ARS";
  const periodChange = firstPrice > 0 ? ((lastPrice - firstPrice) / firstPrice) : 0;
  const periodMetrics = formatSignedPercent(periodChange);

  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 p-5 shadow-xl space-y-4">
      {/* Top Header: Active Ticker & Period Selectors */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2.5">
            <h3 className="text-lg font-bold text-white font-mono tracking-tight">
              {activeTicker}
            </h3>
            {quote && (
              <span className="text-xs text-slate-400 font-sans truncate max-w-xs sm:max-w-md">
                {quote.name}
              </span>
            )}
            <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
              {quote?.asset_type || "BYMA"}
            </span>
          </div>

          {activeBar && (
            <div className="flex items-center gap-3 mt-1 font-mono">
              <span className="text-xl font-bold text-slate-100 tabular-nums">
                {formatMoney(activeBar.close, currency)}
              </span>
              <span
                className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
                  isPositive
                    ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                    : "bg-rose-500/15 text-rose-400 border-rose-500/30"
                }`}
              >
                {periodMetrics.text} ({timeframe})
              </span>
            </div>
          )}
        </div>

        {/* Timeframe Tabs */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-950 border border-slate-800 self-start sm:self-auto">
          {TIMEFRAME_LABELS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onTimeframeChange(item.id)}
              className={`px-3 py-1 rounded-lg text-xs font-mono font-medium transition-all ${
                timeframe === item.id
                  ? "bg-sky-500/20 text-sky-400 border border-sky-500/30 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {/* SVG Canvas Area */}
      {bars.length === 0 ? (
        <div className="h-64 flex flex-col items-center justify-center text-slate-400 text-xs font-mono space-y-2">
          <span>No existen registros de cotizaciones históricas para {activeTicker}.</span>
          <span className="text-slate-400">Seleccione otra especie o verifique el rango.</span>
        </div>
      ) : (
        <div className="relative w-full overflow-hidden select-none">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${viewWidth} ${viewHeight}`}
            className="w-full h-auto cursor-crosshair"
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          >
            <defs>
              {/* Positive Emerald Gradient */}
              <linearGradient id="chartGradientGreen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
                <stop offset="90%" stopColor="#10b981" stopOpacity="0.0" />
              </linearGradient>

              {/* Negative Rose Gradient */}
              <linearGradient id="chartGradientRed" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.35" />
                <stop offset="90%" stopColor="#f43f5e" stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Horizontal Grid Lines */}
            {yTicks.map((tick, idx) => (
              <g key={idx}>
                <line
                  x1={paddingLeft}
                  y1={tick.y}
                  x2={viewWidth - paddingRight}
                  y2={tick.y}
                  stroke="#334155"
                  strokeWidth="0.8"
                  strokeDasharray="3 3"
                />
                <text
                  x={viewWidth - paddingRight + 8}
                  y={tick.y + 3}
                  fill="#94a3b8"
                  fontSize="10"
                  fontFamily="monospace"
                  textAnchor="start"
                >
                  {tick.val.toFixed(2)}
                </text>
              </g>
            ))}

            {/* Volume Histogram Separator Line */}
            <line
              x1={paddingLeft}
              y1={volumeChartTop - 8}
              x2={viewWidth - paddingRight}
              y2={volumeChartTop - 8}
              stroke="#1e293b"
              strokeWidth="1"
            />
            <text
              x={viewWidth - paddingRight + 8}
              y={volumeChartTop + 10}
              fill="#94a3b8"
              fontSize="9"
              fontFamily="monospace"
            >
              VOL
            </text>

            {/* Volume Histogram Bars */}
            {points.map((p, idx) => {
              const bar = p.bar;
              const barHeight = (bar.volume / maxVolume) * volumeChartHeight;
              const barY = volumeChartTop + volumeChartHeight - barHeight;
              const isBarGreen = bar.close >= bar.open;

              return (
                <rect
                  key={`vol-${idx}`}
                  x={p.x - 2}
                  y={barY}
                  width="4"
                  height={Math.max(1, barHeight)}
                  fill={isBarGreen ? "#10b981" : "#f43f5e"}
                  opacity={hoverIndex === idx ? "0.9" : "0.35"}
                  rx="1"
                />
              );
            })}

            {/* Area Path Fill */}
            <path
              d={areaD}
              fill={isPositive ? "url(#chartGradientGreen)" : "url(#chartGradientRed)"}
            />

            {/* Price Line Stroke */}
            <path
              d={pathD}
              fill="none"
              stroke={isPositive ? "#10b981" : "#f43f5e"}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Crosshair on Hover */}
            {activePoint && (
              <g>
                {/* Vertical Crosshair Line */}
                <line
                  x1={activePoint.x}
                  y1={paddingTop}
                  x2={activePoint.x}
                  y2={volumeChartTop + volumeChartHeight}
                  stroke="#38bdf8"
                  strokeWidth="1"
                  strokeDasharray="2 2"
                />

                {/* Horizontal Crosshair Line */}
                <line
                  x1={paddingLeft}
                  y1={activePoint.y}
                  x2={viewWidth - paddingRight}
                  y2={activePoint.y}
                  stroke="#38bdf8"
                  strokeWidth="1"
                  strokeDasharray="2 2"
                />

                {/* Interactive Anchor Dot */}
                <circle
                  cx={activePoint.x}
                  cy={activePoint.y}
                  r="4.5"
                  fill="#0284c7"
                  stroke="#ffffff"
                  strokeWidth="2"
                />
              </g>
            )}

            {/* Bottom X-Axis Time Labels */}
            {points.length > 0 && (
              <>
                <text
                  x={paddingLeft}
                  y={viewHeight - 6}
                  fill="#94a3b8"
                  fontSize="10"
                  fontFamily="monospace"
                >
                  {new Date(bars[0].timestamp).toLocaleDateString("es-AR", {
                    day: "2-digit",
                    month: "2-digit",
                  })}
                </text>
                <text
                  x={viewWidth - paddingRight}
                  y={viewHeight - 6}
                  fill="#94a3b8"
                  fontSize="10"
                  fontFamily="monospace"
                  textAnchor="end"
                >
                  {new Date(bars[bars.length - 1].timestamp).toLocaleDateString(
                    "es-AR",
                    {
                      day: "2-digit",
                      month: "2-digit",
                    }
                  )}
                </text>
              </>
            )}
          </svg>

          {/* Interactive Floating Tooltip */}
          {activePoint && activeBar && (
            <div
              className="absolute pointer-events-none p-2.5 rounded-xl bg-slate-950/95 border border-sky-500/40 shadow-2xl text-xs font-mono z-20 backdrop-blur"
              style={{
                left: `${Math.min(
                  Math.max(activePoint.x - 80, 10),
                  viewWidth - 190
                )}px`,
                top: `${Math.max(activePoint.y - 75, 10)}px`,
              }}
            >
              <div className="text-[11px] text-slate-400 border-b border-slate-800 pb-1 mb-1">
                {new Date(activeBar.timestamp).toLocaleString("es-AR", {
                  day: "2-digit",
                  month: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-400">Cierre:</span>
                <span className="font-bold text-white tabular-nums">
                  {formatMoney(activeBar.close, currency)}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-400">Máx / Mín:</span>
                <span className="text-slate-300 tabular-nums">
                  {activeBar.high.toFixed(2)} / {activeBar.low.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-400">Volumen:</span>
                <span className="text-sky-400 tabular-nums">
                  {activeBar.volume.toLocaleString()}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
