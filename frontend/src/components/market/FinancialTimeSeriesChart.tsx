/**
 * FinancialTimeSeriesChart Component for InvestAI Enterprise.
 * High-performance pure SVG financial charting without external bundle bloat.
 * Features semaphoric area gradients, zero-division immunity, interactive crosshair,
 * adaptive timeframe selectors, ARS ($) / USD (CCL) currency toggle, volume histogram,
 * visual market session markers (official session vs after-hours 5s ticks), and pulsing live dot.
 */

import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { formatMoney, formatSignedPercent } from "@/lib/formatters";
import { CCL_REFERENCE_RATE, type HistoricalBarExtended } from "@/services/marketService";
import type { HistoricalBar, MarketQuote } from "@/types/api";

export type ChartTimeframe = "1D" | "1W" | "1M" | "1Y";
export type ChartCurrencyMode = "ARS" | "USD";

interface FinancialTimeSeriesChartProps {
  bars: (HistoricalBar | HistoricalBarExtended)[];
  activeTicker: string;
  timeframe: ChartTimeframe;
  onTimeframeChange: (tf: ChartTimeframe) => void;
  quote?: MarketQuote;
  cclRate?: number;
}

const TIMEFRAME_LABELS: { id: ChartTimeframe; label: string }[] = [
  { id: "1D", label: "1D" },
  { id: "1W", label: "1S" },
  { id: "1M", label: "1M" },
  { id: "1Y", label: "1A" },
];

function formatSafeDate(ts?: string, isTime = false): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  if (isTime) {
    return d.toLocaleTimeString("es-AR", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
  return d.toLocaleDateString("es-AR", {
    day: "2-digit",
    month: "2-digit",
  });
}

export const FinancialTimeSeriesChart: React.FC<FinancialTimeSeriesChartProps> = ({
  bars,
  activeTicker,
  timeframe,
  onTimeframeChange,
  quote,
  cclRate,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const nativeCurrency: ChartCurrencyMode = quote?.currency === "USD" ? "USD" : "ARS";
  const [displayCurrency, setDisplayCurrency] = useState<ChartCurrencyMode>(nativeCurrency);

  // Fallback-immune CCL exchange rate
  const safeCclRate =
    typeof cclRate === "number" && Number.isFinite(cclRate) && cclRate > 0
      ? cclRate
      : Number(cclRate) > 0
        ? Number(cclRate)
        : CCL_REFERENCE_RATE;

  // Sync default display currency when user selects an instrument with a different native currency
  // biome-ignore lint/correctness/useExhaustiveDependencies: activeTicker is an intentional trigger to reset hover/currency when the instrument changes
  useEffect(() => {
    setDisplayCurrency(nativeCurrency);
    setHoverIndex(null);
  }, [activeTicker, nativeCurrency]);

  // SVG dimensions
  const viewWidth = 800;
  const viewHeight = 360;
  const paddingLeft = 15;
  const paddingRight = 82; // Space for right Y-axis price labels
  const paddingTop = 25;
  const priceChartHeight = 220; // Price area: Y: 25 to 245
  const volumeChartTop = 265;
  const volumeChartHeight = 55; // Volume area: Y: 265 to 320
  const chartWidth = viewWidth - paddingLeft - paddingRight;

  // Currency conversion factor between native quote currency and selected chart currency
  const fxFactor = useMemo(() => {
    if (displayCurrency === nativeCurrency) return 1.0;
    if (nativeCurrency === "ARS" && displayCurrency === "USD") {
      return 1.0 / safeCclRate;
    }
    return safeCclRate;
  }, [displayCurrency, nativeCurrency, safeCclRate]);

  // Sanitize and convert bars with absolute immunity against NaN and zero division
  const convertedBars = useMemo(() => {
    if (!bars || !Array.isArray(bars) || bars.length === 0) return [];
    return bars
      .filter((b) => b && Number.isFinite(Number(b.close)) && Number(b.close) > 0)
      .map((b) => {
        const rawOpen = Number(b.open) * fxFactor;
        const rawHigh = Number(b.high) * fxFactor;
        const rawLow = Number(b.low) * fxFactor;
        const rawClose = Number(b.close) * fxFactor;
        const rawVol = Number(b.volume) || 0;
        const ext = b as HistoricalBarExtended;

        return {
          timestamp: String(b.timestamp || new Date().toISOString()),
          open: Number.isFinite(rawOpen) && rawOpen > 0 ? Number(rawOpen.toFixed(2)) : 0.01,
          high: Number.isFinite(rawHigh) && rawHigh > 0 ? Number(rawHigh.toFixed(2)) : 0.01,
          low: Number.isFinite(rawLow) && rawLow > 0 ? Number(rawLow.toFixed(2)) : 0.01,
          close: Number.isFinite(rawClose) && rawClose > 0 ? Number(rawClose.toFixed(2)) : 0.01,
          volume: Number.isFinite(rawVol) ? Math.max(0, rawVol) : 0,
          is_market_open: typeof ext.is_market_open === "boolean" ? ext.is_market_open : true,
        };
      });
  }, [bars, fxFactor]);

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
    transitionPoint,
  } = useMemo(() => {
    if (!convertedBars || convertedBars.length === 0) {
      return {
        points: [],
        firstPrice: 0,
        lastPrice: 0,
        isPositive: true,
        pathD: "",
        areaD: "",
        yTicks: [],
        maxVolume: 1,
        transitionPoint: null,
      };
    }

    const prices = convertedBars.map((b) => b.close);
    let min = Math.min(...prices);
    let max = Math.max(...prices);

    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      min = 1.0;
      max = 10.0;
    }

    // Defense against flat prices (zero division)
    if (min === max || max - min < 0.0001) {
      const padding = min > 0 ? min * 0.05 : 1.0;
      min = Math.max(0.01, min - padding);
      max += padding;
    } else {
      // Add 4% vertical margin
      const margin = (max - min) * 0.04;
      min = Math.max(0.01, min - margin);
      max += margin;
    }

    const priceRange = Math.max(0.0001, max - min);
    const n = convertedBars.length;
    const stepX = n > 1 ? chartWidth / (n - 1) : chartWidth;

    const computedPoints = convertedBars.map((b, idx) => {
      const x = Number((paddingLeft + idx * stepX).toFixed(1));
      const normalizedPrice = Math.max(0, Math.min(1, (b.close - min) / priceRange));
      const y = Number(
        (paddingTop + priceChartHeight - normalizedPrice * priceChartHeight).toFixed(1),
      );
      return { x, y, bar: b };
    });

    const first = computedPoints[0].bar.close;
    const last = computedPoints[computedPoints.length - 1].bar.close;
    const pos = last >= first;

    // SVG Path assembly
    const path = computedPoints
      .map((p, idx) => (idx === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`))
      .join(" ");

    // Area closed path
    const lastP = computedPoints[computedPoints.length - 1];
    const firstP = computedPoints[0];
    const area = `${path} L ${lastP.x} ${(paddingTop + priceChartHeight).toFixed(1)} L ${firstP.x} ${(paddingTop + priceChartHeight).toFixed(1)} Z`;

    // 4 Y-Axis price tick levels
    const ticks = [0, 0.33, 0.66, 1].map((pct) => {
      const val = min + priceRange * pct;
      const y = paddingTop + priceChartHeight - pct * priceChartHeight;
      return { val, y };
    });

    const maxVol = Math.max(...convertedBars.map((b) => b.volume), 1);

    // Identify session transition point (11:00-17:00 open -> 17:00+ closed / after-hours)
    let transPt: { x: number; y: number; idx: number } | null = null;
    const transIdx = computedPoints.findIndex(
      (p, idx) => idx > 0 && computedPoints[idx - 1].bar.is_market_open && !p.bar.is_market_open,
    );
    if (transIdx !== -1) {
      transPt = {
        x: computedPoints[transIdx].x,
        y: computedPoints[transIdx].y,
        idx: transIdx,
      };
    }

    return {
      points: computedPoints,
      firstPrice: first,
      lastPrice: last,
      isPositive: pos,
      pathD: path,
      areaD: area,
      yTicks: ticks,
      maxVolume: maxVol,
      transitionPoint: transPt,
    };
  }, [convertedBars, chartWidth]);

  // Mouse hover event handler on SVG surface
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || points.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    if (!rect.width) return;
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
  const activeBar = activePoint ? activePoint.bar : convertedBars[convertedBars.length - 1] || null;

  const periodChange = firstPrice > 0 ? (lastPrice - firstPrice) / firstPrice : 0;
  const periodMetrics = formatSignedPercent(periodChange);
  const isIntradiary = timeframe === "1D";

  return (
    <div className="w-full rounded-2xl bg-slate-900 border border-slate-800 p-5 shadow-xl space-y-4">
      {/* Top Header: Active Ticker, Currency Toggle & Period Selectors */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
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
            {displayCurrency !== nativeCurrency && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
                TC CCL Ref: $
                {safeCclRate.toLocaleString("es-AR", {
                  minimumFractionDigits: 1,
                  maximumFractionDigits: 2,
                })}{" "}
                ARS/USD
              </span>
            )}
          </div>

          {activeBar && (
            <div className="flex items-center gap-3 mt-1 font-mono">
              <span className="text-xl font-bold text-slate-100 tabular-nums">
                {formatMoney(activeBar.close, displayCurrency)}
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

          {/* Session Segment Indicators Legend */}
          <div className="flex items-center gap-4 text-[10px] font-mono text-slate-400 pt-1.5 flex-wrap">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
              <span>Rueda Oficial BYMA (11:00 - 17:00 ART)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
              <span>Mercado Cerrado / After-Hours (Tick Continuo 5s)</span>
            </div>
          </div>
        </div>

        {/* Right Controls: Currency Selector (ARS / USD CCL) + Timeframe Tabs */}
        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
          {/* Currency Toggle */}
          <fieldset
            className="flex min-w-0 items-center gap-1 p-1 rounded-xl bg-slate-950 border border-slate-800"
            aria-label="Moneda de visualización del gráfico"
          >
            <button
              type="button"
              onClick={() => setDisplayCurrency("ARS")}
              className={`px-2.5 py-1 rounded-lg text-xs font-mono font-semibold transition-all cursor-pointer ${
                displayCurrency === "ARS"
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              title="Visualizar serie histórica en Pesos Argentinos (ARS)"
            >
              ARS ($)
            </button>
            <button
              type="button"
              onClick={() => setDisplayCurrency("USD")}
              className={`px-2.5 py-1 rounded-lg text-xs font-mono font-semibold transition-all cursor-pointer ${
                displayCurrency === "USD"
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/30 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              title={`Visualizar serie histórica en Dólar CCL ($${safeCclRate.toFixed(1)} ARS/USD)`}
            >
              USD (CCL)
            </button>
          </fieldset>

          {/* Timeframe Tabs */}
          <div className="flex items-center gap-1 p-1 rounded-xl bg-slate-950 border border-slate-800">
            {TIMEFRAME_LABELS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onTimeframeChange(item.id)}
                className={`px-3 py-1 rounded-lg text-xs font-mono font-medium transition-all cursor-pointer ${
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
      </div>

      {/* SVG Canvas Area */}
      {convertedBars.length === 0 ? (
        <div className="h-64 flex flex-col items-center justify-center text-slate-400 text-xs font-mono space-y-2">
          <span>No existen registros de cotizaciones históricas para {activeTicker}.</span>
          <span className="text-slate-500">Seleccione otra especie o verifique el rango.</span>
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
            <title>Price time series chart</title>
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
            {yTicks.map((tick) => (
              <g key={`tick-${tick.val}`}>
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
                  {displayCurrency === "USD"
                    ? `US$${tick.val.toFixed(2)}`
                    : `$${tick.val.toFixed(2)}`}
                </text>
              </g>
            ))}

            {/* Visual Session Transition: Shaded Area & Marker for Closed / After-Hours */}
            {transitionPoint && (
              <g>
                {/* Amber Shaded Zone for After-Hours / Closed Session */}
                <rect
                  x={transitionPoint.x}
                  y={paddingTop}
                  width={Math.max(0, viewWidth - paddingRight - transitionPoint.x)}
                  height={priceChartHeight}
                  fill="rgba(245, 158, 11, 0.08)"
                />
                {/* Dotted Vertical Transition Line at 17:00 */}
                <line
                  x1={transitionPoint.x}
                  y1={paddingTop}
                  x2={transitionPoint.x}
                  y2={paddingTop + priceChartHeight}
                  stroke="#f59e0b"
                  strokeWidth="1.5"
                  strokeDasharray="4 4"
                />
                {/* Curve Node Circle */}
                <circle
                  cx={transitionPoint.x}
                  cy={transitionPoint.y}
                  r="5"
                  fill="#f59e0b"
                  stroke="#0f172a"
                  strokeWidth="2"
                />
                {/* Pill Label */}
                <g
                  transform={`translate(${Math.max(
                    paddingLeft + 110,
                    Math.min(viewWidth - paddingRight - 110, transitionPoint.x),
                  )}, ${paddingTop + 14})`}
                >
                  <rect
                    x="-105"
                    y="-9"
                    width="210"
                    height="18"
                    rx="9"
                    fill="#0f172a"
                    stroke="#f59e0b"
                    strokeWidth="1.2"
                  />
                  <text
                    x="0"
                    y="3"
                    fill="#fbbf24"
                    fontSize="9"
                    fontFamily="monospace"
                    fontWeight="bold"
                    textAnchor="middle"
                  >
                    CIERRE 17:00 → AFTER-HOURS (5s)
                  </text>
                </g>
              </g>
            )}

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
                  key={`vol-${bar.timestamp}`}
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

            {/* Pulsing Live Dot at the latest real-time bar point */}
            {points.length > 0 && (
              <g>
                <circle
                  cx={points[points.length - 1].x}
                  cy={points[points.length - 1].y}
                  r="6"
                  fill={isPositive ? "#10b981" : "#f43f5e"}
                  opacity="0.45"
                  className="animate-ping"
                />
                <circle
                  cx={points[points.length - 1].x}
                  cy={points[points.length - 1].y}
                  r="3.5"
                  fill={isPositive ? "#10b981" : "#f43f5e"}
                  stroke="#ffffff"
                  strokeWidth="1.5"
                />
              </g>
            )}

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
                  {formatSafeDate(convertedBars[0].timestamp, isIntradiary)}
                </text>
                <text
                  x={viewWidth - paddingRight}
                  y={viewHeight - 6}
                  fill="#94a3b8"
                  fontSize="10"
                  fontFamily="monospace"
                  textAnchor="end"
                >
                  {formatSafeDate(convertedBars[convertedBars.length - 1].timestamp, isIntradiary)}
                </text>
              </>
            )}
          </svg>

          {/* Interactive Floating Tooltip */}
          {activePoint && activeBar && (
            <div
              className="absolute pointer-events-none p-2.5 rounded-xl bg-slate-950/95 border border-sky-500/40 shadow-2xl text-xs font-mono z-20 backdrop-blur"
              style={{
                left: `${Math.min(Math.max(activePoint.x - 80, 10), viewWidth - 225)}px`,
                top: `${Math.max(activePoint.y - 88, 10)}px`,
              }}
            >
              <div className="text-[11px] text-slate-400 border-b border-slate-800 pb-1 mb-1">
                {new Date(activeBar.timestamp).toLocaleString("es-AR", {
                  day: "2-digit",
                  month: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                  second: isIntradiary ? "2-digit" : undefined,
                })}
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-slate-400">Cierre:</span>
                <span className="font-bold text-white tabular-nums">
                  {formatMoney(activeBar.close, displayCurrency)}
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
              <div className="flex justify-between gap-4 pt-0.5 border-t border-slate-800/80">
                <span className="text-slate-400">Sesión:</span>
                <span
                  className={`font-semibold tabular-nums ${
                    activeBar.is_market_open ? "text-emerald-400" : "text-amber-400"
                  }`}
                >
                  {activeBar.is_market_open ? "🟢 ABIERTA" : "🟠 AFTER-HOURS"}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
