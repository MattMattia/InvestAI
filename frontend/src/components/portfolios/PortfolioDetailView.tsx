/**
 * Comprehensive Portfolio Detail View Component for InvestAI Enterprise.
 * Orchestrates PortfolioKPIHeader, Detail Navigation Tabs (Holdings, Rebalance, Audit),
 * AssetAllocationDonut, HoldingsTable, RebalancePanel, and full Portfolio CRUD
 * (Bimonetary Cash Treasury Deposit/Withdrawal, Metadata/Profile Edit, and Safe Deletion).
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
	AlertCircle,
	ArrowLeft,
	CheckCircle2,
	Coins,
	DollarSign,
	Loader2,
	PieChart,
	RefreshCw,
	Scale,
	Settings,
	Shield,
	Trash2,
	Wallet,
	X,
} from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { OrderExecutionModal } from "@/components/orders/OrderExecutionModal";
import { RecentOrdersTable } from "@/components/orders/RecentOrdersTable";
import { useAuth } from "@/hooks/useAuth";
import { usePortfolio } from "@/hooks/usePortfolios";
import { formatMoney, parseDecimalSafe } from "@/lib/formatters";
import { navigateToPortfoliosList, useHashRoute } from "@/lib/navigation";
import { orderKeys, portfolioKeys } from "@/lib/queryKeys";
import { orderService } from "@/services/orderService";
import { portfolioService } from "@/services/portfolioService";
import type { InvestorProfile } from "@/types/api";
import { AssetAllocationDonut } from "./AssetAllocationDonut";
import { AuditCompliancePanel } from "./AuditCompliancePanel";
import { HoldingsTable } from "./HoldingsTable";
import { PortfolioKPIHeader } from "./PortfolioKPIHeader";
import { RebalancePanel } from "./RebalancePanel";

interface PortfolioDetailViewProps {
	portfolioId: string;
}

export const PortfolioDetailView: React.FC<PortfolioDetailViewProps> = ({
	portfolioId,
}) => {
	const { tab, navigateToPortfolioTab } = useHashRoute();
	const queryClient = useQueryClient();
	const { isAuthenticated, isTrader, isAdmin } = useAuth();
	const canManage = isAuthenticated && (isTrader || isAdmin);

	const [isOrderModalOpen, setIsOrderModalOpen] = useState<boolean>(false);
	const [managementMode, setManagementMode] = useState<
		"cash" | "settings" | null
	>(null);

	// Treasury & Settings Form State
	const [cashAction, setCashAction] = useState<"DEPOSIT" | "WITHDRAW">(
		"DEPOSIT",
	);
	const [cashCurrency, setCashCurrency] = useState<"ARS" | "USD">("ARS");
	const [cashAmount, setCashAmount] = useState<number>(1000000);
	const [editName, setEditName] = useState<string>("");
	const [editProfile, setEditProfile] = useState<InvestorProfile>("MODERATE");
	const [confirmDelete, setConfirmDelete] = useState<boolean>(false);
	const [isSavingManagement, setIsSavingManagement] = useState<boolean>(false);
	const [managementError, setManagementError] = useState<string | null>(null);
	const [managementSuccess, setManagementSuccess] = useState<string | null>(
		null,
	);

	const {
		data: portfolio,
		isLoading,
		isError,
		error,
		refetch,
		isFetching,
	} = usePortfolio(portfolioId);

	const { data: recentOrders = [], isLoading: isLoadingOrders } = useQuery({
		queryKey: orderKeys.list(portfolioId),
		queryFn: () => orderService.getRecentOrders(portfolioId),
		enabled: Boolean(portfolioId),
		staleTime: 15_000,
	});

	useEffect(() => {
		if (portfolio && managementMode) {
			setEditName(portfolio.name);
			setEditProfile(
				(
					portfolio.investor_profile || "MODERATE"
				).toUpperCase() as InvestorProfile,
			);
			setConfirmDelete(false);
			setManagementError(null);
			setManagementSuccess(null);
		}
	}, [portfolio, managementMode]);

	const handleApplyCashMovement = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!portfolio || !canManage || isSavingManagement) return;
		if (cashAmount <= 0) {
			setManagementError("El monto debe ser estrictamente positivo.");
			return;
		}

		const currentArs = parseDecimalSafe(portfolio.cash_balance_ars);
		const currentUsd = parseDecimalSafe(portfolio.cash_balance_usd);
		const delta = cashAction === "DEPOSIT" ? cashAmount : -cashAmount;

		const nextArs =
			cashCurrency === "ARS" ? Math.max(0, currentArs + delta) : currentArs;
		const nextUsd =
			cashCurrency === "USD" ? Math.max(0, currentUsd + delta) : currentUsd;

		if (cashAction === "WITHDRAW") {
			if (cashCurrency === "ARS" && cashAmount > currentArs) {
				setManagementError("Fondos insuficientes en Caja ARS para ese retiro.");
				return;
			}
			if (cashCurrency === "USD" && cashAmount > currentUsd) {
				setManagementError("Fondos insuficientes en Caja USD para ese retiro.");
				return;
			}
		}

		setIsSavingManagement(true);
		setManagementError(null);
		try {
			await portfolioService.updatePortfolio(portfolio.id, {
				cash_balance_ars: Number(nextArs.toFixed(2)),
				cash_balance_usd: Number(nextUsd.toFixed(2)),
			});
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() }),
				queryClient.invalidateQueries({
					queryKey: portfolioKeys.detail(portfolio.id),
				}),
			]);
			setManagementSuccess(
				`${
					cashAction === "DEPOSIT" ? "Depósito" : "Retiro"
				} de ${formatMoney(cashAmount, cashCurrency)} acreditado exitosamente.`,
			);
		} catch (err: any) {
			setManagementError(
				err?.response?.data?.detail ||
					err?.message ||
					"Error al actualizar el saldo de caja.",
			);
		} finally {
			setIsSavingManagement(false);
		}
	};

	const handleSaveSettings = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!portfolio || !canManage || isSavingManagement) return;
		if (!editName.trim() || editName.trim().length < 3) {
			setManagementError(
				"El nombre de la cartera debe contener al menos 3 caracteres.",
			);
			return;
		}

		setIsSavingManagement(true);
		setManagementError(null);
		try {
			await portfolioService.updatePortfolio(portfolio.id, {
				name: editName.trim(),
				investor_profile: editProfile,
			});
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() }),
				queryClient.invalidateQueries({
					queryKey: portfolioKeys.detail(portfolio.id),
				}),
			]);
			setManagementSuccess("Parámetros de la cartera actualizados.");
		} catch (err: any) {
			setManagementError(
				err?.response?.data?.detail ||
					err?.message ||
					"Error al actualizar la configuración de la cartera.",
			);
		} finally {
			setIsSavingManagement(false);
		}
	};

	const handleDeletePortfolio = async () => {
		if (!portfolio || !canManage || isSavingManagement) return;
		setIsSavingManagement(true);
		setManagementError(null);
		try {
			await portfolioService.deletePortfolio(portfolio.id);
			await queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
			setManagementMode(null);
			navigateToPortfoliosList();
		} catch (err: any) {
			setManagementError(
				err?.response?.data?.detail ||
					err?.message ||
					"Error al eliminar el portafolio.",
			);
			setIsSavingManagement(false);
		}
	};

	if (isLoading) {
		return (
			<div className="space-y-6 animate-pulse">
				{/* Header Skeleton */}
				<div className="h-28 rounded-xl bg-slate-900/60 border border-slate-800 p-6 flex flex-col justify-between">
					<div className="h-6 w-1/3 bg-slate-800 rounded" />
					<div className="grid grid-cols-6 gap-3">
						{[1, 2, 3, 4, 5, 6].map((i) => (
							<div key={i} className="h-12 bg-slate-800/60 rounded" />
						))}
					</div>
				</div>

				{/* Tab skeleton */}
				<div className="h-10 w-64 bg-slate-800/40 rounded" />

				{/* Donut Skeleton */}
				<div className="h-64 rounded-xl bg-slate-900/60 border border-slate-800 p-6 flex items-center justify-center">
					<div className="h-44 w-44 rounded-full border-8 border-slate-800 flex items-center justify-center text-xs text-slate-500 font-mono">
						Cargando portafolio...
					</div>
				</div>
			</div>
		);
	}

	if (isError || !portfolio) {
		return (
			<div className="p-10 rounded-xl bg-slate-900 border border-rose-800/40 text-center space-y-4">
				<AlertCircle className="h-10 w-10 text-rose-400 mx-auto" />
				<h2 className="text-base font-semibold text-rose-200">
					No se pudo cargar la información del portafolio
				</h2>
				<p className="text-xs text-slate-400 max-w-md mx-auto">
					{error?.message ||
						"Es posible que el portafolio no exista o no dispongas de permisos para acceder a esta cartera."}
				</p>

				<div className="flex items-center justify-center gap-3 pt-2">
					<button
						type="button"
						onClick={() => navigateToPortfoliosList()}
						className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 font-medium transition-colors"
					>
						<ArrowLeft className="h-4 w-4" />
						<span>Volver a Portafolios</span>
					</button>
					<button
						type="button"
						onClick={() => refetch()}
						disabled={isFetching}
						className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs text-white font-medium transition-colors"
					>
						<RefreshCw
							className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
						/>
						<span>Reintentar</span>
					</button>
				</div>
			</div>
		);
	}

	return (
		<div className="space-y-6">
			{/* Analytic KPI Header */}
			<PortfolioKPIHeader
				portfolio={portfolio}
				onNewOrder={() => setIsOrderModalOpen(true)}
				onManageCash={() => setManagementMode("cash")}
				onEditPortfolio={() => setManagementMode("settings")}
			/>

			{/* Detail Navigation Tabs */}
			<div className="flex border-b border-slate-800 gap-2">
				<button
					type="button"
					onClick={() => navigateToPortfolioTab(portfolioId, "holdings")}
					className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-medium border-b-2 transition-colors ${
						tab === "holdings"
							? "border-sky-500 text-sky-400 bg-slate-900/40"
							: "border-transparent text-slate-400 hover:text-slate-200"
					}`}
				>
					<PieChart className="h-4 w-4" />
					<span>Tenencias y Asignación</span>
				</button>

				<button
					type="button"
					onClick={() => navigateToPortfolioTab(portfolioId, "rebalance")}
					className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-medium border-b-2 transition-colors ${
						tab === "rebalance"
							? "border-sky-500 text-sky-400 bg-slate-900/40"
							: "border-transparent text-slate-400 hover:text-slate-200"
					}`}
				>
					<Scale className="h-4 w-4" />
					<span>Rebalanceo y Bandas FSM</span>
				</button>

				<button
					type="button"
					onClick={() => navigateToPortfolioTab(portfolioId, "audit")}
					className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-medium border-b-2 transition-colors ${
						tab === "audit"
							? "border-sky-500 text-sky-400 bg-slate-900/40"
							: "border-transparent text-slate-400 hover:text-slate-200"
					}`}
				>
					<Shield className="h-4 w-4" />
					<span>Auditoría y Snapshots</span>
				</button>
			</div>

			{/* Tab 1: Holdings & Donut */}
			{tab === "holdings" && (
				<div className="space-y-6">
					<AssetAllocationDonut portfolio={portfolio} initialCurrency="ARS" />
					<HoldingsTable portfolio={portfolio} />
				</div>
			)}

			{/* Tab 2: Tolerance Bands & FSM Orders */}
			{tab === "rebalance" && (
				<div className="space-y-6">
					<RebalancePanel portfolio={portfolio} />
					<RecentOrdersTable
						orders={recentOrders}
						isLoading={isLoadingOrders}
					/>
				</div>
			)}

			{/* Tab 3: Risk Audit Compliance & Snapshots */}
			{tab === "audit" && <AuditCompliancePanel portfolio={portfolio} />}

			{/* Manual Assisted Order Execution Modal */}
			{isOrderModalOpen && (
				<OrderExecutionModal
					isOpen={isOrderModalOpen}
					onClose={() => setIsOrderModalOpen(false)}
					initialPortfolioId={portfolio.id}
					initialCurrency="ARS"
				/>
			)}

			{/* Portfolio Management Modal (Treasury Cash & Settings / Delete) */}
			{managementMode && (
				<div
					role="dialog"
					aria-modal="true"
					className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-150"
				>
					<div className="relative w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-800 shadow-2xl overflow-hidden">
						{/* Modal Header */}
						<div className="px-6 py-4 border-b border-slate-800 bg-slate-950/50 flex items-center justify-between">
							<div className="flex items-center gap-2.5">
								{managementMode === "cash" ? (
									<Wallet className="h-5 w-5 text-emerald-400" />
								) : (
									<Settings className="h-5 w-5 text-sky-400" />
								)}
								<div>
									<h3 className="text-sm font-bold text-white">
										{managementMode === "cash"
											? "Tesorería Bimonetaria y Liquidez"
											: "Ajustes y Administración de Cartera"}
									</h3>
									<p className="text-[11px] font-mono text-slate-400">
										{portfolio.name}
									</p>
								</div>
							</div>
							<button
								type="button"
								onClick={() => setManagementMode(null)}
								className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
							>
								<X className="h-4 w-4" />
							</button>
						</div>

						{/* Mode Switch Tabs */}
						<div className="grid grid-cols-2 border-b border-slate-800 bg-slate-950/30 text-xs font-mono">
							<button
								type="button"
								onClick={() => {
									setManagementMode("cash");
									setManagementError(null);
									setManagementSuccess(null);
								}}
								className={`py-2.5 font-semibold border-b-2 transition-colors ${
									managementMode === "cash"
										? "border-emerald-500 text-emerald-400 bg-emerald-500/5"
										: "border-transparent text-slate-400 hover:text-slate-200"
								}`}
							>
								Depositar / Retirar Caja
							</button>
							<button
								type="button"
								onClick={() => {
									setManagementMode("settings");
									setManagementError(null);
									setManagementSuccess(null);
								}}
								className={`py-2.5 font-semibold border-b-2 transition-colors ${
									managementMode === "settings"
										? "border-sky-500 text-sky-400 bg-sky-500/5"
										: "border-transparent text-slate-400 hover:text-slate-200"
								}`}
							>
								Editar / Eliminar Cartera
							</button>
						</div>

						<div className="p-6 space-y-4">
							{managementError && (
								<div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/50 text-xs text-rose-300 flex items-center gap-2">
									<AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
									<span>{managementError}</span>
								</div>
							)}

							{managementSuccess && (
								<div className="p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/50 text-xs text-emerald-300 flex items-center gap-2">
									<CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
									<span>{managementSuccess}</span>
								</div>
							)}

							{managementMode === "cash" ? (
								<form onSubmit={handleApplyCashMovement} className="space-y-4">
									{/* Current Balances Summary */}
									<div className="grid grid-cols-2 gap-3 p-3 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs">
										<div>
											<span className="text-[10px] text-slate-400 block">
												Saldo Actual ARS
											</span>
											<span className="text-emerald-400 font-bold">
												{formatMoney(portfolio.cash_balance_ars, "ARS")}
											</span>
										</div>
										<div>
											<span className="text-[10px] text-slate-400 block">
												Saldo Actual USD
											</span>
											<span className="text-sky-400 font-bold">
												{formatMoney(portfolio.cash_balance_usd, "USD")}
											</span>
										</div>
									</div>

									{/* Action & Currency Selectors */}
									<div className="grid grid-cols-2 gap-3">
										<div className="grid grid-cols-2 gap-1.5 p-1 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs">
											<button
												type="button"
												onClick={() => setCashAction("DEPOSIT")}
												className={`py-1.5 rounded-lg font-bold transition-colors ${
													cashAction === "DEPOSIT"
														? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
														: "text-slate-400"
												}`}
											>
												+ Depositar
											</button>
											<button
												type="button"
												onClick={() => setCashAction("WITHDRAW")}
												className={`py-1.5 rounded-lg font-bold transition-colors ${
													cashAction === "WITHDRAW"
														? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
														: "text-slate-400"
												}`}
											>
												- Retirar
											</button>
										</div>

										<div className="grid grid-cols-2 gap-1.5 p-1 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs">
											<button
												type="button"
												onClick={() => {
													setCashCurrency("ARS");
													setCashAmount(1000000);
												}}
												className={`py-1.5 rounded-lg font-bold flex items-center justify-center gap-1 transition-colors ${
													cashCurrency === "ARS"
														? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
														: "text-slate-400"
												}`}
											>
												<Coins className="h-3 w-3" />
												<span>ARS</span>
											</button>
											<button
												type="button"
												onClick={() => {
													setCashCurrency("USD");
													setCashAmount(5000);
												}}
												className={`py-1.5 rounded-lg font-bold flex items-center justify-center gap-1 transition-colors ${
													cashCurrency === "USD"
														? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
														: "text-slate-400"
												}`}
											>
												<DollarSign className="h-3 w-3" />
												<span>USD</span>
											</button>
										</div>
									</div>

									{/* Amount Input & Quick Presets */}
									<div className="space-y-2">
										<label className="text-xs font-mono text-slate-300 block">
											Monto a{" "}
											{cashAction === "DEPOSIT" ? "Depositar" : "Retirar"} (
											{cashCurrency}):
										</label>
										<input
											type="number"
											min="1"
											step="any"
											value={cashAmount}
											onChange={(e) =>
												setCashAmount(
													Math.max(0, parseFloat(e.target.value) || 0),
												)
											}
											className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-sm font-mono text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
										/>

										<div className="flex flex-wrap gap-1.5 pt-1">
											{(cashCurrency === "ARS"
												? [500000, 1000000, 5000000, 10000000]
												: [1000, 5000, 10000, 25000]
											).map((preset) => (
												<button
													key={preset}
													type="button"
													onClick={() => setCashAmount(preset)}
													className="px-2.5 py-1 rounded-lg bg-slate-950 hover:bg-slate-800 text-[11px] font-mono text-slate-300 border border-slate-800 transition-colors"
												>
													{formatMoney(preset, cashCurrency)}
												</button>
											))}
										</div>
									</div>

									<div className="flex justify-end gap-2 pt-2">
										<button
											type="button"
											onClick={() => setManagementMode(null)}
											className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-medium"
										>
											Cerrar
										</button>
										<button
											type="submit"
											disabled={!canManage || isSavingManagement}
											className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
										>
											{isSavingManagement && (
												<Loader2 className="h-3.5 w-3.5 animate-spin" />
											)}
											<span>Aplicar Movimiento en Caja</span>
										</button>
									</div>
								</form>
							) : (
								<div className="space-y-5">
									<form onSubmit={handleSaveSettings} className="space-y-3.5">
										<div className="space-y-1">
											<label className="text-xs font-mono text-slate-300 block">
												Nombre de la Cartera:
											</label>
											<input
												type="text"
												value={editName}
												onChange={(e) => setEditName(e.target.value)}
												className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
											/>
										</div>

										<div className="space-y-1">
											<label className="text-xs font-mono text-slate-300 block">
												Perfil de Riesgo Institucional:
											</label>
											<select
												value={editProfile}
												onChange={(e) =>
													setEditProfile(e.target.value as InvestorProfile)
												}
												className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-xs font-mono text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
											>
												<option value="CONSERVATIVE">
													CONSERVATIVE (Preservación y Renta Fija)
												</option>
												<option value="MODERATE">
													MODERATE (Balanceado / Crecimiento Moderado)
												</option>
												<option value="AGGRESSIVE">
													AGGRESSIVE (Renta Variable / Alto Retorno)
												</option>
											</select>
										</div>

										<div className="flex justify-end pt-1">
											<button
												type="submit"
												disabled={!canManage || isSavingManagement}
												className="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
											>
												{isSavingManagement && (
													<Loader2 className="h-3.5 w-3.5 animate-spin" />
												)}
												<span>Guardar Cambios</span>
											</button>
										</div>
									</form>

									{/* Danger Zone: Delete Portfolio */}
									<div className="pt-4 border-t border-slate-800 space-y-2.5">
										<span className="text-[11px] font-mono uppercase text-rose-400 font-semibold block">
											Zona de Baja de Cartera
										</span>
										{!confirmDelete ? (
											<button
												type="button"
												disabled={!canManage || isSavingManagement}
												onClick={() => setConfirmDelete(true)}
												className="w-full py-2 px-3 rounded-xl bg-rose-950/30 hover:bg-rose-950/50 text-rose-300 border border-rose-800/50 text-xs font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
											>
												<Trash2 className="h-3.5 w-3.5" />
												<span>Eliminar Portafolio Permanentemente</span>
											</button>
										) : (
											<div className="p-3 rounded-xl bg-rose-950/40 border border-rose-500/40 space-y-2.5">
												<p className="text-xs text-rose-200">
													¿Confirmas eliminar el portafolio{" "}
													<strong>{portfolio.name}</strong> y todas sus
													tenencias?
												</p>
												<div className="flex items-center justify-end gap-2">
													<button
														type="button"
														onClick={() => setConfirmDelete(false)}
														className="px-3 py-1.5 rounded-lg bg-slate-800 text-xs text-slate-300"
													>
														Cancelar
													</button>
													<button
														type="button"
														onClick={handleDeletePortfolio}
														disabled={isSavingManagement}
														className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-xs text-white font-semibold flex items-center gap-1"
													>
														<Trash2 className="h-3.5 w-3.5" />
														<span>Sí, Eliminar Definitivamente</span>
													</button>
												</div>
											</div>
										)}
									</div>
								</div>
							)}
						</div>
					</div>
				</div>
			)}
		</div>
	);
};
