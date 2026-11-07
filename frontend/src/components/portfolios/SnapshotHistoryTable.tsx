/**
 * Snapshot History Table Component for InvestAI Enterprise.
 * Displays chronological audit snapshots, compliance status badges,
 * critical alert tallies, and action triggers for forensic payload inspection.
 */

import { Clock, Eye, History, ShieldAlert, ShieldCheck } from "lucide-react";
import type React from "react";
import { formatDate } from "@/lib/formatters";
import type { RiskAuditSnapshot } from "@/types/api";

interface SnapshotHistoryTableProps {
	snapshots: RiskAuditSnapshot[];
	isLoading: boolean;
	onViewSnapshot: (snapshot: RiskAuditSnapshot) => void;
}

export const SnapshotHistoryTable: React.FC<SnapshotHistoryTableProps> = ({
	snapshots,
	isLoading,
	onViewSnapshot,
}) => {
	if (isLoading) {
		return (
			<div className="rounded-xl bg-slate-900 border border-slate-800 p-6 space-y-3 animate-pulse">
				<div className="h-5 w-48 bg-slate-800 rounded mb-4" />
				{[1, 2, 3].map((i) => (
					<div key={i} className="h-12 bg-slate-800/40 rounded w-full" />
				))}
			</div>
		);
	}

	if (snapshots.length === 0) {
		return (
			<div className="rounded-xl bg-slate-900 border border-slate-800 p-8 text-center space-y-3">
				<div className="h-10 w-10 rounded-full bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
					<History className="h-5 w-5" />
				</div>
				<h4 className="text-sm font-semibold text-slate-100">
					Sin Snapshots de Auditoría
				</h4>
				<p className="text-xs text-slate-400 max-w-md mx-auto">
					Aún no se han generado auditorías forenses para esta cartera. Haz clic
					en "Capturar Snapshot de Auditoría" para evaluar las reglas
					cuantitativas de riesgo en vivo.
				</p>
			</div>
		);
	}

	return (
		<div className="rounded-xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden">
			{/* Table Header */}
			<div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
				<div className="flex items-center gap-2">
					<History className="h-4 w-4 text-sky-400" />
					<h3 className="font-semibold text-sm text-slate-100">
						Historial de Snapshots Inmutables
					</h3>
				</div>
				<span className="text-xs font-mono text-slate-400">
					{snapshots.length}{" "}
					{snapshots.length === 1 ? "registro forense" : "registros forenses"}
				</span>
			</div>

			{/* Table */}
			<div className="overflow-x-auto">
				<table className="w-full text-left text-xs border-collapse">
					<thead>
						<tr className="border-b border-slate-800 bg-slate-950/60 text-[11px] font-mono uppercase text-slate-400 tracking-wider">
							<th className="py-3 px-4">Fecha y Hora</th>
							<th className="py-3 px-3 text-center">Estado de Cumplimiento</th>
							<th className="py-3 px-3 text-center">Alertas Críticas</th>
							<th className="py-3 px-4">ID de Snapshot</th>
							<th className="py-3 px-4 text-right">Acción</th>
						</tr>
					</thead>
					<tbody className="divide-y divide-slate-800/60 font-mono">
						{snapshots.map((snap) => {
							const isOk = snap.compliance_status === "COMPLIANCE_OK";
							const alerts = snap.critical_alerts_count || 0;

							return (
								<tr
									key={snap.id}
									className="hover:bg-slate-800/40 transition-colors"
								>
									{/* Timestamp */}
									<td className="py-3.5 px-4 tabular-nums text-slate-200">
										<div className="flex items-center gap-2">
											<Clock className="h-3.5 w-3.5 text-slate-500" />
											<span>{formatDate(snap.created_at)}</span>
										</div>
									</td>

									{/* Status Badge */}
									<td className="py-3.5 px-3 text-center">
										<span
											className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
												isOk
													? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
													: "bg-rose-500/15 text-rose-300 border border-rose-500/30"
											}`}
										>
											{isOk ? (
												<ShieldCheck className="h-3 w-3" />
											) : (
												<ShieldAlert className="h-3 w-3" />
											)}
											{snap.compliance_status}
										</span>
									</td>

									{/* Critical Alerts */}
									<td className="py-3.5 px-3 text-center">
										<span
											className={`font-semibold tabular-nums ${
												alerts > 0
													? "text-rose-400 font-bold"
													: "text-slate-400"
											}`}
										>
											{alerts > 0 ? `${alerts} crítica(s)` : "0"}
										</span>
									</td>

									{/* Snapshot ID */}
									<td className="py-3.5 px-4 text-slate-400 text-[11px]">
										<span className="font-mono bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800">
											{snap.id.length > 12
												? `${snap.id.slice(0, 12)}...`
												: snap.id}
										</span>
									</td>

									{/* Action Button */}
									<td className="py-3.5 px-4 text-right">
										<button
											type="button"
											onClick={() => onViewSnapshot(snap)}
											className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-400 hover:text-sky-300 border border-slate-700 text-[11px] font-mono transition-colors"
										>
											<Eye className="h-3.5 w-3.5" />
											<span>Ver Payload</span>
										</button>
									</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>
		</div>
	);
};
