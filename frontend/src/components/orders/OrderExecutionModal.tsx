/**
 * OrderExecutionModal Component for InvestAI Enterprise.
 * High-precision assisted order dispatch modal featuring pre-trade fee breakdown
 * (Broker 0.50%, VAT 21%, BYMA/CNV 0.10%), inventory & liquidity guards, and RBAC defense.
 */

import React, { useEffect, useId, useMemo, useState } from "react";
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
  Wallet,
  X,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePortfolios } from "@/hooks/usePortfolios";
import {
  calculateOrderCostBreakdown,
  formatMoney,
  parseDecimalSafe,
} from "@/lib/formatters";
import { marketKeys, orderKeys, portfolioKeys } from "@/lib/queryKeys";
import { orderService } from "@/services/orderService";
import { CreateOrderPayload, OrderRecord, Portfolio } from "@/types/api";

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
  initialPrice = 5850.0,
  initialCurrency = "ARS",
  initialPortfolioId,
  onOrderCreated,
}) => {
  const modalId = useId();
  const queryClient = useQueryClient();
  const { isAuthenticated, isTrader, isAdmin } = useAuth();
  const canTrade = isAuthenticated && (isTrader || isAdmin);

  const { data: portfolios = [] } = usePortfolios();

  // Form State
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string>(
    initialPortfolioId || ""
  );
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [quantity, setQuantity] = useState<number>(10);
  const [customPrice, setCustomPrice] = useState<number>(initialPrice);
  const [justification, setJustification] = useState<string>("");
  const [successOrder, setSuccessOrder] = useState<OrderRecord | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Sync initial props on open
  useEffect(() => {
    if (isOpen) {
      if (initialPortfolioId) {
        setSelectedPortfolioId(initialPortfolioId);
      } else if (portfolios.length > 0 && !selectedPortfolioId) {
        setSelectedPortfolioId(portfolios[0].id);
      }
      setCustomPrice(initialPrice > 0 ? initialPrice : 100.0);
      setSuccessOrder(null);
      setSubmitError(null);
    }
  }, [isOpen, initialPortfolioId, initialPrice, portfolios, selectedPortfolioId]);

  // Handle ESC key press
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const activePortfolio = useMemo<Portfolio | undefined>(() => {
    return portfolios.find((p) => p.id === selectedPortfolioId) || portfolios[0];
  }, [portfolios, selectedPortfolioId]);

  const effectivePrice = orderType === "MARKET" ? initialPrice : customPrice;
  const currency = initialCurrency;

  // Pre-Trade Cost Breakdown
  const breakdown = useMemo(() => {
    return calculateOrderCostBreakdown({
      quantity,
      price: effectivePrice,
      side,
    });
  }, [quantity, effectivePrice, side]);

  // Holding inventory check in SELL mode
  const currentHoldingShares = useMemo(() => {
    if (!activePortfolio || !activePortfolio.holdings) return 0;
    const h = activePortfolio.holdings.find(
      (item) => item.asset_ticker === initialTicker.trim().toUpperCase()
    );
    return h ? Math.floor(parseDecimalSafe(h.quantity)) : 0;
  }, [activePortfolio, initialTicker]);

  const hasInsufficientHoldings = side === "SELL" && quantity > currentHoldingShares;

  // Cash liquidity check in BUY mode
  const availableCash = useMemo(() => {
    if (!activePortfolio) return 0;
    return currency === "ARS"
      ? parseDecimalSafe(activePortfolio.cash_balance_ars)
      : parseDecimalSafe(activePortfolio.cash_balance_usd);
  }, [activePortfolio, currency]);

  const hasInsufficientCash = side === "BUY" && breakdown.netTotal > availableCash;

  // Mutation
  const orderMutation = useMutation({
    mutationFn: async (payload: CreateOrderPayload) => {
      return await orderService.createOrder(payload);
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
      setSubmitError(`No dispone de tenencias suficientes para vender ${quantity} títulos.`);
      return;
    }
    if (hasInsufficientCash) {
      setSubmitError("Saldo de caja insuficiente para cubrir la compra con aranceles.");
      return;
    }

    setSubmitError(null);
    orderMutation.mutate({
      portfolio_id: activePortfolio.id,
      ticker: initialTicker,
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
      <div className="relative w-full max-w-xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
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
                <span>Operar Especie: {initialTicker}</span>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                  {currency}
                </span>
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                BYMA • Rueda Continua • Liquidación T+2
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
        <div className="p-6 overflow-y-auto space-y-5">
          {/* RBAC Viewer Warning */}
          {!canTrade && (
            <div className="p-3.5 rounded-xl bg-amber-950/40 border border-amber-800/40 flex items-start gap-2.5 text-xs text-amber-200">
              <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold block text-amber-300">
                  Cuenta en Modo Solo Lectura (VIEWER)
                </span>
                El despacho de órdenes al mercado exige privilegios de{" "}
                <strong>TRADER</strong> o <strong>ADMIN</strong>.
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
                  Orden Despachada Exitosamente
                </h3>
                <p className="text-xs text-slate-400 font-mono mt-1">
                  ID: {successOrder.id} • Estado: {successOrder.status}
                </p>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-left font-mono text-xs space-y-2">
                <div className="flex justify-between">
                  <span className="text-slate-400">Operación:</span>
                  <span
                    className={`font-bold ${
                      successOrder.side === "BUY" ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {successOrder.side === "BUY" ? "COMPRA" : "VENTA"} {successOrder.quantity} {successOrder.ticker}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Precio Operado:</span>
                  <span className="text-white">
                    {formatMoney(successOrder.price, currency)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Aranceles Totales:</span>
                  <span className="text-amber-400">
                    {formatMoney(successOrder.total_fees, currency)}
                  </span>
                </div>
                <div className="flex justify-between border-t border-slate-800 pt-1 font-bold">
                  <span className="text-slate-200">Total Liquidado:</span>
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
                Cerrar y Volver al Monitor
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Destination Portfolio Selector */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Briefcase className="h-3.5 w-3.5 text-sky-400" />
                    Cartera Operativa:
                  </span>
                  {activePortfolio && (
                    <span className="font-mono text-[11px] text-slate-400 flex items-center gap-1">
                      <Wallet className="h-3 w-3 text-emerald-400" />
                      Disponible: {formatMoney(availableCash, currency)}
                    </span>
                  )}
                </label>
                <select
                  value={selectedPortfolioId}
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

              {/* Side Switcher (BUY vs SELL) */}
              <div className="grid grid-cols-2 gap-2 pt-1">
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
                  <span>COMPRA</span>
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
                  <span>VENTA</span>
                </button>
              </div>

              {/* Order Type & Quantity Inputs */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
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

                {/* Quantity */}
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-slate-400 font-mono flex items-center justify-between">
                    <span>Cantidad (Nominal):</span>
                    {side === "SELL" && (
                      <span className="text-[10px] text-slate-400">
                        Tenencia: {currentHoldingShares}
                      </span>
                    )}
                  </label>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={quantity}
                    onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
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
                    onChange={(e) => setCustomPrice(parseFloat(e.target.value) || 0)}
                    disabled={!canTrade || orderMutation.isPending}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:ring-1 focus:ring-sky-500"
                  />
                </div>
              )}

              {/* Justification Field */}
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-slate-400 font-mono">
                  Motivo / Justificación (Opcional):
                </label>
                <input
                  type="text"
                  placeholder="Ej: Rebalanceo táctico, toma de ganancias, incremento de posición"
                  value={justification}
                  onChange={(e) => setJustification(e.target.value)}
                  disabled={!canTrade || orderMutation.isPending}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500 font-sans"
                />
              </div>

              {/* Pre-Trade Financial Cost Breakdown */}
              <div className="p-4 rounded-xl bg-slate-950 border border-slate-800/80 space-y-2">
                <div className="flex items-center justify-between text-xs font-mono text-slate-300 font-semibold pb-1.5 border-b border-slate-800/60">
                  <span className="flex items-center gap-1.5">
                    <Receipt className="h-3.5 w-3.5 text-sky-400" />
                    Cómputo Pre-Trade de Comisiones
                  </span>
                  <span className="text-[10px] text-slate-400 uppercase">
                    Aranceles BYMA / CNV
                  </span>
                </div>

                <div className="space-y-1 text-xs font-mono text-slate-400">
                  <div className="flex justify-between">
                    <span>Subtotal Bruto ({quantity} x {formatMoney(effectivePrice, currency)}):</span>
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
                    Tenencias insuficientes en cartera: posee {currentHoldingShares} títulos de {initialTicker}.
                  </span>
                </div>
              )}

              {hasInsufficientCash && (
                <div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/50 flex items-center gap-2 text-xs text-rose-300">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400" />
                  <span>
                    Saldo de caja insuficiente: dispone de {formatMoney(availableCash, currency)} y la operación requiere {formatMoney(breakdown.netTotal, currency)}.
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
                      Confirmar {side === "BUY" ? "Compra" : "Venta"} ({formatMoney(breakdown.netTotal, currency)})
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
