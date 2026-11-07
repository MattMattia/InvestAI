import {
	Award,
	Briefcase,
	Compass,
	Plus,
	RefreshCw,
	ShieldCheck,
} from "lucide-react";
import type React from "react";
import { useId, useState } from "react";
import type { InvestorProfile, PortfolioListItem } from "../types/portfolio";

interface NavbarProps {
	portfolios: PortfolioListItem[];
	selectedPortfolioId: string | null;
	currentProfile?: InvestorProfile;
	onSelectPortfolio: (id: string) => void;
	onCreatePortfolio: (
		name: string,
		cashArs: number,
		cashUsd: number,
		profile: InvestorProfile,
	) => Promise<void>;
	onUpdateProfile?: (profile: InvestorProfile) => Promise<void>;
	onRefresh: () => void;
	loading: boolean;
}

const PROFILE_CONFIG: Record<
	InvestorProfile,
	{ label: string; badgeCls: string; description: string; limits: string }
> = {
	CONSERVATIVE: {
		label: "Conservador",
		badgeCls: "bg-emerald-950/80 text-emerald-400 border-emerald-800",
		description: "Preservación patrimonial y renta fija prioritaria.",
		limits:
			"Máx. Activo: 10% | Máx. Sector: 25% | Mín. Renta Fija: 60% | Banda: ±3%",
	},
	MODERATE: {
		label: "Moderado",
		badgeCls: "bg-sky-950/80 text-sky-400 border-sky-800",
		description: "Balance entre crecimiento y control de volatilidad.",
		limits:
			"Máx. Activo: 20% | Máx. Sector: 40% | Mín. Renta Fija: 25% | Banda: ±5%",
	},
	AGGRESSIVE: {
		label: "Agresivo",
		badgeCls: "bg-purple-950/80 text-purple-400 border-purple-800",
		description: "Máxima apreciación con alta exposición en renta variable.",
		limits:
			"Máx. Activo: 35% | Máx. Sector: 60% | Sin piso renta fija | Banda: ±8%",
	},
};

export const Navbar: React.FC<NavbarProps> = ({
	portfolios,
	selectedPortfolioId,
	currentProfile = "MODERATE",
	onSelectPortfolio,
	onCreatePortfolio,
	onUpdateProfile,
	onRefresh,
	loading,
}) => {
	const uid = useId();
	const [showModal, setShowModal] = useState(false);
	const [newPortName, setNewPortName] = useState("");
	const [profile, setProfile] = useState<InvestorProfile>("MODERATE");
	const [cashArs, setCashArs] = useState<number>(0);
	const [cashUsd, setCashUsd] = useState<number>(0);

	const selectedPort = portfolios.find((p) => p.id === selectedPortfolioId);
	const activeProfile =
		selectedPort?.investor_profile || currentProfile || "MODERATE";
	const profileInfo = PROFILE_CONFIG[activeProfile] || PROFILE_CONFIG.MODERATE;

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!newPortName.trim()) return;
		await onCreatePortfolio(newPortName.trim(), cashArs, cashUsd, profile);
		setNewPortName("");
		setCashArs(0);
		setCashUsd(0);
		setProfile("MODERATE");
		setShowModal(false);
	};

	return (
		<>
			<header className="bg-slate-800/90 backdrop-blur border-b border-slate-700 sticky top-0 z-30">
				<div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
					<div className="flex items-center space-x-3">
						<div className="w-10 h-10 rounded-lg bg-sky-600 flex items-center justify-center shadow-lg shadow-sky-600/30">
							<ShieldCheck className="w-6 h-6 text-white" />
						</div>
						<div>
							<div className="flex items-center space-x-2">
								<span className="text-xl font-bold tracking-tight text-white">
									InvestAI
								</span>
								<span className="text-xs font-semibold px-2 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-800">
									Etapa 1: Determinista
								</span>
							</div>
							<p className="text-xs text-slate-400">
								Risk Management & Control Cuantitativo
							</p>
						</div>
					</div>

					<div className="flex items-center space-x-3">
						{/* Portfolio Selector & Profile Badge */}
						<div className="flex items-center space-x-2 bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5">
							<Briefcase className="w-4 h-4 text-slate-400 flex-shrink-0" />
							<select
								className="bg-transparent text-sm text-slate-200 focus:outline-none cursor-pointer max-w-[180px] sm:max-w-xs truncate"
								value={selectedPortfolioId || ""}
								onChange={(e) => onSelectPortfolio(e.target.value)}
							>
								{portfolios.length === 0 ? (
									<option value="" disabled>
										Sin carteras
									</option>
								) : (
									portfolios.map((p) => (
										<option
											key={p.id}
											value={p.id}
											className="bg-slate-900 text-slate-200"
										>
											{p.name} ({p.holdings_count} activos)
										</option>
									))
								)}
							</select>

							{/* Active Profile Badge / Selector */}
							{selectedPort && onUpdateProfile ? (
								<span
									className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${profileInfo.badgeCls} hidden sm:inline-flex items-center space-x-1`}
									title={`${profileInfo.description} — Click para cambiar perfil`}
								>
									<Compass className="w-3 h-3 inline mr-1 flex-shrink-0" />
									<select
										value={activeProfile}
										onChange={(e) =>
											onUpdateProfile(e.target.value as InvestorProfile)
										}
										className="bg-transparent text-[11px] font-semibold text-inherit cursor-pointer focus:outline-none"
									>
										<option
											value="CONSERVATIVE"
											className="bg-slate-900 text-emerald-400"
										>
											Conservador
										</option>
										<option
											value="MODERATE"
											className="bg-slate-900 text-sky-400"
										>
											Moderado
										</option>
										<option
											value="AGGRESSIVE"
											className="bg-slate-900 text-purple-400"
										>
											Agresivo
										</option>
									</select>
								</span>
							) : (
								<span
									className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${profileInfo.badgeCls} hidden sm:inline-flex items-center space-x-1`}
									title={`${profileInfo.description} — ${profileInfo.limits}`}
								>
									<Compass className="w-3 h-3 inline mr-1" />
									<span>{profileInfo.label}</span>
								</span>
							)}
						</div>

						<button
							type="button"
							onClick={() => setShowModal(true)}
							className="flex items-center space-x-1 bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium px-3 py-2 rounded-lg transition shadow-sm"
						>
							<Plus className="w-4 h-4" />
							<span className="hidden sm:inline">Nueva Cartera</span>
						</button>

						<button
							type="button"
							onClick={onRefresh}
							disabled={loading}
							title="Recargar datos"
							className="p-2 text-slate-400 hover:text-white bg-slate-900 hover:bg-slate-700 border border-slate-700 rounded-lg transition disabled:opacity-50"
						>
							<RefreshCw
								className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
							/>
						</button>
					</div>
				</div>
			</header>

			{/* Modal Nueva Cartera */}
			{showModal && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
					<div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-lg w-full shadow-2xl">
						<div className="flex items-center space-x-2 mb-4">
							<Award className="w-5 h-5 text-sky-400" />
							<h3 className="text-lg font-bold text-white">
								Crear Nueva Cartera
							</h3>
						</div>

						<form onSubmit={handleSubmit} className="space-y-4">
							<div>
								<label
									htmlFor={`${uid}-port-name`}
									className="block text-xs font-semibold text-slate-300 mb-1"
								>
									Nombre del Portafolio
								</label>
								<input
									id={`${uid}-port-name`}
									type="text"
									required
									placeholder="ej. Cartera Equities & Bonos 2026"
									value={newPortName}
									onChange={(e) => setNewPortName(e.target.value)}
									className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
								/>
							</div>

							{/* Selector de Perfil del Inversor */}
							<div>
								<span className="block text-xs font-semibold text-slate-300 mb-1.5">
									Perfil de Riesgo y Estrategia Cuantitativa
								</span>
								<div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
									{(
										[
											"CONSERVATIVE",
											"MODERATE",
											"AGGRESSIVE",
										] as InvestorProfile[]
									).map((pKey) => {
										const cfg = PROFILE_CONFIG[pKey];
										const isSelected = profile === pKey;
										return (
											<button
												type="button"
												key={pKey}
												onClick={() => setProfile(pKey)}
												className={`text-left p-3 rounded-lg border transition flex flex-col justify-between ${
													isSelected
														? "bg-slate-900/90 border-sky-500 ring-2 ring-sky-500/20 shadow-md"
														: "bg-slate-900/40 border-slate-700 hover:border-slate-600 hover:bg-slate-900/60"
												}`}
											>
												<div>
													<div className="flex items-center justify-between mb-1">
														<span
															className={`text-xs font-bold ${
																isSelected ? "text-sky-400" : "text-slate-200"
															}`}
														>
															{cfg.label}
														</span>
														<input
															type="radio"
															name="investorProfile"
															checked={isSelected}
															onChange={() => setProfile(pKey)}
															className="accent-sky-500 h-3.5 w-3.5"
														/>
													</div>
													<p className="text-[11px] text-slate-400 leading-tight">
														{cfg.description}
													</p>
												</div>
											</button>
										);
									})}
								</div>

								{/* Explicación dinámica de límites según perfil seleccionado */}
								<div className="mt-2.5 p-2.5 rounded-lg bg-slate-900/70 border border-slate-700/80 text-[11px] text-slate-300">
									<div className="font-semibold text-slate-200 mb-0.5">
										Reglas aplicadas al perfil {PROFILE_CONFIG[profile].label}:
									</div>
									<div className="text-slate-400">
										{PROFILE_CONFIG[profile].limits}
									</div>
								</div>
							</div>

							{/* Saldos iniciales de efectivo (estrictamente 0 por defecto) */}
							<div className="grid grid-cols-2 gap-3 pt-1">
								<div>
									<label
										htmlFor={`${uid}-cash-ars`}
										className="block text-xs font-semibold text-slate-300 mb-1"
									>
										Efectivo Inicial ARS ($)
									</label>
									<input
										id={`${uid}-cash-ars`}
										type="number"
										min="0"
										step="any"
										value={cashArs}
										onChange={(e) =>
											setCashArs(parseFloat(e.target.value) || 0)
										}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
									/>
									<span className="text-[10px] text-slate-500">
										Dejar en 0 para cartera pura de activos
									</span>
								</div>
								<div>
									<label
										htmlFor={`${uid}-cash-usd`}
										className="block text-xs font-semibold text-slate-300 mb-1"
									>
										Efectivo Inicial USD (u$s)
									</label>
									<input
										id={`${uid}-cash-usd`}
										type="number"
										min="0"
										step="any"
										value={cashUsd}
										onChange={(e) =>
											setCashUsd(parseFloat(e.target.value) || 0)
										}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
									/>
									<span className="text-[10px] text-slate-500">
										Dejar en 0 para cartera pura de activos
									</span>
								</div>
							</div>

							<div className="flex justify-end space-x-2 pt-3 border-t border-slate-700/60">
								<button
									type="button"
									onClick={() => setShowModal(false)}
									className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-white"
								>
									Cancelar
								</button>
								<button
									type="submit"
									className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold rounded-lg transition shadow-md shadow-sky-600/20"
								>
									Crear Portafolio
								</button>
							</div>
						</form>
					</div>
				</div>
			)}
		</>
	);
};
