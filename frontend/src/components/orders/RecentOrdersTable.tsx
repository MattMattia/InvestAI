/**
 * RecentOrdersTable Component for InvestAI Enterprise.
 * High-density chronological order audit table displaying FSM states,
 * operations, traded prices, net settlements, interactive FSM actions
 * (Execute / Settle, Cancel, Forensic Detail Modal), and ART (UTC-3) timestamps.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
	AlertCircle,
	ArrowDownRight,
	ArrowUpRight,
	CheckCircle2,
	Clock,
	Eye,
	Loader2,
	Play,
	Receipt,
	RotateCw,
	X,
	XCircle,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import {
	calculateOrderCostBreakdown,
	formatDate,
	formatMoney,
	inferAssetNativeCurrency,
} from "@/lib/formatters";
import { orderKeys, portfolioKeys } from "@/lib/queryKeys";
import { orderService } from "@/services/orderService";
import type { OrderRecord } from "@/types/api";

interface RecentOrdersTableProps {
	orders: OrderRecord[];
	isLoading?: boolean;
}

const ACTIONABLE_FSM_STATES = new Set([
	"PENDING",
	"CREATED",
	"VALIDATED",
	"ROUTED",
]);

export const RecentOrdersTable: React.FC<RecentOrdersTableProps> = ({
	orders,
	isLoading = false,
}) => {
	const queryClient = useQueryClient();
	const { isAuthenticated, isTrader, isAdmin } = useAuth();
	const canMutateOrders = isAuthenticated && (isTrader || isAdmin);

	const [selectedOrderDetail, setSelectedOrderDetail] =
		useState<OrderRecord | null>(null);
	const [processingOrderId, setProcessingOrderId] = useState<string | null>(
		null,
	);
	const [actionError, setActionError] = useState<string | null>(null);

	const invalidateAllOrderAndPortfolioQueries = (portfolioId?: string) => {
		queryClient.invalidateQueries({ queryKey: orderKeys.all });
		queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
		if (portfolioId) {
			queryClient.invalidateQueries({
				queryKey: portfolioKeys.detail(portfolioId),
			});
		}
	};

	const executeMutation = useMutation({
		mutationFn: async (order: OrderRecord) => {
			setProcessingOrderId(order.id);
			setActionError(null);
			return await orderService.executeOrder(order.id);
		},
		onSuccess: (updated) => {
			setProcessingOrderId(null);
			invalidateAllOrderAndPortfolioQueries(updated.portfolio_id);
			if (selectedOrderDetail && selectedOrderDetail.id === updated.id) {
				setSelectedOrderDetail(updated);
			}
		},
		onError: (err: any) => {
			setProcessingOrderId(null);
			setActionError(
				err?.response?.data?.detail ||
					err?.message ||
					"Error al liquidar la orden en cartera.",
			);
		},
	});

	const cancelMutation = useMutation({
		mutationFn: async (order: OrderRecord) => {
			setProcessingOrderId(order.id);
			setActionError(null);
			return await orderService.cancelOrder(
				order.id,
				"Cancelada manualmente desde el monitor FSM",
			);
		},
		onSuccess: (updated) => {
			setProcessingOrderId(null);
			invalidateAllOrderAndPortfolioQueries(updated.portfolio_id);
			if (selectedOrderDetail && selectedOrderDetail.id === updated.id) {
				setSelectedOrderDetail(updated);
			}
		},
		onError: (err: any) => {
			setProcessingOrderId(null);
			setActionError(
				err?.response?.data?.detail ||
					err?.message ||
					"Error al cancelar la orden.",
			);
		},
	});

	return (
		<div className="w-full rounded-2xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden flex flex-col">
			<div className="px-5 py-4 border-b border-slate-800/80 bg-slate-950/40 flex flex-wrap items-center justify-between gap-2">
				<div className="flex items-center gap-2">
					<Clock className="h-4 w-4 text-sky-400" />
					<h3 className="text-xs font-mono uppercase tracking-wider text-slate-200 font-semibold">
						Registro Histórico de Órdenes FSM (Hora ART / UTC-3)
					</h3>
				</div>
				<span className="text-[11px] font-mono text-slate-400">
					{orders.length} órdenes registradas
				</span>
			</div>

			{actionError && (
				<div className="mx-5 mt-3 p-3 rounded-xl bg-rose-950/40 border border-rose-800/50 text-xs text-rose-300 flex items-center justify-between">
					<span className="flex items-center gap-2">
						<AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
						{actionError}
					</span>
					<button
						type="button"
						onClick={() => setActionError(null)}
						className="text-slate-400 hover:text-white"
					>
						<X className="h-3.5 w-3.5" />
					</button>
				</div>
			)}

			<div className="overflow-x-auto">
				<table className="w-full text-left text-xs border-collapse">
					<thead>
						<tr className="border-b border-slate-800/80 bg-slate-950/60 font-mono uppercase text-[11px] text-slate-400 tracking-wider">
							<th className="py-3 px-4">Fecha / Hora (ART)</th>
							<th className="py-3 px-4">Especie</th>
							<th className="py-3 px-3">Tipo</th>
							<th className="py-3 px-4">Operación</th>
							<th className="py-3 px-4 text-right">Cantidad</th>
							<th className="py-3 px-4 text-right">Precio Ref.</th>
							<th className="py-3 px-4 text-right">Total Neto</th>
							<th className="py-3 px-4 text-center">Estado FSM</th>
							<th className="py-3 px-4 text-right">Acciones</th>
						</tr>
					</thead>
					<tbody className="divide-y divide-slate-800/60 font-mono">
						{isLoading && orders.length === 0 ? (
							<tr>
								<td
									colSpan={9}
									className="py-12 text-center text-slate-400 font-sans"
								>
									<div className="flex items-center justify-center gap-2">
										<span className="h-4 w-4 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
										<span>Cargando órdenes de negociación...</span>
									</div>
								</td>
							</tr>
						) : orders.length === 0 ? (
							<tr>
								<td
									colSpan={9}
									className="py-12 text-center text-slate-400 font-sans"
								>
									No se registran órdenes enviadas al mercado en esta cartera.
								</td>
							</tr>
						) : (
							orders.map((o) => {
								const isBuy = o.side === "BUY";
								const currency = inferAssetNativeCurrency(o.ticker, "ARS");
								const statusStr = String(o.status).toUpperCase();
								const isActionable = ACTIONABLE_FSM_STATES.has(statusStr);
								const isRowBusy = processingOrderId === o.id;

								const statusBadgeStyle =
									(
										{
											EXECUTED:
												"bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
											VALIDATED: "bg-sky-500/15 text-sky-400 border-sky-500/30",
											ROUTED:
												"bg-indigo-500/15 text-indigo-400 border-indigo-500/30",
											PENDING:
												"bg-amber-500/15 text-amber-300 border-amber-500/30",
											CREATED:
												"bg-amber-500/15 text-amber-300 border-amber-500/30",
											CANCELLED: "bg-slate-800 text-slate-400 border-slate-700",
											FAILED: "bg-rose-500/15 text-rose-400 border-rose-500/30",
											REJECTED:
												"bg-rose-500/15 text-rose-400 border-rose-500/30",
										} as Record<string, string>
									)[statusStr] ||
									"bg-slate-800 text-slate-300 border-slate-700";

								return (
									<tr
										key={o.id}
										className="hover:bg-slate-800/40 transition-colors text-slate-300"
									>
										{/* Date / Time in ART (UTC-3) */}
										<td className="py-3 px-4 text-slate-400 tabular-nums whitespace-nowrap">
											{formatDate(o.created_at)}
										</td>

										{/* Ticker */}
										<td className="py-3 px-4 font-bold text-white tracking-tight">
											<div className="flex items-center gap-1.5">
												<span>{o.ticker}</span>
												<span className="text-[9px] px-1 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700">
													{currency}
												</span>
											</div>
										</td>

										{/* Order Type */}
										<td className="py-3 px-3">
											<span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
												{o.order_type}
											</span>
										</td>

										{/* Operation (BUY/SELL) */}
										<td className="py-3 px-4">
											<span
												className={`inline-flex items-center gap-1 font-bold ${
													isBuy ? "text-emerald-400" : "text-rose-400"
												}`}
											>
												{isBuy ? (
													<ArrowUpRight className="h-3.5 w-3.5" />
												) : (
													<ArrowDownRight className="h-3.5 w-3.5" />
												)}
												<span>{isBuy ? "COMPRA" : "VENTA"}</span>
											</span>
										</td>

										{/* Quantity */}
										<td className="py-3 px-4 text-right tabular-nums text-slate-100 font-semibold">
											{o.quantity.toLocaleString("es-AR")}
										</td>

										{/* Price */}
										<td className="py-3 px-4 text-right tabular-nums text-slate-300 whitespace-nowrap">
											{formatMoney(o.price, currency)}
										</td>

										{/* Net Total */}
										<td className="py-3 px-4 text-right tabular-nums font-bold text-white whitespace-nowrap">
											{formatMoney(o.net_amount, currency)}
										</td>

										{/* FSM Status */}
										<td className="py-3 px-4 text-center">
											<span
												className={`text-[10px] font-semibold px-2 py-0.5 rounded border inline-flex items-center gap-1 ${statusBadgeStyle}`}
											>
												{statusStr === "EXECUTED" ? (
													<CheckCircle2 className="h-3 w-3" />
												) : statusStr === "FAILED" ||
													statusStr === "REJECTED" ||
													statusStr === "CANCELLED" ? (
													<AlertCircle className="h-3 w-3" />
												) : (
													<RotateCw className="h-3 w-3" />
												)}
												<span>{statusStr}</span>
											</span>
										</td>

										{/* Interactive FSM Actions */}
										<td className="py-3 px-4 text-right whitespace-nowrap">
											<div className="inline-flex items-center justify-end gap-1.5">
												{isActionable && canMutateOrders && (
													<>
														<button
															type="button"
															disabled={isRowBusy}
															onClick={() => executeMutation.mutate(o)}
															className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-[10px] font-semibold transition-colors disabled:opacity-50"
															title="Ejecutar y liquidar orden en la cartera (actualiza caja y tenencias)"
														>
															{isRowBusy && executeMutation.isPending ? (
																<Loader2 className="h-3 w-3 animate-spin" />
															) : (
																<Play className="h-3 w-3" />
															)}
															<span>Ejecutar</span>
														</button>
														<button
															type="button"
															disabled={isRowBusy}
															onClick={() => cancelMutation.mutate(o)}
															className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 text-[10px] font-semibold transition-colors disabled:opacity-50"
															title="Cancelar orden en la FSM"
														>
															<XCircle className="h-3 w-3" />
															<span>Cancelar</span>
														</button>
													</>
												)}

												<button
													type="button"
													onClick={() => setSelectedOrderDetail(o)}
													className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 text-[10px] font-medium transition-colors"
													title="Ver comprobante y desglose de aranceles BYMA/CNV"
												>
													<Eye className="h-3 w-3 text-sky-400" />
													<span>Detalle</span>
												</button>
											</div>
										</td>
									</tr>
								);
							})
						)}
					</tbody>
				</table>
			</div>

			{/* Forensic Order Detail Modal */}
			{selectedOrderDetail && (
				<div
					role="dialog"
					aria-modal="true"
					className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-150"
				>
					{(() => {
						const ord = selectedOrderDetail;
						const cur = inferAssetNativeCurrency(ord.ticker, "ARS");
						const detailBreakdown = calculateOrderCostBreakdown({
							quantity: ord.quantity,
							price: ord.price,
							side: ord.side,
						});
						const isActionable = ACTIONABLE_FSM_STATES.has(ord.status);

						return (
							<div className="w-full max-w-md rounded-2xl bg-slate-900 border border-slate-800 shadow-2xl overflow-hidden">
								<div className="px-5 py-4 border-b border-slate-800 bg-slate-950/50 flex items-center justify-between">
									<div className="flex items-center gap-2">
										<Receipt className="h-4 w-4 text-sky-400" />
										<h4 className="text-sm font-bold text-white font-mono">
											Comprobante de Orden • {ord.ticker}
										</h4>
									</div>
									<button
										type="button"
										onClick={() => setSelectedOrderDetail(null)}
										className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
									>
										<X className="h-4 w-4" />
									</button>
								</div>

								<div className="p-5 space-y-4 font-mono text-xs">
									<div className="grid grid-cols-2 gap-2 p-3 rounded-xl bg-slate-950 border border-slate-800/80">
										<div>
											<span className="text-[10px] text-slate-400 block">
												ID Orden
											</span>
											<span className="text-slate-200 font-semibold">
												{ord.id.slice(0, 12)}
											</span>
										</div>
										<div>
											<span className="text-[10px] text-slate-400 block">
												Fecha / Hora (ART)
											</span>
											<span className="text-slate-200">
												{formatDate(ord.created_at)}
											</span>
										</div>
										<div>
											<span className="text-[10px] text-slate-400 block">
												Operación
											</span>
											<span
												className={`font-bold ${
													ord.side === "BUY"
														? "text-emerald-400"
														: "text-rose-400"
												}`}
											>
												{ord.side === "BUY" ? "COMPRA" : "VENTA"} (
												{ord.quantity} nominales)
											</span>
										</div>
										<div>
											<span className="text-[10px] text-slate-400 block">
												Estado FSM
											</span>
											<span className="text-sky-400 font-bold">
												{ord.status}
											</span>
										</div>
									</div>

									{/* Breakdown */}
									<div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800/80 space-y-1.5">
										<div className="flex justify-between text-slate-400">
											<span>Precio Unitario ({cur}):</span>
											<span className="text-slate-200">
												{formatMoney(ord.price, cur)}
											</span>
										</div>
										<div className="flex justify-between text-slate-400">
											<span>Monto Bruto:</span>
											<span className="text-slate-200">
												{formatMoney(detailBreakdown.grossAmount, cur)}
											</span>
										</div>
										<div className="flex justify-between text-slate-400">
											<span>Comisión Broker (0.50%):</span>
											<span className="text-slate-300">
												{formatMoney(detailBreakdown.brokerFee, cur)}
											</span>
										</div>
										<div className="flex justify-between text-slate-400">
											<span>IVA s/ Comisión (21%):</span>
											<span className="text-slate-300">
												{formatMoney(detailBreakdown.brokerFeeVat, cur)}
											</span>
										</div>
										<div className="flex justify-between text-slate-400">
											<span>Derechos BYMA / CNV (0.10%):</span>
											<span className="text-slate-300">
												{formatMoney(detailBreakdown.marketFee, cur)}
											</span>
										</div>
										<div className="flex justify-between pt-2 border-t border-slate-800 font-bold text-sm">
											<span className="text-slate-200">
												Total Neto ({cur}):
											</span>
											<span className="text-emerald-400">
												{formatMoney(detailBreakdown.netTotal, cur)}
											</span>
										</div>
									</div>

									{ord.justification && (
										<div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 text-[11px] font-sans text-slate-300">
											<span className="text-slate-400 font-semibold block mb-0.5">
												Justificación / Auditoría:
											</span>
											{ord.justification}
										</div>
									)}

									<div className="flex items-center justify-end gap-2 pt-1">
										{isActionable && canMutateOrders && (
											<>
												<button
													type="button"
													onClick={() => executeMutation.mutate(ord)}
													disabled={processingOrderId === ord.id}
													className="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5"
												>
													<Play className="h-3.5 w-3.5" />
													<span>Ejecutar y Liquidar</span>
												</button>
												<button
													type="button"
													onClick={() => cancelMutation.mutate(ord)}
													disabled={processingOrderId === ord.id}
													className="px-3 py-2 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 text-xs font-semibold flex items-center gap-1.5"
												>
													<XCircle className="h-3.5 w-3.5" />
													<span>Cancelar Orden</span>
												</button>
											</>
										)}
										<button
											type="button"
											onClick={() => setSelectedOrderDetail(null)}
											className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium"
										>
											Cerrar
										</button>
									</div>
								</div>
							</div>
						);
					})()}
				</div>
			)}
		</div>
	);
};
