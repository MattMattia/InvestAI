/**
 * Create Portfolio Modal Component for InvestAI Enterprise Dashboard.
 * Encapsulates form state, Pydantic 422 error parsing, and mutation execution.
 */

import { AlertCircle, Briefcase, Coins, DollarSign, Plus, RefreshCw, X } from "lucide-react";
import type React from "react";
import { useEffect, useId, useState } from "react";
import { useCreatePortfolio } from "@/hooks/usePortfolios";
import { ApiError, type ValidationErrorDetail } from "@/lib/apiClient";
import type { InvestorProfile } from "@/types/api";

interface CreatePortfolioModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CreatePortfolioModal: React.FC<CreatePortfolioModalProps> = ({ isOpen, onClose }) => {
  const uid = useId();
  const createMutation = useCreatePortfolio();

  const [name, setName] = useState<string>("");
  const [investorProfile, setInvestorProfile] = useState<InvestorProfile>("MODERATE");
  const [cashArs, setCashArs] = useState<string>("0");
  const [cashUsd, setCashUsd] = useState<string>("0");

  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationErrorDetail[]>([]);

  useEffect(() => {
    if (isOpen) {
      setName("");
      setInvestorProfile("MODERATE");
      setCashArs("0");
      setCashUsd("0");
      setErrorMessage(null);
      setValidationErrors([]);
    }
  }, [isOpen]);

  // Handle ESC key dismiss
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setValidationErrors([]);

    if (!name.trim()) {
      setErrorMessage("Por favor ingrese un nombre para la cartera.");
      return;
    }

    try {
      await createMutation.mutateAsync({
        name: name.trim(),
        investor_profile: investorProfile,
        cash_balance_ars: cashArs,
        cash_balance_usd: cashUsd,
      });
      onClose();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(err.detail);
        if (err.validationErrors) {
          setValidationErrors(err.validationErrors);
        }
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Ocurrió un error inesperado al crear el portafolio.");
      }
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Cerrar modal"
        tabIndex={-1}
        className="fixed inset-0 h-full w-full cursor-default bg-slate-950/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-800 p-6 shadow-2xl z-10 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-sky-600/20 border border-sky-500/30 flex items-center justify-center text-sky-400">
              <Briefcase className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Crear Nuevo Portafolio</h2>
              <p className="text-xs text-slate-400">
                Configure el perfil de riesgo y saldos iniciales de tesorería
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Global Error Banner */}
        {errorMessage && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start gap-2.5">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-rose-400" />
            <div className="flex-1 space-y-1">
              <span className="font-semibold block">{errorMessage}</span>
              {validationErrors.length > 0 && (
                <ul className="list-disc list-inside space-y-0.5 text-rose-300/90 font-mono text-[11px]">
                  {validationErrors.map((ve) => (
                    <li key={`${ve.field ?? ""}-${ve.issue}`}>
                      {ve.field ? `${ve.field}: ` : ""}
                      {ve.issue}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor={`${uid}-name`}
              className="block text-xs font-medium text-slate-300 mb-1.5"
            >
              Nombre de la Cartera *
            </label>
            <input
              id={`${uid}-name`}
              type="text"
              required
              placeholder="Ej: Cartera Renta Fija ARS o CEDEARs Tech"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-100 placeholder-slate-500 text-sm focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition-all"
            />
          </div>

          <div>
            <span className="block text-xs font-medium text-slate-300 mb-1.5">
              Perfil de Inversor (Asset Allocation)
            </span>
            <div className="grid grid-cols-3 gap-2">
              {(["CONSERVATIVE", "MODERATE", "AGGRESSIVE"] as InvestorProfile[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setInvestorProfile(p)}
                  className={`py-2 px-2 text-xs font-mono font-medium rounded-lg border text-center transition-all ${
                    investorProfile === p
                      ? "bg-sky-600/20 text-sky-300 border-sky-500 shadow-sm"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200 hover:bg-slate-800/40"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Bimonetary Initial Cash Balances */}
          <div className="grid grid-cols-2 gap-3 pt-1">
            <div>
              <label
                htmlFor={`${uid}-cash-ars`}
                className="block text-xs font-medium text-slate-300 mb-1.5 flex items-center gap-1.5"
              >
                <Coins className="h-3.5 w-3.5 text-emerald-400" />
                Saldo Inicial ARS ($)
              </label>
              <input
                id={`${uid}-cash-ars`}
                type="number"
                step="any"
                min="0"
                value={cashArs}
                onChange={(e) => setCashArs(e.target.value)}
                className="w-full px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-100 font-mono text-sm focus:outline-none focus:border-sky-500 transition-all"
              />
            </div>

            <div>
              <label
                htmlFor={`${uid}-cash-usd`}
                className="block text-xs font-medium text-slate-300 mb-1.5 flex items-center gap-1.5"
              >
                <DollarSign className="h-3.5 w-3.5 text-sky-400" />
                Saldo Inicial USD (US$)
              </label>
              <input
                id={`${uid}-cash-usd`}
                type="number"
                step="any"
                min="0"
                value={cashUsd}
                onChange={(e) => setCashUsd(e.target.value)}
                className="w-full px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-slate-100 font-mono text-sm focus:outline-none focus:border-sky-500 transition-all"
              />
            </div>
          </div>

          {/* Actions */}
          <div className="pt-4 border-t border-slate-800 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={createMutation.isPending}
              className="px-4 py-2 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-md shadow-sky-600/30 transition-all flex items-center gap-2 disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Creando...</span>
                </>
              ) : (
                <>
                  <Plus className="h-4 w-4" />
                  <span>Crear Portafolio</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
