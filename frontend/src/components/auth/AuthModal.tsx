/**
 * Modal Component for User Login & Registration.
 * Styled with Tailwind dark slate financial theme, keyboard accessibility (Escape),
 * and Pydantic 422 / 401 error mapping.
 */

import React, { useEffect, useState } from "react";
import { AlertCircle, Lock, Mail, RefreshCw, UserCheck, X } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { ApiError, ValidationErrorDetail } from "@/lib/apiClient";
import { InvestorProfile } from "@/types/api";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialMode?: "login" | "register";
}

export const AuthModal: React.FC<AuthModalProps> = ({
  isOpen,
  onClose,
  initialMode = "login",
}) => {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">(initialMode);

  // Form Fields
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");
  const [fullName, setFullName] = useState<string>("");
  const [investorProfile, setInvestorProfile] =
    useState<InvestorProfile>("MODERATE");

  // Local UI State
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<
    ValidationErrorDetail[]
  >([]);

  // Synchronize initial mode
  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      setErrorMessage(null);
      setValidationErrors([]);
    }
  }, [isOpen, initialMode]);

  // Handle ESC key to dismiss modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
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
    setSubmitting(true);

    try {
      if (mode === "login") {
        await login({ email, password });
      } else {
        await register({
          email,
          password,
          full_name: fullName,
          investor_profile: investorProfile,
        });
      }
      onClose();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(err.detail);
        if (err.validationErrors && err.validationErrors.length > 0) {
          setValidationErrors(err.validationErrors);
        }
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Ocurrió un error inesperado al procesar la solicitud.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Modal Header & Tabs */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 pt-5 pb-3">
          <div className="flex gap-4">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setErrorMessage(null);
                setValidationErrors([]);
              }}
              className={`text-sm font-semibold pb-2 border-b-2 transition-colors ${
                mode === "login"
                  ? "border-sky-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              Iniciar Sesión
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setErrorMessage(null);
                setValidationErrors([]);
              }}
              className={`text-sm font-semibold pb-2 border-b-2 transition-colors ${
                mode === "register"
                  ? "border-sky-500 text-white"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              Registrarse
            </button>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
            aria-label="Cerrar modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
          {/* Error Banner */}
          {errorMessage && (
            <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800/80 text-rose-300 text-xs flex items-start gap-2.5">
              <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="font-semibold">{errorMessage}</p>
                {validationErrors.length > 0 && (
                  <ul className="mt-1 list-disc list-inside space-y-0.5 text-rose-300/80">
                    {validationErrors.map((v, i) => (
                      <li key={i}>
                        {v.field ? <span className="font-mono">{v.field}: </span> : null}
                        {v.issue}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          {/* Registration Extra Fields */}
          {mode === "register" && (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Nombre Completo
                </label>
                <div className="relative">
                  <UserCheck className="h-4 w-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Ej. Martín González"
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Perfil de Inversor
                </label>
                <select
                  value={investorProfile}
                  onChange={(e) =>
                    setInvestorProfile(e.target.value as InvestorProfile)
                  }
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                >
                  <option value="CONSERVATIVE">Conservador (Baja volatilidad, Renta fija)</option>
                  <option value="MODERATE">Moderado (Equilibrio retorno/riesgo)</option>
                  <option value="AGGRESSIVE">Agresivo (Renta variable, Renta mixta)</option>
                </select>
              </div>
            </>
          )}

          {/* Common Fields: Email and Password */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Correo Electrónico
            </label>
            <div className="relative">
              <Mail className="h-4 w-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="analista@investai.market"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Contraseña
            </label>
            <div className="relative">
              <Lock className="h-4 w-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              />
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={submitting}
            className="mt-2 w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm flex items-center justify-center gap-2 transition shadow-lg shadow-sky-600/30 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? (
              <>
                <RefreshCw className="h-4 w-4 animate-spin" />
                <span>Procesando...</span>
              </>
            ) : mode === "login" ? (
              <span>Acceder a la Plataforma</span>
            ) : (
              <span>Crear Cuenta Institucional</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};

