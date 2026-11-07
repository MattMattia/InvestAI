/**
 * OrderExecutionModal Component for InvestAI Enterprise.
 * High-precision assisted order dispatch modal featuring dynamic BYMA species selector,
 * native currency resolution (ARS vs USD), pre-trade fee breakdown (Broker 0.50%, VAT 21%,
 * BYMA/CNV 0.10%), real-time inventory & liquidity guards, and immediate FSM settlement.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
	AlertCircle,
	AlertTriangle,
	ArrowDownRight,
	ArrowUpRight,
	Briefcase,
	CheckCircle2,
	Loader2,
	Lock,
	Receipt,
	ShieldAlert,
	TrendingUp,
	Wallet,
	X,
} from "lucide-react";
import type React from "react";
import { useEffect, useId, useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { usePortfolio, usePortfolios } from "@/hooks/usePortfolios";
import {
	calculateOrderCostBreakdown,
	formatMoney,
	inferAssetNativeCurrency,
	parseDecimalSafe,
} from "@/lib/formatters";
import { marketKeys, orderKeys, portfolioKeys } from "@/lib/queryKeys";
import { marketService } from "@/services/marketService";
import { orderService } from "@/services/orderService";
import type { CreateOrderPayload, OrderRecord, Portfolio } from "@/types/api";

interface OrderExecutionModalProps {
	isOpen: boolean;
	onClose: () => void;
	initialTicker?: string;
	initialPrice?: number;
	initialCurrency?: "ARS" | "USD";
	initialPortfolioId?: string;
	onOrderCreated?: (order: OrderRecord) => void;
}

export const OrderExecutionModal: React.FC<OrderExecutionModalProps> = ({
	isOpen,
	onClose,
	initialTicker = "GGAL",
	initialPrice,
	initialCurrency,
	initialPortfolioId,
	onOrderCreated,
}) => {
	const modalId = useId();
	const queryClient = useQueryClient();
	const { isAuthenticated, isTrader, isAdmin } = useAuth();
	const canTrade = isAuthenticated && (isTrader || isAdmin);

	const { data: portfolios = [] } = usePortfolios();
	const curatedCatalog = useMemo(
		() => marketService.getCuratedQuotesSync("ALL"),
		[],
	);

	// Form State
	const [selectedPortfolioId, setSelectedPortfolioId] = useState<string>(
		initialPortfolioId || "",
	);
	const [selectedTicker, setSelectedTicker] = useState<string>(
		(initialTicker || "GGAL").trim().toUpperCase(),
	);
	const [side, setSide] = useState<"BUY" | "SELL">("BUY");
	const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
	const [quantity, setQuantity] = useState<number>(10);
	const [customPrice, setCustomPrice] = useState<number>(
		initialPrice || 5120.0,
	);
	const [justification, setJustification] = useState<string>("");
	const [autoExecuteOnSubmit, setAutoExecuteOnSubmit] = useState<boolean>(true);
	const [successOrder, setSuccessOrder] = useState<OrderRecord | null>(null);
	const [submitError, setSubmitError] = useState<string | null>(null);

	// Fetch full portfolio detail (including holdings array) for the selected portfolio
	const resolvedPortfolioId =
		selectedPortfolioId || initialPortfolioId || portfolios[0]?.id || "";
	const { data: detailedPortfolio } = usePortfolio(resolvedPortfolioId);

	const activePortfolio = useMemo<Portfolio | undefined>(() => {
		if (detailedPortfolio && detailedPortfolio.id === resolvedPortfolioId) {
			return detailedPortfolio;
		}
		return (
			portfolios.find((p) => p.id === resolvedPortfolioId) || portfolios[0]
		);
	}, [detailedPortfolio, portfolios, resolvedPortfolioId]);

	// Combined species catalog (26 BYMA species + any custom portfolio holding)
	const speciesOptions = useMemo(() => {
		const map = new Map<
			string,
			{
				ticker: string;
				name: string;
				asset_type: string;
				currency: "ARS" | "USD";
				price: number;
			}
		>();

		for (const q of curatedCatalog) {
			map.set(q.ticker, {
				ticker: q.ticker,
				name: q.name,
				asset_type: q.asset_type,
				currency: q.currency,
				price: q.last_price,
			});
		}

		if (activePortfolio?.holdings) {
			for (const h of activePortfolio.holdings) {
				const t = (h.asset_ticker || "").trim().toUpperCase();
				if (t && !map.has(t)) {
					const cur = inferAssetNativeCurrency(
						t,
						(h.asset?.currency as "ARS" | "USD") || "ARS",
					);
					map.set(t, {
						ticker: t,
						name: h.asset?.name || `${t} (Posición en Cartera)`,
						asset_type: h.asset?.asset_type || "STOCK",
						currency: cur,
						price: parseDecimalSafe(h.current_price) || 100.0,
					});
				}
			}
		}

		return Array.from(map.values());
	}, [curatedCatalog, activePortfolio]);

	const activeSpecies = useMemo(() => {
		const clean = selectedTicker.trim().toUpperCase();
		return (
			speciesOptions.find((s) => s.ticker === clean) || {
				ticker: clean,
				name: clean,
				asset_type: "STOCK",
				currency: inferAssetNativeCurrency(clean, initialCurrency || "ARS"),
				price: initialPrice && initialPrice > 0 ? initialPrice : 1000.0,
			}
		);
	}, [speciesOptions, selectedTicker, initialCurrency, initialPrice]);

	// Sync initial props on open
	useEffect(() => {
		if (isOpen) {
			const targetPortId = initialPortfolioId || portfolios[0]?.id || "";
			if (targetPortId) {
				setSelectedPortfolioId(targetPortId);
			}
			const cleanInitTicker = (initialTicker || "GGAL").trim().toUpperCase();
			setSelectedTicker(cleanInitTicker);

			const matched = curatedCatalog.find((q) => q.ticker === cleanInitTicker);
			const resolvedPrice =
				initialPrice && initialPrice > 0
					? initialPrice
					: matched?.last_price || 5120.0;

			setCustomPrice(resolvedPrice);
			setSuccessOrder(null);
			setSubmitError(null);
		}
	}, [
		isOpen,
		initialPortfolioId,
		initialTicker,
		initialPrice,
		portfolios,
		curatedCatalog,
	]);

	// Update reference price when user picks a different ticker in the dropdown
	const handleSelectSpecies = (newTicker: string) => {
		const clean = newTicker.trim().toUpperCase();
		setSelectedTicker(clean);
		const found = speciesOptions.find((s) => s.ticker === clean);
		if (found) {
			setCustomPrice(found.price);
		}
		setSubmitError(null);
	};

	// Handle ESC key press
	useEffect(() => {
		if (!isOpen) return;
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [isOpen, onClose]);

	const marketReferencePrice = activeSpecies.price;
	const effectivePrice =
		orderType === "MARKET" ? marketReferencePrice : customPrice;
	const currency: "ARS" | "USD" = activeSpecies.currency;

	// Pre-Trade Cost Breakdown
	const breakdown = useMemo(() => {
		return calculateOrderCostBreakdown({
			quantity,
			price: effectivePrice,
			side,
		});
	}, [quantity, effectivePrice, side]);

	// Holding inventory check in SELL mode (using full detailedPortfolio.holdings)
	const currentHoldingShares = useMemo(() => {
		const holdingsList =
			detailedPortfolio?.holdings || activePortfolio?.holdings || [];
		const target = selectedTicker.trim().toUpperCase();
		const h = holdingsList.find(
			(item) =>
				(item.asset_ticker || (item as any).ticker || "")
					.trim()
					.toUpperCase() === target,
		);
		return h ? Math.floor(parseDecimalSafe(h.quantity)) : 0;
	}, [detailedPortfolio, activePortfolio, selectedTicker]);

	const hasInsufficientHoldings =
		side === "SELL" && quantity > currentHoldingShares;

	// Cash liquidity check in BUY mode against true native currency balance
	const availableCash = useMemo(() => {
		if (!activePortfolio) return 0;
		return currency === "ARS"
			? parseDecimalSafe(activePortfolio.cash_balance_ars)
			: parseDecimalSafe(activePortfolio.cash_balance_usd);
	}, [activePortfolio, currency]);

	const hasInsufficientCash =
		side === "BUY" && breakdown.netTotal > availableCash;

	// Mutation
	const orderMutation = useMutation({
		mutationFn: async (payload: CreateOrderPayload) => {
			const created = await orderService.createOrder(payload);
			if (autoExecuteOnSubmit) {
				return await orderService.executeOrder(created.id);
			}
			return created;
		},
		onSuccess: (order) => {
			setSuccessOrder(order);
			setSubmitError(null);

			// Invalidate relevant caches in parallel
			queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
			queryClient.invalidateQueries({
				queryKey: portfolioKeys.detail(order.portfolio_id),
			});
			queryClient.invalidateQueries({ queryKey: orderKeys.all });
			queryClient.invalidateQueries({ queryKey: marketKeys.quotes() });

			if (onOrderCreated) {
				onOrderCreated(order);
			}
		},
		onError: (err: any) => {
			const msg =
				err?.response?.data?.detail ||
				err?.response?.data?.message ||
				err?.message ||
				"Error al despachar la orden a BYMA.";
			setSubmitError(typeof msg === "string" ? msg : JSON.stringify(msg));
		},
	});

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault();
		if (!canTrade || !activePortfolio) return;
		if (quantity <= 0) {
			setSubmitError("La cantidad debe ser un entero estrictamente positivo.");
			return;
		}
		if (hasInsufficientHoldings) {
			setSubmitError(
				`No dispone de tenencias suficientes para vender ${quantity} títulos de ${selectedTicker}.`,
			);
			return;
		}
		if (hasInsufficientCash) {
			setSubmitError(
				`Saldo de caja en ${currency} insuficiente para cubrir la compra con aranceles.`,
			);
			return;
		}

		setSubmitError(null);
		orderMutation.mutate({
			portfolio_id: activePortfolio.id,
			ticker: selectedTicker,
			side,
			order_type: orderType,
			quantity,
			price: effectivePrice,
			currency,
			justification: justification.trim() || undefined,
		});
	};

	if (!isOpen) return null;

	return (
		<div
			role="dialog"
			aria-modal="true"
			aria-labelledby={`${modalId}-title`}
			className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200"
		>
			<div className="relative w-full max-w-xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
				{/* Modal Header */}
				<div className="flex items-center justify-between px-6 py-4 border-b border-slate-800/80 bg-slate-950/40">
					<div className="flex items-center gap-2.5">
						<div
							className={`h-9 w-9 rounded-xl flex items-center justify-center font-bold text-xs ${
								side === "BUY"
									? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
									: "bg-rose-500/20 text-rose-400 border border-rose-500/30"
							}`}
						>
							{side === "BUY" ? (
								<ArrowUpRight className="h-5 w-5" />
							) : (
								<ArrowDownRight className="h-5 w-5" />
							)}
						</div>
						<div>
							<h2
								id={`${modalId}-title`}
								className="text-base font-bold text-white tracking-tight flex items-center gap-2"
							>
								<span>Operar Especie: {selectedTicker}</span>
								<span
									className={`text-xs font-mono px-2 py-0.5 rounded border ${
										currency === "USD"
											? "bg-amber-500/15 text-amber-300 border-amber-500/30"
											: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
									}`}
								>
									{currency}
								</span>
							</h2>
							<p className="text-xs text-slate-400 font-mono truncate max-w-sm">
								{activeSpecies.name} • Precio Ref:{" "}
								{formatMoney(marketReferencePrice, currency)}
							</p>
						</div>
					</div>

					<button
						type="button"
						onClick={onClose}
						className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
						title="Cerrar ventana"
					>
						<X className="h-5 w-5" />
					</button>
				</div>

				{/* Modal Body */}
				<div className="p-6 overflow-y-auto space-y-4">
					{/* RBAC Viewer Warning */}
					{!canTrade && (
						<div className="p-3.5 rounded-xl bg-amber-950/40 border border-amber-800/40 flex items-start gap-2.5 text-xs text-amber-200">
							<ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
							<div>
								<span className="font-semibold block text-amber-300">
									Cuenta en Modo Solo Lectura (VIEWER)
								</span>
								El despacho de órdenes al mercado exige privilegios de{" "}
								<strong>TRADER</strong> o <strong>ADMIN</strong>. Puede cambiar
								su rol en caliente haciendo clic sobre su usuario en el
								encabezado.
							</div>
						</div>
					)}

					{successOrder ? (
						/* Success confirmation card */
						<div className="p-6 rounded-2xl bg-emerald-950/20 border border-emerald-800/40 text-center space-y-4">
							<div className="h-12 w-12 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mx-auto">
								<CheckCircle2 className="h-7 w-7" />
							</div>
							<div>
								<h3 className="text-base font-bold text-white">
									{successOrder.status === "EXECUTED"
										? "Orden Ejecutada y Liquidada en Cartera"
										: "Orden Registrada en la FSM"}
								</h3>
								<p className="text-xs text-slate-400 font-mono mt-1">
									ID: {successOrder.id.slice(0, 12)} • Estado FSM:{" "}
									{successOrder.status}
								</p>
							</div>

							<div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-left font-mono text-xs space-y-2">
								<div className="flex justify-between">
									<span className="text-slate-400">Operación:</span>
									<span
										className={`font-bold ${
											successOrder.side === "BUY"
												? "text-emerald-400"
												: "text-rose-400"
										}`}
									>
										{successOrder.side === "BUY" ? "COMPRA" : "VENTA"}{" "}
										{successOrder.quantity} {successOrder.ticker}
									</span>
								</div>
								<div className="flex justify-between">
									<span className="text-slate-400">Precio Operado:</span>
									<span className="text-white">
										{formatMoney(successOrder.price, currency)}
									</span>
								</div>
								<div className="flex justify-between">
									<span className="text-slate-400">Aranceles BYMA/CNV:</span>
									<span className="text-amber-400">
										{formatMoney(successOrder.total_fees, currency)}
									</span>
								</div>
								<div className="flex justify-between border-t border-slate-800 pt-1 font-bold">
									<span className="text-slate-200">
										Total Liquidado ({currency}):
									</span>
									<span className="text-sky-400">
										{formatMoney(successOrder.net_amount, currency)}
									</span>
								</div>
							</div>

							<button
								type="button"
								onClick={onClose}
								className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-medium text-xs transition-colors"
							>
								Cerrar y Actualizar Cartera
							</button>
						</div>
					) : (
						<form onSubmit={handleSubmit} className="space-y-4">
							{/* Destination Portfolio Selector & Species Selector */}
							<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
								{/* Portfolio Selector */}
								<div className="space-y-1.5">
									<label className="text-xs font-medium text-slate-300 flex items-center justify-between">
										<span className="flex items-center gap-1.5">
											<Briefcase className="h-3.5 w-3.5 text-sky-400" />
											Cartera Operativa:
										</span>
									</label>
									<select
										value={resolvedPortfolioId}
										onChange={(e) => setSelectedPortfolioId(e.target.value)}
										disabled={!canTrade || orderMutation.isPending}
										className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500"
									>
										{portfolios.map((p) => (
											<option key={p.id} value={p.id}>
												{p.name} ({p.investor_profile})
											</option>
										))}
									</select>
								</div>

								{/* Dynamic BYMA Species Selector */}
								<div className="space-y-1.5">
									<label className="text-xs font-medium text-slate-300 flex items-center justify-between">
										<span className="flex items-center gap-1.5">
											<TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
											Especie BYMA:
										</span>
										<span className="font-mono text-[10px] text-slate-400">
											Tenencia: {currentHoldingShares} nominales
										</span>
									</label>
									<select
										value={selectedTicker}
										onChange={(e) => handleSelectSpecies(e.target.value)}
										disabled={!canTrade || orderMutation.isPending}
										aria-label="Seleccionar especie BYMA"
										className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs font-mono text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
									>
										<optgroup label="Acciones Líderes BYMA (ARS)">
											{speciesOptions
												.filter((s) => s.asset_type === "STOCK")
												.map((s) => (
													<option key={s.ticker} value={s.ticker}>
														{s.ticker} — {formatMoney(s.price, s.currency)} (
														{s.name.slice(0, 22)})
													</option>
												))}
										</optgroup>
										<optgroup label="CEDEARs (ARS)">
											{speciesOptions
												.filter((s) => s.asset_type === "CEDEAR")
												.map((s) => (
													<option key={s.ticker} value={s.ticker}>
														{s.ticker} — {formatMoney(s.price, s.currency)} (
														{s.name.slice(0, 22)})
													</option>
												))}
										</optgroup>
										<optgroup label="Bonos Soberanos (ARS / USD)">
											{speciesOptions
												.filter((s) => s.asset_type === "BOND")
												.map((s) => (
													<option key={s.ticker} value={s.ticker}>
														{s.ticker} ({s.currency}) —{" "}
														{formatMoney(s.price, s.currency)}
													</option>
												))}
										</optgroup>
									</select>
								</div>
							</div>

							{/* Liquidity & Inventory Status Bar */}
							{activePortfolio && (
								<div className="px-3.5 py-2 rounded-xl bg-slate-950/80 border border-slate-800/80 flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono">
									<span className="text-slate-400 flex items-center gap-1.5">
										<Wallet className="h-3.5 w-3.5 text-emerald-400" />
										Caja {currency} Disponible:{" "}
										<strong className="text-slate-100">
											{formatMoney(availableCash, currency)}
										</strong>
									</span>
									<span className="text-slate-400">
										Posición en {selectedTicker}:{" "}
										<strong className="text-sky-400">
											{currentHoldingShares.toLocaleString("es-AR")} títulos
										</strong>
									</span>
								</div>
							)}

							{/* Side Switcher (BUY vs SELL) */}
							<div className="grid grid-cols-2 gap-2">
								<button
									type="button"
									onClick={() => setSide("BUY")}
									disabled={!canTrade || orderMutation.isPending}
									className={`py-2 px-3 rounded-xl text-xs font-mono font-bold flex items-center justify-center gap-1.5 transition-all ${
										side === "BUY"
											? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow-sm shadow-emerald-500/10"
											: "bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-300"
									}`}
								>
									<ArrowUpRight className="h-4 w-4" />
									<span>COMPRA ({currency})</span>
								</button>

								<button
									type="button"
									onClick={() => setSide("SELL")}
									disabled={!canTrade || orderMutation.isPending}
									className={`py-2 px-3 rounded-xl text-xs font-mono font-bold flex items-center justify-center gap-1.5 transition-all ${
										side === "SELL"
											? "bg-rose-500/20 text-rose-400 border border-rose-500/40 shadow-sm shadow-rose-500/10"
											: "bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-300"
									}`}
								>
									<ArrowDownRight className="h-4 w-4" />
									<span>VENTA ({currency})</span>
								</button>
							</div>

							{/* Order Type & Quantity Inputs */}
							<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
								{/* Order Type */}
								<div className="space-y-1">
									<label className="text-[11px] font-medium text-slate-400 font-mono">
										Tipo de Orden:
									</label>
									<div className="grid grid-cols-2 gap-1.5">
										<button
											type="button"
											onClick={() => setOrderType("MARKET")}
											className={`py-1.5 text-xs font-mono rounded-lg transition-colors ${
												orderType === "MARKET"
													? "bg-sky-500/20 text-sky-400 border border-sky-500/30"
													: "bg-slate-950 text-slate-400 border border-slate-800"
											}`}
										>
											MERCADO
										</button>
										<button
											type="button"
											onClick={() => setOrderType("LIMIT")}
											className={`py-1.5 text-xs font-mono rounded-lg transition-colors ${
												orderType === "LIMIT"
													? "bg-sky-500/20 text-sky-400 border border-sky-500/30"
													: "bg-slate-950 text-slate-400 border border-slate-800"
											}`}
										>
											LÍMITE
										</button>
									</div>
								</div>

								{/* Quantity + Quick Fill Buttons on SELL */}
								<div className="space-y-1">
									<label className="text-[11px] font-medium text-slate-400 font-mono flex items-center justify-between">
										<span>Cantidad (Nominal):</span>
										{side === "SELL" && currentHoldingShares > 0 && (
											<div className="flex items-center gap-1">
												{[
													{ label: "25%", pct: 0.25 },
													{ label: "50%", pct: 0.5 },
													{ label: "75%", pct: 0.75 },
													{ label: "100% (Máx)", pct: 1.0 },
												].map((btn) => (
													<button
														key={btn.label}
														type="button"
														onClick={() =>
															setQuantity(
																Math.max(
																	1,
																	Math.floor(currentHoldingShares * btn.pct),
																),
															)
														}
														className="px-1.5 py-0.5 rounded bg-slate-800 hover:bg-sky-500/20 text-[9px] text-sky-400 border border-slate-700 transition-colors"
													>
														{btn.label}
													</button>
												))}
											</div>
										)}
									</label>
									<input
										type="number"
										min="1"
										step="1"
										value={quantity}
										onChange={(e) =>
											setQuantity(Math.max(1, parseInt(e.target.value) || 1))
										}
										disabled={!canTrade || orderMutation.isPending}
										className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
									/>
								</div>
							</div>

							{/* Price Row (If LIMIT) */}
							{orderType === "LIMIT" && (
								<div className="space-y-1">
									<label className="text-[11px] font-medium text-slate-400 font-mono">
										Precio Límite ({currency}):
									</label>
									<input
										type="number"
										step="0.01"
										min="0.01"
										value={customPrice}
										onChange={(e) =>
											setCustomPrice(parseFloat(e.target.value) || 0)
										}
										disabled={!canTrade || orderMutation.isPending}
										className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
									/>
								</div>
							)}

							{/* Justification & Immediate Execution Toggle */}
							<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
								<div className="space-y-1">
									<label className="text-[11px] font-medium text-slate-400 font-mono">
										Motivo / Justificación (Opcional):
									</label>
									<input
										type="text"
										placeholder="Ej: Rebalanceo táctico, toma de ganancias"
										value={justification}
										onChange={(e) => setJustification(e.target.value)}
										disabled={!canTrade || orderMutation.isPending}
										className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500 font-sans"
									/>
								</div>

								<label className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-800 cursor-pointer text-xs text-slate-300 select-none">
									<input
										type="checkbox"
										checked={autoExecuteOnSubmit}
										onChange={(e) => setAutoExecuteOnSubmit(e.target.checked)}
										className="rounded accent-emerald-500"
									/>
									<span className="font-mono text-[11px]">
										Liquidar al instante (EXECUTED)
									</span>
								</label>
							</div>

							{/* Pre-Trade Financial Cost Breakdown */}
							<div className="p-4 rounded-xl bg-slate-950 border border-slate-800/80 space-y-2">
								<div className="flex items-center justify-between text-xs font-mono text-slate-300 font-semibold pb-1.5 border-b border-slate-800/60">
									<span className="flex items-center gap-1.5">
										<Receipt className="h-3.5 w-3.5 text-sky-400" />
										Cómputo Pre-Trade de Comisiones ({currency})
									</span>
									<span className="text-[10px] text-slate-400 uppercase">
										Aranceles BYMA / CNV
									</span>
								</div>

								<div className="space-y-1 text-xs font-mono text-slate-400">
									<div className="flex justify-between">
										<span>
											Subtotal Bruto ({quantity} x{" "}
											{formatMoney(effectivePrice, currency)}):
										</span>
										<span className="text-slate-200 tabular-nums">
											{formatMoney(breakdown.grossAmount, currency)}
										</span>
									</div>
									<div className="flex justify-between">
										<span>Arancel Broker (0.50%):</span>
										<span className="text-slate-300 tabular-nums">
											{formatMoney(breakdown.brokerFee, currency)}
										</span>
									</div>
									<div className="flex justify-between">
										<span>IVA Arancel (21%):</span>
										<span className="text-slate-300 tabular-nums">
											{formatMoney(breakdown.brokerFeeVat, currency)}
										</span>
									</div>
									<div className="flex justify-between">
										<span>Derechos Mercado BYMA / CNV (0.10%):</span>
										<span className="text-slate-300 tabular-nums">
											{formatMoney(breakdown.marketFee, currency)}
										</span>
									</div>

									<div className="flex justify-between pt-1 border-t border-slate-800/80 font-bold text-sm">
										<span className="text-slate-200">
											Total Neto a {side === "BUY" ? "Debitar" : "Acreditar"}:
										</span>
										<span
											className={`tabular-nums ${
												side === "BUY" ? "text-emerald-400" : "text-sky-400"
											}`}
										>
											{formatMoney(breakdown.netTotal, currency)}
										</span>
									</div>
								</div>
							</div>

							{/* Guard Warnings */}
							{hasInsufficientHoldings && (
								<div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/50 flex items-center gap-2 text-xs text-rose-300">
									<AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
									<span>
										Tenencias insuficientes en cartera: posee{" "}
										{currentHoldingShares} títulos de {selectedTicker}.
									</span>
								</div>
							)}

							{hasInsufficientCash && (
								<div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/50 flex items-center gap-2 text-xs text-rose-300">
									<AlertTriangle className="h-4 w-4 shrink-0 text-rose-400" />
									<span>
										Saldo de caja en {currency} insuficiente: dispone de{" "}
										{formatMoney(availableCash, currency)} y la operación
										requiere {formatMoney(breakdown.netTotal, currency)}.
									</span>
								</div>
							)}

							{submitError && (
								<div className="p-3 rounded-xl bg-rose-950/50 border border-rose-800/60 text-xs text-rose-300 flex items-center gap-2">
									<AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
									<span>{submitError}</span>
								</div>
							)}

							{/* Action Buttons */}
							<div className="flex items-center justify-end gap-3 pt-2">
								<button
									type="button"
									onClick={onClose}
									disabled={orderMutation.isPending}
									className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
								>
									Cancelar
								</button>
								<button
									type="submit"
									disabled={
										!canTrade ||
										orderMutation.isPending ||
										hasInsufficientHoldings ||
										hasInsufficientCash
									}
									className={`px-5 py-2.5 rounded-xl text-xs font-semibold shadow-lg transition-all flex items-center gap-2 ${
										!canTrade ||
										orderMutation.isPending ||
										hasInsufficientHoldings ||
										hasInsufficientCash
											? "bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700"
											: side === "BUY"
												? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/20"
												: "bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/20"
									}`}
								>
									{orderMutation.isPending ? (
										<>
											<Loader2 className="h-4 w-4 animate-spin" />
											<span>Enviando Orden a BYMA...</span>
										</>
									) : !canTrade ? (
										<>
											<Lock className="h-4 w-4" />
											<span>Acceso Restringido</span>
										</>
									) : (
										<span>
											Confirmar {side === "BUY" ? "Compra" : "Venta"} (
											{formatMoney(breakdown.netTotal, currency)})
										</span>
									)}
								</button>
							</div>
						</form>
					)}
				</div>
			</div>
		</div>
	);
};
