/**
 * Audit & Risk Compliance Panel for InvestAI Enterprise Portfolio Management.
 * Features live execution of the RiskEngine, compliance KPIs, immutable snapshot history,
 * and forensic payload drill-downs.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
	AlertCircle,
	Camera,
	CheckCircle2,
	Clock,
	Lock,
	RefreshCw,
	Shield,
	ShieldAlert,
	ShieldCheck,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { formatDate } from "@/lib/formatters";
import { snapshotKeys } from "@/lib/queryKeys";
import { portfolioService } from "@/services/portfolioService";
import type { Portfolio, RiskAuditSnapshot } from "@/types/api";
import { SnapshotDetailModal } from "./SnapshotDetailModal";
import { SnapshotHistoryTable } from "./SnapshotHistoryTable";

interface AuditCompliancePanelProps {
	portfolio: Portfolio;
}

export const AuditCompliancePanel: React.FC<AuditCompliancePanelProps> = ({
	portfolio,
}) => {
	const queryClient = useQueryClient();
	const { isAuthenticated, isTrader, isAdmin, isViewer } = useAuth();
	const canCapture = isAuthenticated && (isTrader || isAdmin);

	const [selectedSnapshot, setSelectedSnapshot] =
		useState<RiskAuditSnapshot | null>(null);
	const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
	const [auditError, setAuditError] = useState<string | null>(null);

	// Query snapshots list
	const {
		data: snapshots = [],
		isLoading,
		refetch,
		isFetching,
	} = useQuery({
		queryKey: snapshotKeys.byPortfolio(portfolio.id),
		queryFn: () => portfolioService.getPortfolioSnapshots(portfolio.id),
		enabled: isAuthenticated && Boolean(portfolio.id),
		staleTime: 30_000,
	});

	// Mutation to trigger live risk evaluation and persist snapshot
	const auditMutation = useMutation({
		mutationFn: () => portfolioService.triggerAuditSnapshot(portfolio.id),
		onSuccess: (newSnapshot) => {
			setAuditError(null);
			queryClient.invalidateQueries({
				queryKey: snapshotKeys.byPortfolio(portfolio.id),
			});
			setSelectedSnapshot(newSnapshot);
			setIsModalOpen(true);
		},
		onError: (err: unknown) => {
			setAuditError(
				err instanceof Error
					? err.message
					: "Error al evaluar el riesgo del portafolio.",
			);
		},
	});

	const latestSnapshot = snapshots.length > 0 ? snapshots[0] : null;
	const isLatestOk = latestSnapshot?.compliance_status === "COMPLIANCE_OK";
	const latestAlerts = latestSnapshot?.critical_alerts_count || 0;

	const handleViewSnapshot = (snapshot: RiskAuditSnapshot) => {
		setSelectedSnapshot(snapshot);
		setIsModalOpen(true);
	};

	return (
		<div className="space-y-6">
			{/* Top Compliance Executive Summary */}
			<div className="p-6 rounded-xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
				<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
					<div>
						<h2 className="text-base font-semibold text-white flex items-center gap-2">
							<Shield className="h-5 w-5 text-sky-400" />
							Auditoría Normativa y Control de Riesgos Deterministas
						</h2>
						<p className="text-xs text-slate-400 mt-0.5">
							Supervisión de concentración de activos, sesgo sectorial, desvíos
							de tipo de cambio implícito y valuación anómala
						</p>
					</div>

					<div className="flex items-center gap-3">
						<button
							type="button"
							onClick={() => refetch()}
							disabled={isFetching || !isAuthenticated}
							className="p-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-40"
							title="Refrescar snapshots"
						>
							<RefreshCw
								className={`h-4 w-4 ${isFetching ? "animate-spin text-sky-400" : ""}`}
							/>
						</button>

						{canCapture ? (
							<button
								type="button"
								onClick={() => auditMutation.mutate()}
								disabled={auditMutation.isPending}
								className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-md shadow-sky-600/30 transition-all active:scale-95 disabled:opacity-50"
							>
								{auditMutation.isPending ? (
									<>
										<RefreshCw className="h-4 w-4 animate-spin" />
										<span>Evaluando Reglas...</span>
									</>
								) : (
									<>
										<Camera className="h-4 w-4" />
										<span>Capturar Snapshot de Auditoría</span>
									</>
								)}
							</button>
						) : isAuthenticated && isViewer ? (
							<div
								className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-slate-800 text-slate-400 text-xs cursor-not-allowed border border-slate-700"
								title="El rol VIEWER no tiene autorización para emitir auditorías activas"
							>
								<Lock className="h-3.5 w-3.5 text-amber-400" />
								<span>Auditoría Bloqueada (Rol VIEWER)</span>
							</div>
						) : (
							<div className="flex items-center gap-1.5 text-xs text-slate-400 font-mono">
								<Lock className="h-3.5 w-3.5" />
								<span>Inicia sesión para auditar</span>
							</div>
						)}
					</div>
				</div>

				{/* Executive KPI Cards */}
				<div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
					<div className="p-4 rounded-lg bg-slate-950/70 border border-slate-800 flex items-center justify-between">
						<div>
							<span className="text-[10px] uppercase font-mono text-slate-400 block">
								Estado Normativo Actual
							</span>
							<div className="flex items-center gap-2 mt-1">
								{latestSnapshot ? (
									<>
										{isLatestOk ? (
											<span className="inline-flex items-center gap-1 text-emerald-400 font-bold font-mono text-sm">
												<CheckCircle2 className="h-4 w-4" />
												COMPLIANCE_OK
											</span>
										) : (
											<span className="inline-flex items-center gap-1 text-rose-400 font-bold font-mono text-sm">
												<AlertCircle className="h-4 w-4" />
												BREACH_DETECTED
											</span>
										)}
									</>
								) : (
									<span className="text-slate-400 text-sm font-mono">
										Sin evaluaciones
									</span>
								)}
							</div>
						</div>

						<div
							className={`p-2.5 rounded-lg border ${
								isLatestOk
									? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
									: "bg-slate-800 text-slate-400 border-slate-700"
							}`}
						>
							<ShieldCheck className="h-5 w-5" />
						</div>
					</div>

					<div className="p-4 rounded-lg bg-slate-950/70 border border-slate-800 flex items-center justify-between">
						<div>
							<span className="text-[10px] uppercase font-mono text-slate-400 block">
								Última Auditoría Forense
							</span>
							<span className="text-sm font-bold font-mono text-white mt-1 block">
								{latestSnapshot
									? formatDate(latestSnapshot.created_at)
									: "Nunca"}
							</span>
						</div>

						<div className="p-2.5 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/30">
							<Clock className="h-5 w-5" />
						</div>
					</div>

					<div className="p-4 rounded-lg bg-slate-950/70 border border-slate-800 flex items-center justify-between">
						<div>
							<span className="text-[10px] uppercase font-mono text-slate-400 block">
								Alertas Críticas Activas
							</span>
							<span
								className={`text-sm font-bold font-mono mt-1 block ${
									latestAlerts > 0
										? "text-rose-400 font-bold"
										: "text-slate-300"
								}`}
							>
								{latestAlerts} {latestAlerts === 1 ? "alerta" : "alertas"}
							</span>
						</div>

						<div
							className={`p-2.5 rounded-lg border ${
								latestAlerts > 0
									? "bg-rose-500/10 text-rose-400 border-rose-500/30"
									: "bg-slate-800 text-slate-400 border-slate-700"
							}`}
						>
							<ShieldAlert className="h-5 w-5" />
						</div>
					</div>
				</div>
			</div>

			{/* Error Message */}
			{auditError && (
				<div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-3">
					<AlertCircle className="h-5 w-5 shrink-0 text-rose-400" />
					<span>{auditError}</span>
				</div>
			)}

			{/* Snapshot History Table */}
			<SnapshotHistoryTable
				snapshots={snapshots}
				isLoading={isLoading}
				onViewSnapshot={handleViewSnapshot}
			/>

			{/* Forensic Inspection Modal */}
			<SnapshotDetailModal
				snapshot={selectedSnapshot}
				isOpen={isModalOpen}
				onClose={() => {
					setIsModalOpen(false);
					setSelectedSnapshot(null);
				}}
			/>
		</div>
	);
};
