import { Layers, PieChart, TrendingUp } from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";
import type { Holding, Portfolio } from "../types/portfolio";

interface AllocationChartProps {
	portfolio: Portfolio | null;
	fxCcl?: number;
}

type ViewMode = "asset" | "sector" | "assetType";

interface AllocationSlice {
	key: string;
	label: string;
	subLabel?: string;
	valueArs: number;
	percentage: number;
	count: number;
	color: string;
}

const COLOR_PALETTE = [
	"#38bdf8", // Sky 400
	"#34d399", // Emerald 400
	"#818cf8", // Indigo 400
	"#fbbf24", // Amber 400
	"#c084fc", // Purple 400
	"#f472b6", // Pink 400
	"#2dd4bf", // Teal 400
	"#fb923c", // Orange 400
	"#60a5fa", // Blue 400
	"#a78bfa", // Violet 400
	"#e879f9", // Fuchsia 400
	"#4ade80", // Green 400
	"#f87171", // Red 400
	"#facc15", // Yellow 400
	"#22d3ee", // Cyan 400
	"#ec4899", // Pink 500
	"#14b8a6", // Teal 500
	"#6366f1", // Indigo 500
	"#8b5cf6", // Violet 500
	"#d946ef", // Fuchsia 500
	"#06b6d4", // Cyan 500
	"#10b981", // Emerald 500
	"#84cc16", // Lime 500
	"#f59e0b", // Amber 500
	"#94a3b8", // Slate 400
];

const ASSET_TYPE_LABELS: Record<string, string> = {
	CEDEAR: "CEDEARs (Renta Variable Int.)",
	EQUITY: "Acciones Locales",
	BOND_SOVEREIGN: "Bonos Soberanos (AL30/GD30)",
	BOND_CORPORATE: "Obligaciones Negociables (ONs)",
	TREASURY_BILL: "Letras del Tesoro (LECAPs)",
	CASH: "Efectivo y Liquidez",
	OTHER: "Otros Instrumentos",
};

const SECTOR_LABELS: Record<string, string> = {
	TECHNOLOGY: "Tecnología",
	FINANCIAL_SERVICES: "Finanzas y Banca",
	ENERGY: "Energía y Petróleo",
	COMMUNICATION_SERVICES: "Comunicaciones",
	CONSUMER_CYCLICAL: "Consumo Cíclico",
	CONSUMER_DEFENSIVE: "Consumo Defensivo",
	HEALTHCARE: "Salud y Farmacia",
	INDUSTRIALS: "Industria y Bienes de Capital",
	BASIC_MATERIALS: "Materiales Básicos",
	UTILITIES: "Servicios Públicos",
	REAL_ESTATE: "Bienes Raíces",
	GOVERNMENT: "Títulos Públicos / Gobierno",
	CASH: "Liquidez y Efectivo",
	OTHER: "Otros / Diversificado",
};

export const AllocationChart: React.FC<AllocationChartProps> = ({
	portfolio,
	fxCcl = 1300.0,
}) => {
	const [viewMode, setViewMode] = useState<ViewMode>("asset");
	const [hoveredSlice, setHoveredSlice] = useState<AllocationSlice | null>(
		null,
	);
	const [clickedSlice, setClickedSlice] = useState<AllocationSlice | null>(
		null,
	);

	const { slices, totalValueArs } = useMemo(() => {
		if (!portfolio) return { slices: [], totalValueArs: 0 };

		const holdings = portfolio.holdings || [];
		let holdingsTotalArs = 0;

		const getHoldingValueArs = (h: Holding): number => {
			const isUsd = h.asset?.currency === "USD";
			const mult = isUsd ? fxCcl : 1.0;
			return h.quantity * h.current_price * mult;
		};

		holdings.forEach((h) => {
			holdingsTotalArs += getHoldingValueArs(h);
		});

		const cashArs = portfolio.cash_balance_ars || 0;
		const cashUsdInArs = (portfolio.cash_balance_usd || 0) * fxCcl;
		const totalCashArs = cashArs + cashUsdInArs;

		const totalPortfolioArs = holdingsTotalArs + totalCashArs;

		if (totalPortfolioArs <= 0) {
			return { slices: [], totalValueArs: 0 };
		}

		const groupMap: Record<
			string,
			{ value: number; count: number; label: string; subLabel?: string }
		> = {};

		if (viewMode === "assetType") {
			holdings.forEach((h) => {
				const typeKey = h.asset?.asset_type || "OTHER";
				const val = getHoldingValueArs(h);
				if (!groupMap[typeKey]) {
					groupMap[typeKey] = {
						value: 0,
						count: 0,
						label: ASSET_TYPE_LABELS[typeKey] || typeKey,
					};
				}
				groupMap[typeKey].value += val;
				groupMap[typeKey].count += 1;
			});

			if (totalCashArs > 0) {
				groupMap["CASH"] = {
					value: totalCashArs,
					count: 1,
					label: ASSET_TYPE_LABELS["CASH"],
				};
			}
		} else if (viewMode === "sector") {
			holdings.forEach((h) => {
				const secKey = h.asset?.sector || "OTHER";
				const val = getHoldingValueArs(h);
				if (!groupMap[secKey]) {
					groupMap[secKey] = {
						value: 0,
						count: 0,
						label: SECTOR_LABELS[secKey] || secKey,
					};
				}
				groupMap[secKey].value += val;
				groupMap[secKey].count += 1;
			});

			if (totalCashArs > 0) {
				groupMap["CASH"] = {
					value: totalCashArs,
					count: 1,
					label: SECTOR_LABELS["CASH"],
				};
			}
		} else {
			// viewMode === "asset" (Por Activo individual)
			holdings.forEach((h) => {
				const ticker = h.asset_ticker || "UNKNOWN";
				const val = getHoldingValueArs(h);
				const assetName =
					h.asset?.name && h.asset.name !== ticker ? h.asset.name : undefined;
				if (!groupMap[ticker]) {
					groupMap[ticker] = {
						value: 0,
						count: 0,
						label: ticker,
						subLabel: assetName,
					};
				}
				groupMap[ticker].value += val;
				groupMap[ticker].count += 1;
			});

			if (totalCashArs > 0) {
				groupMap["EFECTIVO"] = {
					value: totalCashArs,
					count: 1,
					label: "EFECTIVO",
					subLabel: "Saldos ARS / USD",
				};
			}
		}

		const sortedEntries = Object.entries(groupMap).sort(
			([, a], [, b]) => b.value - a.value,
		);

		const resultSlices: AllocationSlice[] = sortedEntries.map(
			([key, data], idx) => {
				const pct = (data.value / totalPortfolioArs) * 100;
				return {
					key,
					label: data.label,
					subLabel: data.subLabel,
					valueArs: data.value,
					percentage: round2(pct),
					count: data.count,
					color: COLOR_PALETTE[idx % COLOR_PALETTE.length],
				};
			},
		);

		return { slices: resultSlices, totalValueArs: totalPortfolioArs };
	}, [portfolio, fxCcl, viewMode]);

	const activeSlice =
		hoveredSlice || clickedSlice || (slices.length > 0 ? slices[0] : null);

	const formatCurrency = (val: number) => {
		return new Intl.NumberFormat("es-AR", {
			style: "currency",
			currency: "ARS",
			maximumFractionDigits: 0,
		}).format(val);
	};

	function round2(num: number): number {
		return Math.round((num + Number.EPSILON) * 100) / 100;
	}

	const donutSegments = useMemo(() => {
		let accumulatedAngle = 0;
		const radius = 64;
		const circumference = 2 * Math.PI * radius;

		return slices.map((slice) => {
			const strokeDash = (slice.percentage / 100) * circumference;
			const strokeDashoffset = -accumulatedAngle;
			accumulatedAngle += strokeDash;

			return {
				...slice,
				strokeDasharray: `${strokeDash} ${circumference - strokeDash}`,
				strokeDashoffset,
			};
		});
	}, [slices]);

	if (!portfolio || slices.length === 0) {
		return (
			<div className="bg-slate-800/80 border border-slate-700/80 rounded-xl p-6 text-center">
				<div className="w-12 h-12 rounded-full bg-slate-900 mx-auto flex items-center justify-center text-slate-500 mb-3">
					<PieChart className="w-6 h-6" />
				</div>
				<h4 className="text-sm font-semibold text-slate-200">
					Sin tenencias para distribuir
				</h4>
				<p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
					Carga un archivo de Balanz o añade activos manualmente para visualizar
					la diversificación por activo individual, sector o tipo de activo.
				</p>
			</div>
		);
	}

	return (
		<div className="bg-slate-800/80 border border-slate-700/80 rounded-xl p-5 shadow-lg space-y-5">
			{/* Header and Toggle Controls */}
			<div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
				<div>
					<h3 className="text-base font-bold text-white flex items-center space-x-2">
						<PieChart className="w-4 h-4 text-sky-400" />
						<span>Distribución Cuantitativa de la Cartera</span>
					</h3>
					<p className="text-xs text-slate-400 mt-0.5">
						Composición patrimonial ponderada sobre el valor total consolidado
					</p>
				</div>

				{/* View Switcher Toggle: Por Activo | Por Sector | Por Tipo de Activo */}
				<div className="flex items-center bg-slate-900/90 p-1 rounded-lg border border-slate-700/80 self-stretch sm:self-auto gap-1">
					<button
						onClick={() => {
							setViewMode("asset");
							setHoveredSlice(null);
							setClickedSlice(null);
						}}
						className={`flex-1 sm:flex-initial flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
							viewMode === "asset"
								? "bg-sky-600 text-white shadow-sm"
								: "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
						}`}
					>
						<TrendingUp className="w-3.5 h-3.5" />
						<span>Por Activo</span>
					</button>
					<button
						onClick={() => {
							setViewMode("sector");
							setHoveredSlice(null);
							setClickedSlice(null);
						}}
						className={`flex-1 sm:flex-initial flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
							viewMode === "sector"
								? "bg-sky-600 text-white shadow-sm"
								: "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
						}`}
					>
						<PieChart className="w-3.5 h-3.5" />
						<span>Por Sector</span>
					</button>
					<button
						onClick={() => {
							setViewMode("assetType");
							setHoveredSlice(null);
							setClickedSlice(null);
						}}
						className={`flex-1 sm:flex-initial flex items-center justify-center space-x-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
							viewMode === "assetType"
								? "bg-sky-600 text-white shadow-sm"
								: "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
						}`}
					>
						<Layers className="w-3.5 h-3.5" />
						<span>Por Tipo de Activo</span>
					</button>
				</div>
			</div>

			{/* Main Visual Section: SVG Donut + Breakdown List */}
			<div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-center">
				{/* SVG Interactive Donut Chart */}
				<div className="md:col-span-5 flex flex-col items-center justify-center relative p-2">
					<div className="relative w-52 h-52 flex items-center justify-center">
						<svg
							viewBox="0 0 160 160"
							className="w-full h-full -rotate-90 transform"
						>
							<circle
								cx="80"
								cy="80"
								r="64"
								fill="transparent"
								stroke="#1e293b"
								strokeWidth="24"
							/>
							{donutSegments.map((segment) => {
								const isHovered = activeSlice?.key === segment.key;
								return (
									<circle
										key={segment.key}
										cx="80"
										cy="80"
										r="64"
										fill="transparent"
										stroke={segment.color}
										strokeWidth={isHovered ? 26 : 22}
										strokeDasharray={segment.strokeDasharray}
										strokeDashoffset={segment.strokeDashoffset}
										className="cursor-pointer transition-all duration-200 hover:opacity-90"
										onMouseEnter={() => setHoveredSlice(segment)}
										onClick={() => setClickedSlice(segment)}
									/>
								);
							})}
						</svg>

						{/* Central Donut Readout */}
						<div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none px-3">
							<span
								className="text-xs font-bold text-slate-200 truncate max-w-[125px]"
								title={activeSlice?.label}
							>
								{activeSlice ? activeSlice.label : "Total Cartera"}
							</span>
							{activeSlice?.subLabel && (
								<span
									className="text-[10px] text-slate-400 truncate max-w-[115px] -mt-0.5"
									title={activeSlice.subLabel}
								>
									{activeSlice.subLabel}
								</span>
							)}
							<span className="text-xl font-black text-white tracking-tight mt-0.5">
								{activeSlice ? `${activeSlice.percentage}%` : "100%"}
							</span>
							<span className="text-[10px] font-semibold text-slate-400 mt-0.5">
								{activeSlice
									? formatCurrency(activeSlice.valueArs)
									: formatCurrency(totalValueArs)}
							</span>
						</div>
					</div>
				</div>

				{/* Detailed Breakdown List with Progress Bars */}
				<div className="md:col-span-7 space-y-2.5">
					<div className="flex items-center justify-between text-[11px] font-semibold text-slate-400 uppercase tracking-wider px-1">
						<span>
							{viewMode === "asset"
								? "Ticker / Activo"
								: viewMode === "sector"
									? "Sector Económico"
									: "Clase de Instrumento"}
						</span>
						<div className="flex items-center space-x-6">
							<span>Valuación (ARS)</span>
							<span className="w-12 text-right">Peso</span>
						</div>
					</div>

					<div className="space-y-2 max-h-64 overflow-y-auto pr-1">
						{slices.map((slice) => {
							const isSelected = activeSlice?.key === slice.key;
							return (
								<div
									key={slice.key}
									onMouseEnter={() => setHoveredSlice(slice)}
									onClick={() => setClickedSlice(slice)}
									className={`p-2 rounded-lg transition border cursor-pointer ${
										isSelected
											? "bg-slate-900/90 border-slate-600 shadow-sm ring-1 ring-sky-500/30"
											: "bg-slate-900/40 border-slate-700/60 hover:bg-slate-900/60 hover:border-slate-600"
									}`}
								>
									<div className="flex items-center justify-between text-xs mb-1.5">
										<div className="flex items-center space-x-2 truncate">
											<span
												className="w-2.5 h-2.5 rounded-full flex-shrink-0"
												style={{ backgroundColor: slice.color }}
											/>
											<div className="truncate flex items-baseline space-x-1.5">
												<span className="font-bold text-slate-100 font-mono text-xs">
													{slice.label}
												</span>
												{slice.subLabel && (
													<span
														className="text-[11px] text-slate-400 truncate max-w-[160px] sm:max-w-[200px]"
														title={slice.subLabel}
													>
														{slice.subLabel}
													</span>
												)}
												{slice.count > 0 &&
													viewMode !== "asset" &&
													slice.key !== "CASH" && (
														<span className="text-[10px] text-slate-500 flex-shrink-0">
															({slice.count}{" "}
															{slice.count === 1 ? "activo" : "activos"})
														</span>
													)}
											</div>
										</div>

										<div className="flex items-center space-x-4 flex-shrink-0">
											<span className="font-mono text-slate-300 font-medium text-[11px]">
												{formatCurrency(slice.valueArs)}
											</span>
											<span className="w-12 text-right font-mono font-bold text-sky-400 text-xs">
												{slice.percentage.toFixed(1)}%
											</span>
										</div>
									</div>

									{/* Horizontal Bar with fill */}
									<div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
										<div
											className="h-full rounded-full transition-all duration-300"
											style={{
												width: `${slice.percentage}%`,
												backgroundColor: slice.color,
											}}
										/>
									</div>
								</div>
							);
						})}
					</div>
				</div>
			</div>

			{/* Segmented Cumulative Bar */}
			<div className="pt-2">
				<div className="w-full h-3 rounded-full bg-slate-950 flex overflow-hidden p-0.5 border border-slate-800 shadow-inner">
					{slices.map((slice) => (
						<div
							key={slice.key}
							title={`${slice.label}: ${slice.percentage}%`}
							style={{
								width: `${slice.percentage}%`,
								backgroundColor: slice.color,
							}}
							className="h-full transition-all hover:brightness-125 cursor-pointer first:rounded-l-full last:rounded-r-full"
							onMouseEnter={() => setHoveredSlice(slice)}
							onClick={() => setClickedSlice(slice)}
						/>
					))}
				</div>
				<div className="flex items-center justify-between text-[11px] text-slate-400 mt-1.5 px-0.5">
					<span>
						Total Consolidado Cartera: {formatCurrency(totalValueArs)}
					</span>
					<span className="text-slate-500 font-medium">100% Ponderado</span>
				</div>
			</div>
		</div>
	);
};
