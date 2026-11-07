/**
 * MarketDataView Component for InvestAI Enterprise.
 * Comprehensive Real-Time Market Monitor for BYMA, featuring category filters,
 * instant ticker search, interactive SVG chart, high-density quotes table,
 * 5-second polling auto-sync, resilient error boundary, and 10Y quantitative analytics.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import React, { useMemo, useState } from "react";
import { OrderExecutionModal } from "@/components/orders/OrderExecutionModal";
import { useHashRoute } from "@/lib/navigation";
import { marketKeys, portfolioKeys } from "@/lib/queryKeys";
import {
	buildDeterministicHistoricalBars,
	marketService,
} from "@/services/marketService";
import type { MarketQuote } from "@/types/api";
import {
	type ChartTimeframe,
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

function formatQuantPct(val: number | null | undefined): string {
	if (val === null || val === undefined || !Number.isFinite(Number(val))) {
		return "0.0%";
	}
	const abs = Math.abs(Number(val));
	if (abs > 1.0) {
		return `${abs.toFixed(1)}%`;
	}
	return `${(abs * 100).toFixed(1)}%`;
}

interface ChartErrorBoundaryProps {
	children: React.ReactNode;
}

interface ChartErrorBoundaryState {
	hasError: boolean;
}

class ChartErrorBoundary extends React.Component<
	ChartErrorBoundaryProps,
	ChartErrorBoundaryState
> {
	constructor(props: ChartErrorBoundaryProps) {
		super(props);
		this.state = { hasError: false };
	}

	static getDerivedStateFromError(): ChartErrorBoundaryState {
		return { hasError: true };
	}

	componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
		console.error("ChartErrorBoundary caught render error:", error, errorInfo);
	}

	render() {
		if (this.state.hasError) {
			return (
				<div className="w-full rounded-2xl bg-slate-900 border border-slate-800 p-8 shadow-xl flex flex-col items-center justify-center text-center space-y-3">
					<span className="text-amber-400 font-mono text-xs font-semibold">
						⚠️ Ocurrió una inconsistencia transitoria al renderizar el gráfico.
					</span>
					<p className="text-slate-400 text-xs max-w-md">
						Las cotizaciones en vivo y la ejecución de órdenes continúan
						operando con normalidad.
					</p>
					<button
						type="button"
						onClick={() => this.setState({ hasError: false })}
						className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-400 text-xs font-mono transition-colors cursor-pointer border border-slate-700"
					>
						Reintentar visualización
					</button>
				</div>
			);
		}
		return this.props.children;
	}
}

export const MarketDataView: React.FC = () => {
	const { ticker: routeTicker, navigateToMarket } = useHashRoute();
	const queryClient = useQueryClient();

	// Active ticker selection: defaults to route ticker or GGAL
	const activeTicker =
		(routeTicker && routeTicker.trim().toUpperCase()) || "GGAL";

	const [selectedCategory, setSelectedCategory] =
		useState<MarketCategory>("ALL");
	const [searchQuery, setSearchQuery] = useState<string>("");
	const [timeframe, setTimeframe] = useState<ChartTimeframe>("1M");
	const [isRefreshingManual, setIsRefreshingManual] = useState<boolean>(false);
	const [tradeModalQuote, setTradeModalQuote] = useState<MarketQuote | null>(
		null,
	);

	// Full catalog lookup so activeQuote is always resolved regardless of category tab
	const allCuratedQuotes = useMemo(
		() => marketService.getCuratedQuotesSync("ALL"),
		[],
	);

	// 1. Query official market session status
	const statusQuery = useQuery({
		queryKey: marketKeys.status(),
		queryFn: () => marketService.getMarketStatus(),
		refetchInterval: 30_000,
		refetchIntervalInBackground: false,
	});

	// 2. Query live feed with 5s continuous polling and auto-sync
	const feedQuery = useQuery({
		queryKey: marketKeys.quotes(selectedCategory),
		queryFn: () =>
			marketService.getLiveMarketFeed(selectedCategory, isRefreshingManual),
		initialData: () => ({
			quotes: marketService.getCuratedQuotesSync(selectedCategory),
			ccl_rate: 1668.8,
			mep_rate: 1581.1,
			data_source: "CACHE_FALLBACK",
			updated_at: new Date().toISOString(),
		}),
		refetchInterval: 5000,
		staleTime: 0,
		refetchIntervalInBackground: true,
	});

	// 3. Query historical series with 5s auto-sync and smooth placeholder transitions
	const historyQuery = useQuery({
		queryKey: marketKeys.history(activeTicker, timeframe),
		queryFn: () => marketService.getHistoricalBars(activeTicker, timeframe),
		initialData: () =>
			buildDeterministicHistoricalBars(activeTicker, timeframe),
		refetchInterval: 5000,
		staleTime: 0,
		placeholderData: (prev) => prev,
	});

	const resolvedBars = useMemo(() => {
		if (historyQuery.data && historyQuery.data.length > 0) {
			return historyQuery.data;
		}
		return buildDeterministicHistoricalBars(activeTicker, timeframe);
	}, [historyQuery.data, activeTicker, timeframe]);

	// Manual refresh trigger: refetches live quotes and invalidates portfolio cache (MTM sync)
	const handleManualRefresh = async () => {
		setIsRefreshingManual(true);
		await Promise.all([
			queryClient.invalidateQueries({ queryKey: marketKeys.all }),
			queryClient.invalidateQueries({ queryKey: portfolioKeys.all }),
		]);
		await feedQuery.refetch();
		setTimeout(() => setIsRefreshingManual(false), 600);
	};

	const handleSelectTicker = (ticker: string) => {
		navigateToMarket(ticker);
	};

	// Filtered quotes based on search query
	const filteredQuotes = useMemo(() => {
		const raw = feedQuery.data?.quotes || [];
		if (!searchQuery.trim()) return raw;
		const term = searchQuery.trim().toLowerCase();
		return raw.filter(
			(q) =>
				q.ticker.toLowerCase().includes(term) ||
				q.name.toLowerCase().includes(term),
		);
	}, [feedQuery.data?.quotes, searchQuery]);

	// Active quote data for chart header
	const activeQuote = useMemo(() => {
		return (
			(feedQuery.data?.quotes || []).find((q) => q.ticker === activeTicker) ||
			allCuratedQuotes.find((q) => q.ticker === activeTicker)
		);
	}, [feedQuery.data?.quotes, allCuratedQuotes, activeTicker]);

	// 10-Year Quantitative & Fundamental Metrics for activeTicker
	const activeMetrics10Y = useMemo(
		() => marketService.getCalibrated10YMetricsSync(activeTicker),
		[activeTicker],
	);

	return (
		<div className="space-y-6">
			{/* 1. Official BYMA Session Status Bar with Live Multi-Source Badge & FX Rates */}
			<MarketStatusBar
				status={statusQuery.data}
				onRefresh={handleManualRefresh}
				isRefreshing={isRefreshingManual || feedQuery.isFetching}
				dataSource={feedQuery.data?.data_source}
				cclRate={feedQuery.data?.ccl_rate}
				mepRate={feedQuery.data?.mep_rate}
			/>

			{/* 2. Interactive SVG Financial Time Series Chart with Error Boundary */}
			<div className="relative">
				{historyQuery.isFetching && (
					<div className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-950/80 border border-sky-500/30 text-[11px] font-mono text-sky-400 backdrop-blur-sm shadow-sm animate-pulse">
						<span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
						<span>Actualizando 5s...</span>
					</div>
				)}
				<ChartErrorBoundary key={`${activeTicker}-${timeframe}`}>
					<FinancialTimeSeriesChart
						bars={resolvedBars}
						activeTicker={activeTicker}
						timeframe={timeframe}
						onTimeframeChange={(tf) => setTimeframe(tf)}
						quote={activeQuote}
						cclRate={feedQuery.data?.ccl_rate}
					/>
				</ChartErrorBoundary>
			</div>

			{/* 2.5. Real-Time 10-Year Quantitative & Fundamental Metrics Card */}
			<div className="p-5 rounded-xl bg-slate-900 border border-slate-800 shadow-lg space-y-4">
				<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-800">
					<div>
						<h3 className="text-xs font-semibold uppercase tracking-wider text-sky-400">
							Ficha Cuantitativa (10 Años) y Fundamentales —{" "}
							{activeMetrics10Y.ticker} ({activeMetrics10Y.asset_type})
						</h3>
						<p className="text-xs text-slate-400 mt-0.5">
							Ventana histórica computada:{" "}
							<span className="font-mono text-slate-200 font-semibold">
								{activeMetrics10Y.history_years_available.toFixed(1)} años
							</span>{" "}
							({activeMetrics10Y.data_points_count} ruedas desde{" "}
							<span className="font-mono">
								{activeMetrics10Y.history_start_date}
							</span>
							) en moneda dura (USD/CCL)
						</p>
					</div>
					<span className="text-[11px] font-mono px-2.5 py-1 rounded-md bg-slate-950 border border-slate-800 text-emerald-400">
						Retorno Esperado Compuesto (μ_quant): +
						{(activeMetrics10Y.composite_quant_return * 100).toFixed(2)}% anual
					</span>
				</div>

				<div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 text-xs font-mono">
					<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
						<span className="text-[10px] text-slate-400 block font-sans">
							CAGR 10Y (USD)
						</span>
						<span className="text-sm font-bold text-emerald-400">
							+{(activeMetrics10Y.cagr_annualized * 100).toFixed(1)}%
						</span>
					</div>
					<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
						<span className="text-[10px] text-slate-400 block font-sans">
							Volatilidad 10Y (σ)
						</span>
						<span className="text-sm font-bold text-amber-300">
							{(activeMetrics10Y.volatility_annualized * 100).toFixed(1)}%
						</span>
					</div>
					<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
						<span className="text-[10px] text-slate-400 block font-sans">
							Sharpe / Sortino
						</span>
						<span className="text-sm font-bold text-sky-300">
							{activeMetrics10Y.sharpe_ratio.toFixed(2)} /{" "}
							{activeMetrics10Y.sortino_ratio.toFixed(2)}
						</span>
					</div>
					<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
						<span className="text-[10px] text-slate-400 block font-sans">
							Max Drawdown
						</span>
						<span className="text-sm font-bold text-rose-400">
							-{formatQuantPct(activeMetrics10Y.max_drawdown)}
						</span>
					</div>
					<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
						<span className="text-[10px] text-slate-400 block font-sans">
							Beta / VaR 95% (1D)
						</span>
						<span className="text-sm font-bold text-slate-200">
							{activeMetrics10Y.beta_market.toFixed(2)} /{" "}
							{formatQuantPct(activeMetrics10Y.var_95_daily)}
						</span>
					</div>
					{activeMetrics10Y.asset_type === "BOND" ? (
						<>
							<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
								<span className="text-[10px] text-slate-400 block font-sans">
									TIR (YTM Anual)
								</span>
								<span className="text-sm font-bold text-amber-300">
									{activeMetrics10Y.ytm_tir_pct?.toFixed(2) ?? "14.50"}%
								</span>
							</div>
							<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
								<span className="text-[10px] text-slate-400 block font-sans">
									Modified Duration
								</span>
								<span className="text-sm font-bold text-sky-300">
									{activeMetrics10Y.modified_duration?.toFixed(2) ?? "2.50"}{" "}
									años
								</span>
							</div>
							<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
								<span className="text-[10px] text-slate-400 block font-sans">
									Paridad Técnica
								</span>
								<span className="text-sm font-bold text-emerald-300">
									{activeMetrics10Y.parity_pct?.toFixed(1) ?? "68.5"}%
								</span>
							</div>
						</>
					) : (
						<>
							<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
								<span className="text-[10px] text-slate-400 block font-sans">
									Ratio P/E / P/B
								</span>
								<span className="text-sm font-bold text-sky-300">
									{activeMetrics10Y.pe_ratio?.toFixed(1) ?? "12.0"}x /{" "}
									{activeMetrics10Y.pb_ratio?.toFixed(1) ?? "1.8"}x
								</span>
							</div>
							<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
								<span className="text-[10px] text-slate-400 block font-sans">
									ROE (Rentabilidad)
								</span>
								<span className="text-sm font-bold text-emerald-400">
									{activeMetrics10Y.roe_pct?.toFixed(1) ?? "18.5"}%
								</span>
							</div>
							<div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80">
								<span className="text-[10px] text-slate-400 block font-sans">
									Deuda/Patrimonio · Div
								</span>
								<span className="text-sm font-bold text-slate-200">
									{activeMetrics10Y.debt_to_equity?.toFixed(2) ?? "0.55"}x ·{" "}
									{activeMetrics10Y.dividend_yield_pct?.toFixed(1) ?? "0.0"}%
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
							className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all cursor-pointer ${
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
							className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 cursor-pointer"
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
				isLoading={feedQuery.isLoading}
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
