/**
 * Institutional User Profile & RBAC Simulation Modal.
 * Allows authenticated users to inspect account metadata, update their full name,
 * and hot-swap Investor Profile (CONSERVATIVE / MODERATE / AGGRESSIVE) and
 * RBAC Role (TRADER / ADMIN / VIEWER) for live academic demonstrations.
 */

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Lock,
  RefreshCw,
  Shield,
  Sliders,
  User as UserIcon,
  X,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { InvestorProfile, UserRole } from "@/types/api";

interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const UserProfileModal: React.FC<UserProfileModalProps> = ({
  isOpen,
  onClose,
}) => {
  const { user, updateUserProfile } = useAuth();

  const [fullName, setFullName] = useState<string>("");
  const [investorProfile, setInvestorProfile] =
    useState<InvestorProfile>("MODERATE");
  const [selectedRole, setSelectedRole] = useState<UserRole>("TRADER");
  const [saving, setSaving] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && user) {
      setFullName(user.full_name || "");
      setInvestorProfile(user.investor_profile || "MODERATE");
      setSelectedRole(user.role || "TRADER");
      setErrorMsg(null);
      setSuccessMsg(null);
    }
  }, [isOpen, user]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !user) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      await updateUserProfile({
        full_name: fullName.trim() || user.full_name,
        investor_profile: investorProfile,
        role: selectedRole,
      });
      setSuccessMsg(
        `Perfil actualizado correctamente — Rol activo: ${selectedRole} | Perfil: ${investorProfile}`
      );
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "No se pudo actualizar el perfil del usuario."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4 bg-slate-950/60">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-sky-500/15 border border-sky-500/30 text-sky-400">
              <UserIcon className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">
                Perfil de Cuenta & Control RBAC
              </h3>
              <p className="text-xs text-slate-400 font-mono">{user.email}</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSave} className="p-6 space-y-5">
          {errorMsg && (
            <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-xs text-rose-200 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {successMsg && (
            <div className="p-3 rounded-lg bg-emerald-950/60 border border-emerald-700 text-xs text-emerald-200 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* Full Name */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Nombre del Operador / Titular
            </label>
            <input
              type="text"
              required
              minLength={2}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>

          {/* Investor Risk Profile */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2 flex items-center gap-1.5">
              <Sliders className="h-3.5 w-3.5 text-sky-400" />
              Perfil de Inversor Predeterminado
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              {(
                [
                  {
                    id: "CONSERVATIVE",
                    label: "Conservador",
                    desc: "Preservación & Renta Fija",
                  },
                  {
                    id: "MODERATE",
                    label: "Moderado",
                    desc: "Balance Riesgo / Retorno",
                  },
                  {
                    id: "AGGRESSIVE",
                    label: "Agresivo",
                    desc: "Renta Variable & Equity",
                  },
                ] as const
              ).map((item) => {
                const active = investorProfile === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setInvestorProfile(item.id)}
                    className={`p-3 rounded-xl border text-left transition ${
                      active
                        ? "bg-sky-500/15 border-sky-500 text-white shadow-sm"
                        : "bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700"
                    }`}
                  >
                    <div className="text-xs font-bold">{item.label}</div>
                    <div className="text-[10px] text-slate-400 mt-0.5 leading-tight">
                      {item.desc}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* RBAC Role Switcher for Live Academic Demo */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2 flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5 text-indigo-400" />
              Rol de Autorización RBAC (Conmutación en Caliente para Defensa)
            </label>
            <div className="space-y-2">
              {(
                [
                  {
                    role: "TRADER" as UserRole,
                    badgeClass:
                      "bg-sky-500/20 text-sky-300 border-sky-500/30",
                    title: "Operador Bursátil (TRADER)",
                    desc: "Habilitado para crear carteras, ejecutar órdenes, simular rebalanceos e ingerir extractos.",
                  },
                  {
                    role: "ADMIN" as UserRole,
                    badgeClass:
                      "bg-rose-500/20 text-rose-300 border-rose-500/30",
                    title: "Administrador Institucional (ADMIN)",
                    desc: "Privilegios totales sobre carteras, auditoría forense, snapshots de riesgo y configuración.",
                  },
                  {
                    role: "VIEWER" as UserRole,
                    badgeClass:
                      "bg-slate-800 text-slate-300 border-slate-700",
                    title: "Auditor de Solo Lectura (VIEWER)",
                    desc: "Modo restringido: bloquea creación de órdenes, ingesta y mutaciones para demostrar blindaje RBAC.",
                  },
                ] as const
              ).map((r) => {
                const isSelected = selectedRole === r.role;
                return (
                  <button
                    key={r.role}
                    type="button"
                    onClick={() => setSelectedRole(r.role)}
                    className={`w-full p-3 rounded-xl border text-left flex items-start justify-between gap-3 transition ${
                      isSelected
                        ? "bg-slate-800/90 border-sky-500 shadow-sm"
                        : "bg-slate-950 border-slate-800/80 hover:border-slate-700"
                    }`}
                  >
                    <div className="space-y-0.5">
                      <div className="text-xs font-semibold text-slate-100 flex items-center gap-2">
                        <span>{r.title}</span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        {r.desc}
                      </p>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border shrink-0 ${r.badgeClass}`}
                    >
                      {r.role}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Security Footer Info */}
          <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-[11px] text-slate-400 font-mono">
            <span className="flex items-center gap-1.5">
              <Lock className="h-3.5 w-3.5 text-emerald-400" />
              ID: {String(user.id).slice(0, 13)}...
            </span>
            <span>Aislamiento BOLA Activo</span>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 transition"
            >
              Cerrar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white flex items-center gap-2 shadow-lg shadow-sky-600/30 transition disabled:opacity-50"
            >
              {saving ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Guardando...</span>
                </>
              ) : (
                <span>Guardar Cambios de Perfil</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

