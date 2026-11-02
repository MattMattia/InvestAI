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
import { marketService } from "@/services/marketService";
import { ChartTimeframe, FinancialTimeSeriesChart } from "./FinancialTimeSeriesChart";
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
    refetchInterval: isMarketOpen ? 15_000 : 60_000,
    refetchIntervalInBackground: false,
  });

  // 3. Query historical series for the active ticker and timeframe
  const historyQuery = useQuery({
    queryKey: marketKeys.history(activeTicker, timeframe),
    queryFn: () => marketService.getHistoricalBars(activeTicker, timeframe),
    staleTime: 30_000,
  });

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
    return (quotesQuery.data || []).find((q) => q.ticker === activeTicker);
  }, [quotesQuery.data, activeTicker]);

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
        bars={historyQuery.data || []}
        activeTicker={activeTicker}
        timeframe={timeframe}
        onTimeframeChange={(tf) => setTimeframe(tf)}
        quote={activeQuote}
      />

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
        isLoading={quotesQuery.isLoading}
      />
    </div>
  );
};
