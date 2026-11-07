import { ArrowDownRight, ArrowUpRight, Plus, Trash2 } from "lucide-react";
import type React from "react";
import { useState } from "react";
import type { Holding, HoldingCreatePayload } from "../types/portfolio";

interface HoldingsTableProps {
	holdings: Holding[];
	onAddHolding: (payload: HoldingCreatePayload) => Promise<void>;
	onDeleteHolding: (holdingId: number) => Promise<void>;
}

export const HoldingsTable: React.FC<HoldingsTableProps> = ({
	holdings,
	onAddHolding,
	onDeleteHolding,
}) => {
	const [showModal, setShowModal] = useState(false);
	const [ticker, setTicker] = useState("");
	const [quantity, setQuantity] = useState<number>(10);
	const [buyPrice, setBuyPrice] = useState<number>(1000);
	const [currentPrice, setCurrentPrice] = useState<number>(1100);
	const [currency, setCurrency] = useState("ARS");
	const [assetType, setAssetType] = useState("CEDEAR");
	const [sector, setSector] = useState("OTHER");

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!ticker.trim()) return;
		await onAddHolding({
			ticker: ticker.trim().toUpperCase(),
			quantity,
			average_buy_price: buyPrice,
			current_price: currentPrice,
			currency,
			asset_type: assetType,
			sector,
		});
		setTicker("");
		setShowModal(false);
	};

	const getAssetTypeBadge = (type?: string) => {
		switch (type) {
			case "BOND_SOVEREIGN":
				return (
					<span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-800">
						Bono Soberano
					</span>
				);
			case "BOND_CORPORATE":
				return (
					<span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-950 text-blue-300 border border-blue-800">
						Obligación Negociable
					</span>
				);
			case "CEDEAR":
				return (
					<span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-950 text-amber-300 border border-amber-800">
						CEDEAR
					</span>
				);
			case "EQUITY":
				return (
					<span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-purple-950 text-purple-300 border border-purple-800">
						Acción Local
					</span>
				);
			default:
				return (
					<span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
						{type || "Activo"}
					</span>
				);
		}
	};

	return (
		<div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-sm">
			<div className="p-4 sm:p-5 border-b border-slate-700 flex items-center justify-between">
				<div>
					<h3 className="text-base font-bold text-white">
						Composición de Cartera y Tenencias
					</h3>
					<p className="text-xs text-slate-400">
						Posiciones activas, precios de compra y valuación en tiempo real
					</p>
				</div>
				<button
					onClick={() => setShowModal(true)}
					className="flex items-center space-x-1.5 bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold px-3 py-2 rounded-lg transition"
				>
					<Plus className="w-4 h-4" />
					<span>Agregar Posición</span>
				</button>
			</div>

			<div className="overflow-x-auto">
				<table className="w-full text-left text-sm text-slate-300">
					<thead className="bg-slate-900/60 text-xs uppercase tracking-wider text-slate-400 font-semibold border-b border-slate-700/80">
						<tr>
							<th className="py-3 px-4">Ticker / Especie</th>
							<th className="py-3 px-4">Tipo</th>
							<th className="py-3 px-4 text-right">Nominales</th>
							<th className="py-3 px-4 text-right">PPC</th>
							<th className="py-3 px-4 text-right">Cotización</th>
							<th className="py-3 px-4 text-right">Valor Mercado</th>
							<th className="py-3 px-4 text-right">P&L ($ / %)</th>
							<th className="py-3 px-4 text-center">Peso (%)</th>
							<th className="py-3 px-4 text-center">Acciones</th>
						</tr>
					</thead>
					<tbody className="divide-y divide-slate-700/60 font-medium">
						{holdings.length === 0 ? (
							<tr>
								<td
									colSpan={9}
									className="py-12 text-center text-slate-400 text-sm"
								>
									No hay tenencias registradas en esta cartera. Añade una
									posición manual o importa tu reporte CSV/Excel.
								</td>
							</tr>
						) : (
							holdings.map((h) => {
								const isPositive = h.unrealized_pnl >= 0;
								return (
									<tr key={h.id} className="hover:bg-slate-700/30 transition">
										<td className="py-3 px-4">
											<div className="font-bold text-white text-sm">
												{h.asset_ticker}
											</div>
											<div className="text-xs text-slate-400">
												{h.asset?.sector || "GENERAL"}
											</div>
										</td>
										<td className="py-3 px-4">
											{getAssetTypeBadge(h.asset?.asset_type)}
										</td>
										<td className="py-3 px-4 text-right font-mono text-slate-200">
											{h.quantity.toLocaleString("es-AR")}
										</td>
										<td className="py-3 px-4 text-right font-mono text-slate-300">
											${" "}
											{h.average_buy_price.toLocaleString("es-AR", {
												minimumFractionDigits: 2,
											})}
										</td>
										<td className="py-3 px-4 text-right font-mono text-white">
											${" "}
											{h.current_price.toLocaleString("es-AR", {
												minimumFractionDigits: 2,
											})}
										</td>
										<td className="py-3 px-4 text-right font-mono font-bold text-slate-100">
											${" "}
											{h.market_value.toLocaleString("es-AR", {
												minimumFractionDigits: 2,
											})}
										</td>
										<td className="py-3 px-4 text-right">
											<div
												className={`flex items-center justify-end font-semibold text-xs ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
											>
												{isPositive ? (
													<ArrowUpRight className="w-3.5 h-3.5 mr-0.5" />
												) : (
													<ArrowDownRight className="w-3.5 h-3.5 mr-0.5" />
												)}
												<span>
													${" "}
													{Math.abs(h.unrealized_pnl).toLocaleString("es-AR", {
														minimumFractionDigits: 2,
													})}
												</span>
											</div>
											<div
												className={`text-[11px] font-mono ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
											>
												{isPositive ? "+" : ""}
												{h.unrealized_pnl_pct.toFixed(2)}%
											</div>
										</td>
										<td className="py-3 px-4 text-center">
											<div className="inline-block w-20">
												<div className="text-xs font-mono font-semibold text-slate-200 mb-1">
													{h.weight_pct !== null && h.weight_pct !== undefined
														? `${h.weight_pct.toFixed(1)}%`
														: "0.0%"}
												</div>
												<div className="w-full bg-slate-700 h-1.5 rounded-full overflow-hidden">
													<div
														className="bg-sky-500 h-full rounded-full"
														style={{
															width: `${Math.min(h.weight_pct || 0, 100)}%`,
														}}
													/>
												</div>
											</div>
										</td>
										<td className="py-3 px-4 text-center">
											<button
												onClick={() => onDeleteHolding(h.id)}
												title="Eliminar posición"
												className="text-slate-400 hover:text-rose-400 p-1.5 rounded-lg hover:bg-slate-700 transition"
											>
												<Trash2 className="w-4 h-4" />
											</button>
										</td>
									</tr>
								);
							})
						)}
					</tbody>
				</table>
			</div>

			{/* Modal Agregar Posición */}
			{showModal && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
					<div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-lg w-full shadow-2xl">
						<h3 className="text-lg font-bold text-white mb-4">
							Añadir Posición a la Cartera
						</h3>
						<form onSubmit={handleSubmit} className="space-y-4">
							<div className="grid grid-cols-2 gap-3">
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Ticker / Símbolo
									</label>
									<input
										type="text"
										required
										placeholder="ej. AAPL, AL30, GGAL"
										value={ticker}
										onChange={(e) => setTicker(e.target.value)}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white uppercase focus:outline-none focus:border-sky-500"
									/>
								</div>
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Tipo de Activo
									</label>
									<select
										value={assetType}
										onChange={(e) => setAssetType(e.target.value)}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500 cursor-pointer"
									>
										<option value="CEDEAR">CEDEAR</option>
										<option value="BOND_SOVEREIGN">Bono Soberano</option>
										<option value="BOND_CORPORATE">
											Obligación Negociable
										</option>
										<option value="EQUITY">Acción Local (Merval)</option>
										<option value="TREASURY_BILL">
											Letra del Tesoro (LECAP)
										</option>
									</select>
								</div>
							</div>

							<div className="grid grid-cols-3 gap-3">
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Cantidad
									</label>
									<input
										type="number"
										min="0.0001"
										step="any"
										required
										value={quantity}
										onChange={(e) =>
											setQuantity(parseFloat(e.target.value) || 0)
										}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
									/>
								</div>
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Precio Compra ($)
									</label>
									<input
										type="number"
										min="0"
										step="any"
										required
										value={buyPrice}
										onChange={(e) =>
											setBuyPrice(parseFloat(e.target.value) || 0)
										}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
									/>
								</div>
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Cotización Mercado ($)
									</label>
									<input
										type="number"
										min="0"
										step="any"
										required
										value={currentPrice}
										onChange={(e) =>
											setCurrentPrice(parseFloat(e.target.value) || 0)
										}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
									/>
								</div>
							</div>

							<div className="grid grid-cols-2 gap-3">
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Moneda
									</label>
									<select
										value={currency}
										onChange={(e) => setCurrency(e.target.value)}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500 cursor-pointer"
									>
										<option value="ARS">ARS (Pesos)</option>
										<option value="USD">USD (Dólares)</option>
									</select>
								</div>
								<div>
									<label className="block text-xs font-semibold text-slate-300 mb-1">
										Sector Económico
									</label>
									<select
										value={sector}
										onChange={(e) => setSector(e.target.value)}
										className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500 cursor-pointer"
									>
										<option value="TECHNOLOGY">Tecnología</option>
										<option value="FINANCIAL_SERVICES">
											Servicios Financieros
										</option>
										<option value="ENERGY">Energía / Petróleo</option>
										<option value="GOVERNMENT">Gobierno / Soberano</option>
										<option value="CONSUMER_CYCLICAL">Consumo Cíclico</option>
										<option value="CONSUMER_DEFENSIVE">
											Consumo Defensivo
										</option>
										<option value="HEALTHCARE">Salud</option>
										<option value="OTHER">Otros / Diversificado</option>
									</select>
								</div>
							</div>

							<div className="flex justify-end space-x-2 pt-3 border-t border-slate-700">
								<button
									type="button"
									onClick={() => setShowModal(false)}
									className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-white"
								>
									Cancelar
								</button>
								<button
									type="submit"
									className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold rounded-lg transition"
								>
									Confirmar Posición
								</button>
							</div>
						</form>
					</div>
				</div>
			)}
		</div>
	);
};
