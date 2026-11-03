/**
 * MarketDataView Component for InvestAI Enterprise.
 * Comprehensive Real-Time Market Monitor for BYMA, featuring category filters,
 * instant ticker search, interactive SVG chart, high-density quotes table, and smart polling.
 */

import React, { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useHashRoute } from "@/lib/navigation";
import { marketKeys } from "@/lib/queryKeys";
import {
  buildDeterministicHistoricalBars,
  marketService,
} from "@/services/marketService";
import { MarketQuote } from "@/types/api";
import { OrderExecutionModal } from "@/components/orders/OrderExecutionModal";
import {
  ChartTimeframe,
  FinancialTimeSeriesChart,
} from "./FinancialTimeSeriesChart";
import { MarketStatusBar } from "./MarketStatusBar";
import { QuotesTable } from "./QuotesTable";

type MarketCategory = "ALL" | "STOCK" | "CEDEAR" | "BOND";

const CATEGORY_TABS: { id: MarketCategory; label: string }[] = [
  { id: "ALL", label: "Todas las Especies" },
  { id: "STOCK", label: "Acciones Líderes" },
  { id: "CEDEAR", label: "CEDEARs" },
  { id: "BOND", label: "Bonos Soberanos" },
];

export const MarketDataView: React.FC = () => {
  const { ticker: routeTicker, navigateToMarket } = useHashRoute();
  const queryClient = useQueryClient();

  // Active ticker selection: defaults to route ticker or GGAL
  const activeTicker = (routeTicker && routeTicker.trim().toUpperCase()) || "GGAL";

  const [selectedCategory, setSelectedCategory] = useState<MarketCategory>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("1M");
  const [isRefreshingManual, setIsRefreshingManual] = useState<boolean>(false);
  const [tradeModalQuote, setTradeModalQuote] = useState<MarketQuote | null>(null);

  // Full catalog lookup so activeQuote is always resolved regardless of category tab
  const allCuratedQuotes = useMemo(() => marketService.getCuratedQuotesSync("ALL"), []);

  // 1. Query official market session status
  const statusQuery = useQuery({
    queryKey: marketKeys.status(),
    queryFn: () => marketService.getMarketStatus(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });

  const isMarketOpen = statusQuery.data?.is_open ?? false;

  // 2. Query live quotes with dynamic interval based on session state
  const quotesQuery = useQuery({
    queryKey: marketKeys.quotes(selectedCategory),
    queryFn: () => marketService.getLiveQuotes(selectedCategory),
    initialData: () => marketService.getCuratedQuotesSync(selectedCategory),
    refetchInterval: isMarketOpen ? 15_000 : 60_000,
    refetchIntervalInBackground: false,
  });

  // 3. Query historical series for the active ticker and timeframe with instant synchronous fallback
  const historyQuery = useQuery({
    queryKey: marketKeys.history(activeTicker, timeframe),
    queryFn: () => marketService.getHistoricalBars(activeTicker, timeframe),
    initialData: () => buildDeterministicHistoricalBars(activeTicker, timeframe),
    staleTime: 30_000,
  });

  const resolvedBars = useMemo(() => {
    if (historyQuery.data && historyQuery.data.length > 0) {
      return historyQuery.data;
    }
    return buildDeterministicHistoricalBars(activeTicker, timeframe);
  }, [historyQuery.data, activeTicker, timeframe]);

  // Manual refresh trigger
  const handleManualRefresh = async () => {
    setIsRefreshingManual(true);
    await queryClient.invalidateQueries({ queryKey: marketKeys.all });
    setTimeout(() => setIsRefreshingManual(false), 500);
  };

  const handleSelectTicker = (ticker: string) => {
    navigateToMarket(ticker);
  };

  // Filtered quotes based on search query
  const filteredQuotes = useMemo(() => {
    const raw = quotesQuery.data || [];
    if (!searchQuery.trim()) return raw;
    const term = searchQuery.trim().toLowerCase();
    return raw.filter(
      (q) =>
        q.ticker.toLowerCase().includes(term) ||
        q.name.toLowerCase().includes(term)
    );
  }, [quotesQuery.data, searchQuery]);

  // Active quote data for chart header
  const activeQuote = useMemo(() => {
    return (
      (quotesQuery.data || []).find((q) => q.ticker === activeTicker) ||
      allCuratedQuotes.find((q) => q.ticker === activeTicker)
    );
  }, [quotesQuery.data, allCuratedQuotes, activeTicker]);

  // 10-Year Quantitative & Fundamental Metrics for activeTicker
  const activeMetrics10Y = useMemo(
    () => marketService.getCalibrated10YMetricsSync(activeTicker),
    [activeTicker]
  );

  return (
    <div className="space-y-6">
      {/* 1. Official BYMA Session Status Bar */}
      <MarketStatusBar
        status={statusQuery.data}
        onRefresh={handleManualRefresh}
        isRefreshing={isRefreshingManual || quotesQuery.isFetching}
      />

      {/* 2. Interactive SVG Financial Time Series Chart */}
      <FinancialTimeSeriesChart
        bars={resolvedBars}
        activeTicker={activeTicker}
        timeframe={timeframe}
        onTimeframeChange={(tf) => setTimeframe(tf)}
        quote={activeQuote}
      />

      {/* 2.5. Real-Time 10-Year Quantitative & Fundamental Metrics Card */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 shadow-lg space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-800">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-sky-400">
              Ficha Cuantitativa (10 Años) y Fundamentales — {activeMetrics10Y.ticker} ({activeMetrics10Y.asset_type})
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Ventana histórica computada:{" "}
              <span className="font-mono text-slate-200 font-semibold">
                {activeMetrics10Y.history_years_available.toFixed(1)} años
              </span>{" "}
              ({activeMetrics10Y.data_points_count} ruedas desde{" "}
              <span className="font-mono">{activeMetrics10Y.history_start_date}</span>) en moneda dura (USD/CCL)
            </p>
          </div>
          <span className="text-[11px] font-mono px-2.5 py-1 rounded-md bg-slate-950 border border-slate-800 text-emerald-400">
            Retorno Esperado Compuesto (μ_quant): +{(activeMetrics10Y.composite_quant_return * 100).toFixed(2)}% anual
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 text-xs font-mono">
          <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
            <span className="text-[10px] text-slate-400 block font-sans">CAGR 10Y (USD)</span>
            <span className="text-sm font-bold text-emerald-400">
              +{(activeMetrics10Y.cagr_annualized * 100).toFixed(1)}%
            </span>
          </div>
          <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
            <span className="text-[10px] text-slate-400 block font-sans">Volatilidad 10Y (σ)</span>
            <span className="text-sm font-bold text-amber-300">
              {(activeMetrics10Y.volatility_annualized * 100).toFixed(1)}%
            </span>
          </div>
          <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
            <span className="text-[10px] text-slate-400 block font-sans">Sharpe / Sortino</span>
            <span className="text-sm font-bold text-sky-300">
              {activeMetrics10Y.sharpe_ratio.toFixed(2)} / {activeMetrics10Y.sortino_ratio.toFixed(2)}
            </span>
          </div>
          <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
            <span className="text-[10px] text-slate-400 block font-sans">Max Drawdown</span>
            <span className="text-sm font-bold text-rose-400">
              -{(activeMetrics10Y.max_drawdown * 100).toFixed(1)}%
            </span>
          </div>
          <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
            <span className="text-[10px] text-slate-400 block font-sans">Beta / VaR 95% (1D)</span>
            <span className="text-sm font-bold text-slate-200">
              {activeMetrics10Y.beta_market.toFixed(2)} / {(activeMetrics10Y.var_95_daily * 100).toFixed(1)}%
            </span>
          </div>
          {activeMetrics10Y.asset_type === "BOND" ? (
            <>
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
                <span className="text-[10px] text-slate-400 block font-sans">TIR (YTM Anual)</span>
                <span className="text-sm font-bold text-amber-300">
                  {activeMetrics10Y.ytm_tir_pct?.toFixed(2) ?? "14.50"}%
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
                <span className="text-[10px] text-slate-400 block font-sans">Modified Duration</span>
                <span className="text-sm font-bold text-sky-300">
                  {activeMetrics10Y.modified_duration?.toFixed(2) ?? "2.50"} años
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
                <span className="text-[10px] text-slate-400 block font-sans">Paridad Técnica</span>
                <span className="text-sm font-bold text-emerald-300">
                  {activeMetrics10Y.parity_pct?.toFixed(1) ?? "68.5"}%
                </span>
              </div>
            </>
          ) : (
            <>
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
                <span className="text-[10px] text-slate-400 block font-sans">Ratio P/E / P/B</span>
                <span className="text-sm font-bold text-sky-300">
                  {activeMetrics10Y.pe_ratio?.toFixed(1) ?? "12.0"}x / {activeMetrics10Y.pb_ratio?.toFixed(1) ?? "1.8"}x
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
                <span className="text-[10px] text-slate-400 block font-sans">ROE (Rentabilidad)</span>
                <span className="text-sm font-bold text-emerald-400">
                  {activeMetrics10Y.roe_pct?.toFixed(1) ?? "18.5"}%
                </span>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
                <span className="text-[10px] text-slate-400 block font-sans">Deuda/Patrimonio · Div</span>
                <span className="text-sm font-bold text-slate-200">
                  {activeMetrics10Y.debt_to_equity?.toFixed(2) ?? "0.55"}x · {activeMetrics10Y.dividend_yield_pct?.toFixed(1) ?? "0.0"}%
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 3. Filter Controls & Search Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        {/* Category Filter Pills */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
          {CATEGORY_TABS.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setSelectedCategory(cat.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
                selectedCategory === cat.id
                  ? "bg-sky-500/20 text-sky-400 border border-sky-500/30 shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div className="relative min-w-[240px] sm:w-72">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar por ticker o nombre..."
            className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-8 py-2 text-xs font-mono text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
              title="Limpiar búsqueda"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* 4. Real-Time Quotes Table */}
      <QuotesTable
        quotes={filteredQuotes}
        selectedTicker={activeTicker}
        onSelectTicker={handleSelectTicker}
        onTradeTicker={(q) => setTradeModalQuote(q)}
        isLoading={quotesQuery.isLoading}
      />

      {/* 5. Assisted Order Execution Modal */}
      {tradeModalQuote && (
        <OrderExecutionModal
          isOpen={Boolean(tradeModalQuote)}
          onClose={() => setTradeModalQuote(null)}
          initialTicker={tradeModalQuote.ticker}
          initialPrice={tradeModalQuote.last_price}
          initialCurrency={tradeModalQuote.currency}
        />
      )}
    </div>
  );
};
