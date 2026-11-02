/**
 * Comprehensive Portfolio Detail View Component for InvestAI Enterprise.
 * Orchestrates PortfolioKPIHeader, Detail Navigation Tabs (Holdings vs Rebalance),
 * AssetAllocationDonut, HoldingsTable, and RebalancePanel with URL-synchronized state.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  PieChart,
  RefreshCw,
  Scale,
  Shield,
} from "lucide-react";
import { usePortfolio } from "@/hooks/usePortfolios";
import { navigateToPortfoliosList, useHashRoute } from "@/lib/navigation";
import { parseDecimalSafe } from "@/lib/formatters";
import { orderKeys } from "@/lib/queryKeys";
import { orderService } from "@/services/orderService";
import { OrderExecutionModal } from "@/components/orders/OrderExecutionModal";
import { RecentOrdersTable } from "@/components/orders/RecentOrdersTable";
import { AssetAllocationDonut } from "./AssetAllocationDonut";
import { AuditCompliancePanel } from "./AuditCompliancePanel";
import { HoldingsTable } from "./HoldingsTable";
import { PortfolioKPIHeader } from "./PortfolioKPIHeader";
import { RebalancePanel } from "./RebalancePanel";

interface PortfolioDetailViewProps {
  portfolioId: string;
}

export const PortfolioDetailView: React.FC<PortfolioDetailViewProps> = ({
  portfolioId,
}) => {
  const { tab, navigateToPortfolioTab } = useHashRoute();
  const [isOrderModalOpen, setIsOrderModalOpen] = useState<boolean>(false);
  const {
    data: portfolio,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = usePortfolio(portfolioId);

  const { data: recentOrders = [], isLoading: isLoadingOrders } = useQuery({
    queryKey: orderKeys.list(portfolioId),
    queryFn: () => orderService.getRecentOrders(portfolioId),
    enabled: Boolean(portfolioId),
    staleTime: 15_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        {/* Header Skeleton */}
        <div className="h-28 rounded-xl bg-slate-900/60 border border-slate-800 p-6 flex flex-col justify-between">
          <div className="h-6 w-1/3 bg-slate-800 rounded" />
          <div className="grid grid-cols-6 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-12 bg-slate-800/60 rounded" />
            ))}
          </div>
        </div>

        {/* Tab skeleton */}
        <div className="h-10 w-64 bg-slate-800/40 rounded" />

        {/* Donut Skeleton */}
        <div className="h-64 rounded-xl bg-slate-900/60 border border-slate-800 p-6 flex items-center justify-center">
          <div className="h-44 w-44 rounded-full border-8 border-slate-800 flex items-center justify-center text-xs text-slate-500 font-mono">
            Cargando portafolio...
          </div>
        </div>
      </div>
    );
  }

  if (isError || !portfolio) {
    return (
      <div className="p-10 rounded-xl bg-slate-900 border border-rose-800/40 text-center space-y-4">
        <AlertCircle className="h-10 w-10 text-rose-400 mx-auto" />
        <h2 className="text-base font-semibold text-rose-200">
          No se pudo cargar la información del portafolio
        </h2>
        <p className="text-xs text-slate-400 max-w-md mx-auto">
          {error?.message ||
            "Es posible que el portafolio no exista o no dispongas de permisos para acceder a esta cartera."}
        </p>

        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            onClick={() => navigateToPortfoliosList()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 font-medium transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Volver a Portafolios</span>
          </button>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs text-white font-medium transition-colors"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
            />
            <span>Reintentar</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Analytic KPI Header */}
      <PortfolioKPIHeader
        portfolio={portfolio}
        onNewOrder={() => setIsOrderModalOpen(true)}
      />

      {/* Detail Navigation Tabs */}
      <div className="flex border-b border-slate-800 gap-2">
        <button
          onClick={() => navigateToPortfolioTab(portfolioId, "holdings")}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-medium border-b-2 transition-colors ${
            tab === "holdings"
              ? "border-sky-500 text-sky-400 bg-slate-900/40"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <PieChart className="h-4 w-4" />
          <span>Tenencias y Asignación</span>
        </button>

        <button
          onClick={() => navigateToPortfolioTab(portfolioId, "rebalance")}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-medium border-b-2 transition-colors ${
            tab === "rebalance"
              ? "border-sky-500 text-sky-400 bg-slate-900/40"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Scale className="h-4 w-4" />
          <span>Rebalanceo y Bandas FSM</span>
        </button>

        <button
          onClick={() => navigateToPortfolioTab(portfolioId, "audit")}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-mono font-medium border-b-2 transition-colors ${
            tab === "audit"
              ? "border-sky-500 text-sky-400 bg-slate-900/40"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Shield className="h-4 w-4" />
          <span>Auditoría y Snapshots</span>
        </button>
      </div>

      {/* Tab 1: Holdings & Donut */}
      {tab === "holdings" && (
        <div className="space-y-6">
          <AssetAllocationDonut portfolio={portfolio} initialCurrency="ARS" />
          <HoldingsTable portfolio={portfolio} />
        </div>
      )}

      {/* Tab 2: Tolerance Bands & FSM Orders */}
      {tab === "rebalance" && (
        <div className="space-y-6">
          <RebalancePanel portfolio={portfolio} />
          <RecentOrdersTable orders={recentOrders} isLoading={isLoadingOrders} />
        </div>
      )}

      {/* Tab 3: Risk Audit Compliance & Snapshots */}
      {tab === "audit" && <AuditCompliancePanel portfolio={portfolio} />}

      {/* Manual Assisted Order Execution Modal */}
      {isOrderModalOpen && (
        <OrderExecutionModal
          isOpen={isOrderModalOpen}
          onClose={() => setIsOrderModalOpen(false)}
          initialPortfolioId={portfolio.id}
          initialCurrency={
            parseDecimalSafe(portfolio.cash_balance_usd) > 0 ? "USD" : "ARS"
          }
        />
      )}
    </div>
  );
};
