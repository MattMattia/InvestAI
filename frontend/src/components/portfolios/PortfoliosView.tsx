/**
 * Portfolios Dashboard View Component for InvestAI Enterprise.
 * Displays consolidated wealth metrics, responsive card grid, RBAC-guarded actions,
 * and seamless integration with CreatePortfolioModal.
 */

import React, { useMemo, useState } from "react";
import {
  AlertCircle,
  Briefcase,
  Coins,
  DollarSign,
  Filter,
  Lock,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePortfolios } from "@/hooks/usePortfolios";
import { formatMoney, parseDecimalSafe } from "@/lib/formatters";
import { Portfolio } from "@/types/api";
import { CreatePortfolioModal } from "./CreatePortfolioModal";
import { PortfolioCard } from "./PortfolioCard";

interface PortfoliosViewProps {
  onOpenAuthModal: () => void;
  onSelectPortfolio?: (portfolio: Portfolio) => void;
}

export const PortfoliosView: React.FC<PortfoliosViewProps> = ({
  onOpenAuthModal,
  onSelectPortfolio,
}) => {
  const { isAuthenticated, isTrader, isAdmin, isViewer } = useAuth();
  const {
    data: portfolios = [],
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = usePortfolios();

  const [searchQuery, setSearchQuery] = useState<string>("");
  const [profileFilter, setProfileFilter] = useState<string>("ALL");
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);

  const canCreate = isAuthenticated && (isTrader || isAdmin);

  // Consolidated Wealth Metrics
  const metrics = useMemo(() => {
    let totalArs = 0;
    let cashArsTotal = 0;
    let cashUsdTotal = 0;

    portfolios.forEach((p) => {
      const pArs = parseDecimalSafe(p.total_market_value_ars ?? p.cash_balance_ars);
      totalArs += pArs;
      cashArsTotal += parseDecimalSafe(p.cash_balance_ars);
      cashUsdTotal += parseDecimalSafe(p.cash_balance_usd);
    });

    return {
      totalCount: portfolios.length,
      totalWealthArs: totalArs,
      cashArsTotal,
      cashUsdTotal,
    };
  }, [portfolios]);

  // Filtered List
  const filteredPortfolios = useMemo(() => {
    return portfolios.filter((p) => {
      const matchesSearch = p.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const matchesProfile =
        profileFilter === "ALL" ||
        (p.investor_profile || "MODERATE").toUpperCase() === profileFilter;
      return matchesSearch && matchesProfile;
    });
  }, [portfolios, searchQuery, profileFilter]);

  return (
    <div className="space-y-6">
      {/* Header & Primary Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <Briefcase className="h-5 w-5 text-sky-400" />
            Portafolios de Inversión
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Supervisión institucional de activos bajo gestión, caja bimonetaria y asignación táctica
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => refetch()}
            disabled={isFetching || !isAuthenticated}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors disabled:opacity-40"
            title="Refrescar portafolios"
          >
            <RefreshCw
              className={`h-4 w-4 ${isFetching ? "animate-spin text-sky-400" : ""}`}
            />
          </button>

          {canCreate ? (
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-md shadow-sky-600/30 transition-all active:scale-95"
            >
              <Plus className="h-4 w-4" />
              <span>Nueva Cartera</span>
            </button>
          ) : isAuthenticated && isViewer ? (
            <div
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800/80 border border-slate-700 text-slate-400 text-xs cursor-not-allowed"
              title="El rol VIEWER posee permisos de solo lectura"
            >
              <Lock className="h-3.5 w-3.5 text-amber-400" />
              <span>Solo Lectura</span>
            </div>
          ) : (
            <button
              onClick={onOpenAuthModal}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-300 border border-sky-500/30 text-xs font-medium transition-all"
            >
              <Lock className="h-4 w-4 text-sky-400" />
              <span>Acceder para Operar</span>
            </button>
          )}
        </div>
      </div>

      {/* Guest Mode Notice */}
      {!isAuthenticated && (
        <div className="p-4 rounded-xl bg-gradient-to-r from-sky-950/40 via-slate-900 to-slate-900 border border-sky-800/40 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-md">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-sky-600/20 border border-sky-500/30 flex items-center justify-center text-sky-400 shrink-0">
              <ShieldAlert className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-slate-100">
                Sesión Anónima Activa
              </h3>
              <p className="text-[11px] text-slate-400">
                Inicia sesión con tu cuenta corporativa para sincronizar carteras, ejecutar rebalanceos y visualizar órdenes.
              </p>
            </div>
          </div>
          <button
            onClick={onOpenAuthModal}
            className="px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium transition-colors shrink-0 self-start sm:self-auto"
          >
            Iniciar Sesión
          </button>
        </div>
      )}

      {/* Metrics Banner */}
      {isAuthenticated && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1.5">
              <Wallet className="h-3.5 w-3.5 text-sky-400" />
              Carteras Activas
            </span>
            <div className="text-2xl font-bold font-mono text-white mt-2">
              {metrics.totalCount}
            </div>
            <span className="text-[10px] text-slate-400 mt-1">
              Bajo supervisión institucional
            </span>
          </div>

          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1.5">
              <Briefcase className="h-3.5 w-3.5 text-emerald-400" />
              Patrimonio Agregado
            </span>
            <div className="text-2xl font-bold font-mono text-emerald-400 mt-2">
              {formatMoney(metrics.totalWealthArs, "ARS")}
            </div>
            <span className="text-[10px] text-slate-400 mt-1">
              Valuado al tipo implícito BYMA
            </span>
          </div>

          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1.5">
              <Coins className="h-3.5 w-3.5 text-amber-400" />
              Caja Agregada ARS
            </span>
            <div className="text-2xl font-bold font-mono text-slate-100 mt-2">
              {formatMoney(metrics.cashArsTotal, "ARS")}
            </div>
            <span className="text-[10px] text-slate-400 mt-1">
              Disponible para liquidación T+1/T+2
            </span>
          </div>

          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm flex flex-col justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1.5">
              <DollarSign className="h-3.5 w-3.5 text-sky-400" />
              Caja Agregada USD
            </span>
            <div className="text-2xl font-bold font-mono text-slate-100 mt-2">
              {formatMoney(metrics.cashUsdTotal, "USD")}
            </div>
            <span className="text-[10px] text-slate-400 mt-1">
              Tesorería en divisa dura cable/MEP
            </span>
          </div>
        </div>
      )}

      {/* Filters & Search Bar */}
      {isAuthenticated && portfolios.length > 0 && (
        <div className="flex flex-col sm:flex-row items-center gap-3">
          <div className="relative flex-1 w-full">
            <Search className="h-4 w-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Buscar por nombre de cartera..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div className="flex items-center gap-1.5 w-full sm:w-auto">
            <Filter className="h-3.5 w-3.5 text-slate-400 shrink-0" />
            <select
              value={profileFilter}
              onChange={(e) => setProfileFilter(e.target.value)}
              className="bg-slate-900 border border-slate-800 text-slate-300 text-xs rounded-lg px-2.5 py-2 focus:outline-none focus:border-sky-500"
            >
              <option value="ALL">Todos los perfiles</option>
              <option value="CONSERVATIVE">Conservador</option>
              <option value="MODERATE">Moderado</option>
              <option value="AGGRESSIVE">Agresivo</option>
            </select>
          </div>
        </div>
      )}

      {/* Content Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-56 rounded-xl bg-slate-900/50 border border-slate-800 p-5 animate-pulse flex flex-col justify-between"
            >
              <div className="space-y-3">
                <div className="h-4 bg-slate-800 rounded w-2/3" />
                <div className="h-3 bg-slate-800/60 rounded w-1/3" />
                <div className="h-12 bg-slate-950 rounded mt-4" />
              </div>
              <div className="h-4 bg-slate-800/40 rounded w-full" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="p-8 rounded-xl bg-slate-900 border border-rose-800/40 text-center space-y-3">
          <AlertCircle className="h-8 w-8 text-rose-400 mx-auto" />
          <h3 className="text-sm font-semibold text-rose-200">
            Error al consultar portafolios
          </h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto">
            {error?.message ||
              "No se pudieron recuperar las carteras desde el servidor backend."}
          </p>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-white transition-colors"
          >
            Reintentar Consulta
          </button>
        </div>
      ) : filteredPortfolios.length === 0 ? (
        <div className="p-12 rounded-xl bg-slate-900/40 border border-dashed border-slate-800 text-center space-y-4">
          <div className="h-12 w-12 rounded-full bg-slate-800/60 flex items-center justify-center mx-auto text-slate-400">
            <Briefcase className="h-6 w-6" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              {searchQuery || profileFilter !== "ALL"
                ? "No se encontraron portafolios con los filtros seleccionados"
                : "No hay portafolios registrados aún"}
            </h3>
            <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
              {searchQuery || profileFilter !== "ALL"
                ? "Intenta modificar el término de búsqueda o selecciona otro perfil de riesgo."
                : "Crea tu primera cartera de inversión para comenzar a monitorear asignación, riesgo y balances."}
            </p>
          </div>

          {canCreate && !searchQuery && profileFilter === "ALL" && (
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium shadow-md shadow-sky-600/30 transition-all inline-flex items-center gap-2"
            >
              <Plus className="h-4 w-4" />
              <span>Crear Primera Cartera</span>
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredPortfolios.map((portfolio) => (
            <PortfolioCard
              key={portfolio.id}
              portfolio={portfolio}
              onSelect={onSelectPortfolio}
            />
          ))}
        </div>
      )}

      {/* Modal to Create Portfolio */}
      <CreatePortfolioModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
      />
    </div>
  );
};
