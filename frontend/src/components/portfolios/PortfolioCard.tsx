/**
 * Financial Portfolio Card Component for InvestAI Enterprise Dashboard.
 * Displays bimonetary cash balances, total market valuation, investor profile badge,
 * and active holdings telemetry.
 */

import {
	Briefcase,
	ChevronRight,
	Coins,
	DollarSign,
	Layers,
} from "lucide-react";
import type React from "react";
import { formatMoney } from "@/lib/formatters";
import type { InvestorProfile, Portfolio } from "@/types/api";

interface PortfolioCardProps {
	portfolio: Portfolio;
	onSelect?: (portfolio: Portfolio) => void;
}

export const PortfolioCard: React.FC<PortfolioCardProps> = ({
	portfolio,
	onSelect,
}) => {
	const profile = (portfolio.investor_profile || "MODERATE")
		.toString()
		.toUpperCase() as InvestorProfile;

	const profileBadgeStyle =
		{
			CONSERVATIVE: "bg-sky-500/10 text-sky-400 border-sky-500/30",
			MODERATE: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
			AGGRESSIVE: "bg-purple-500/10 text-purple-400 border-purple-500/30",
		}[profile] || "bg-slate-800 text-slate-300 border-slate-700";

	const holdingsCount =
		typeof portfolio.holdings_count === "number"
			? portfolio.holdings_count
			: (portfolio.holdings?.length ?? 0);

	return (
		<div
			onClick={() => onSelect?.(portfolio)}
			className="group relative rounded-xl bg-slate-900/90 border border-slate-800 p-5 shadow-lg hover:border-sky-500/50 hover:shadow-sky-500/10 transition-all cursor-pointer flex flex-col justify-between"
		>
			{/* Top Header: Name & Profile */}
			<div>
				<div className="flex items-start justify-between gap-3 mb-3">
					<div className="flex items-center gap-2.5">
						<div className="h-8 w-8 rounded-lg bg-slate-800 flex items-center justify-center text-sky-400 group-hover:bg-sky-600 group-hover:text-white transition-colors">
							<Briefcase className="h-4 w-4" />
						</div>
						<div>
							<h3 className="font-semibold text-sm text-slate-100 group-hover:text-sky-300 transition-colors">
								{portfolio.name}
							</h3>
							<span className="text-[10px] font-mono text-slate-400">
								ID: {portfolio.id.slice(0, 8)}...
							</span>
						</div>
					</div>

					<span
						className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border font-semibold tracking-wider ${profileBadgeStyle}`}
					>
						{profile}
					</span>
				</div>

				{/* Total Valuation Metric */}
				<div className="mt-4 p-3.5 rounded-lg bg-slate-950/70 border border-slate-800/80">
					<span className="text-[10px] uppercase font-mono tracking-wider text-slate-400 block mb-1">
						Valuación Estimada Total
					</span>
					<div className="text-xl font-bold font-mono tracking-tight text-white">
						{formatMoney(
							portfolio.total_market_value_ars ?? portfolio.cash_balance_ars,
							"ARS",
						)}
					</div>
				</div>

				{/* Bimonetary Cash Balances */}
				<div className="mt-4 grid grid-cols-2 gap-2 text-xs">
					<div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-800 flex flex-col">
						<span className="text-[10px] text-slate-400 font-mono flex items-center gap-1 mb-0.5">
							<Coins className="h-3 w-3 text-emerald-400" />
							Caja ARS
						</span>
						<span className="font-mono font-medium text-slate-200">
							{formatMoney(portfolio.cash_balance_ars, "ARS")}
						</span>
					</div>

					<div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-800 flex flex-col">
						<span className="text-[10px] text-slate-400 font-mono flex items-center gap-1 mb-0.5">
							<DollarSign className="h-3 w-3 text-sky-400" />
							Caja USD
						</span>
						<span className="font-mono font-medium text-slate-200">
							{formatMoney(portfolio.cash_balance_usd, "USD")}
						</span>
					</div>
				</div>
			</div>

			{/* Footer Info: Holdings Count, Date & Action Button */}
			<div className="mt-5 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
				<span className="flex items-center gap-1.5 font-mono">
					<Layers className="h-3.5 w-3.5 text-slate-400" />
					{holdingsCount} {holdingsCount === 1 ? "activo" : "activos"}
				</span>

				<button
					type="button"
					onClick={(e) => {
						e.stopPropagation();
						onSelect?.(portfolio);
					}}
					className="flex items-center gap-1 text-[11px] font-mono text-sky-400 hover:text-sky-300 transition-colors font-medium"
				>
					<span>Ver Tenencias</span>
					<ChevronRight className="h-3.5 w-3.5" />
				</button>
			</div>
		</div>
	);
};
