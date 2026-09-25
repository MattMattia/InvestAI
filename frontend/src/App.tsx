import React, { useEffect, useState } from "react";
import { api } from "./services/api";
import {
  HoldingCreatePayload,
  InvestorProfile,
  Portfolio,
  PortfolioListItem,
  RebalancePlan,
  RiskAssessmentReport,
  TargetAllocationInput,
} from "./types/portfolio";
import { Navbar } from "./components/Navbar";
import { MetricsOverview } from "./components/MetricsOverview";
import { AllocationChart } from "./components/AllocationChart";
import { HoldingsTable } from "./components/HoldingsTable";
import { FileUploader } from "./components/FileUploader";
import { RiskAlertsPanel } from "./components/RiskAlertsPanel";
import { RebalanceModal } from "./components/RebalanceModal";
import { Scale, Play, AlertCircle, Compass } from "lucide-react";

export const App: React.FC = () => {
  const [portfolios, setPortfolios] = useState<PortfolioListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentPortfolio, setCurrentPortfolio] = useState<Portfolio | null>(null);
  const [riskReport, setRiskReport] = useState<RiskAssessmentReport | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [evaluating, setEvaluating] = useState<boolean>(false);
  const [isRebalanceOpen, setIsRebalanceOpen] = useState<boolean>(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  // Load portfolios on mount
  useEffect(() => {
    loadPortfolios();
  }, []);

  const loadPortfolios = async () => {
    setLoading(true);
    setGlobalError(null);
    try {
      const list = await api.listPortfolios();
      setPortfolios(list);

      if (list.length > 0) {
        const idToSelect = selectedId && list.some((p) => p.id === selectedId) ? selectedId : list[0].id;
        setSelectedId(idToSelect);
        await loadPortfolioDetails(idToSelect);
      } else {
        // Create initial default portfolio with 0 initial cash
        const created = await api.createPortfolio({
          name: "Mi Cartera Principal",
          investor_profile: "MODERATE",
          cash_balance_ars: 0,
          cash_balance_usd: 0,
        });
        setPortfolios([created]);
        setSelectedId(created.id);
        setCurrentPortfolio(created);
      }
    } catch (err: any) {
      setGlobalError(
        "No se pudo conectar con el Backend FastAPI en http://127.0.0.1:8000. Asegúrate de que el servidor esté activo."
      );
    } finally {
      setLoading(false);
    }
  };

  const loadPortfolioDetails = async (id: string) => {
    try {
      const p = await api.getPortfolio(id);
      setCurrentPortfolio(p);
      // Auto-evaluate risk if there are holdings
      if (p.holdings.length > 0) {
        evaluateRisk(id);
      } else {
        setRiskReport(null);
      }
    } catch (err: any) {
      setGlobalError(err.message || "Error al cargar la cartera.");
    }
  };

  const handleSelectPortfolio = async (id: string) => {
    setSelectedId(id);
    await loadPortfolioDetails(id);
  };

  const handleCreatePortfolio = async (
    name: string,
    cashArs: number,
    cashUsd: number,
    profile: InvestorProfile
  ) => {
    setLoading(true);
    try {
      const created = await api.createPortfolio({
        name,
        investor_profile: profile,
        cash_balance_ars: cashArs,
        cash_balance_usd: cashUsd,
      });
      await loadPortfolios();
      setSelectedId(created.id);
      await loadPortfolioDetails(created.id);
    } catch (err: any) {
      setGlobalError(err.message || "Error al crear portafolio.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddHolding = async (payload: HoldingCreatePayload) => {
    if (!selectedId) return;
    try {
      await api.addHolding(selectedId, payload);
      await loadPortfolioDetails(selectedId);
    } catch (err: any) {
      setGlobalError(err.response?.data?.message || err.message || "Error al añadir la posición.");
    }
  };

  const handleDeleteHolding = async (holdingId: number) => {
    if (!selectedId) return;
    try {
      await api.deleteHolding(selectedId, holdingId);
      await loadPortfolioDetails(selectedId);
    } catch (err: any) {
      setGlobalError(err.message || "Error al eliminar la posición.");
    }
  };

  const handleUploadFile = async (file: File) => {
    if (!selectedId) throw new Error("No hay cartera seleccionada");
    return await api.uploadPortfolioFile(selectedId, file);
  };

  const evaluateRisk = async (pId?: string) => {
    const targetId = pId || selectedId;
    if (!targetId) return;
    setEvaluating(true);
    try {
      const report = await api.evaluatePortfolioRisk(targetId);
      setRiskReport(report);
    } catch (err: any) {
      setGlobalError(err.message || "Error al evaluar el riesgo del portafolio.");
    } finally {
      setEvaluating(false);
    }
  };

  const handleGenerateRebalance = async (targets: TargetAllocationInput[]): Promise<RebalancePlan> => {
    if (!selectedId) throw new Error("No hay cartera seleccionada");
    return await api.generatePortfolioRebalance(selectedId, { targets });
  };

  const activeProfile = currentPortfolio?.investor_profile || "MODERATE";
  const profileBadgeMap: Record<InvestorProfile, { label: string; cls: string }> = {
    CONSERVATIVE: {
      label: "Perfil Conservador",
      cls: "bg-emerald-950/80 text-emerald-400 border-emerald-800",
    },
    MODERATE: {
      label: "Perfil Moderado",
      cls: "bg-sky-950/80 text-sky-400 border-sky-800",
    },
    AGGRESSIVE: {
      label: "Perfil Agresivo",
      cls: "bg-purple-950/80 text-purple-400 border-purple-800",
    },
  };
  const activeProfileBadge = profileBadgeMap[activeProfile] || profileBadgeMap.MODERATE;

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans">
      <Navbar
        portfolios={portfolios}
        selectedPortfolioId={selectedId}
        currentProfile={currentPortfolio?.investor_profile}
        onSelectPortfolio={handleSelectPortfolio}
        onCreatePortfolio={handleCreatePortfolio}
        onRefresh={() => selectedId && loadPortfolioDetails(selectedId)}
        loading={loading}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Global Error Banner */}
        {globalError && (
          <div className="bg-rose-950/80 border border-rose-800 rounded-xl p-4 flex items-center justify-between text-rose-200 text-sm shadow-md">
            <div className="flex items-center space-x-3">
              <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
              <span>{globalError}</span>
            </div>
            <button
              onClick={() => setGlobalError(null)}
              className="text-xs font-semibold px-2 py-1 bg-rose-900 hover:bg-rose-800 rounded text-white"
            >
              Cerrar
            </button>
          </div>
        )}

        {/* Action Header Banner */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-slate-800/60 border border-slate-700/80 rounded-xl p-4 sm:p-5">
          <div>
            <div className="flex items-center space-x-2.5">
              <h2 className="text-xl font-bold text-white tracking-tight">
                {currentPortfolio ? currentPortfolio.name : "Cargando Cartera..."}
              </h2>
              {currentPortfolio && (
                <span
                  className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border ${activeProfileBadge.cls} inline-flex items-center space-x-1`}
                >
                  <Compass className="w-3 h-3 mr-1 inline" />
                  <span>{activeProfileBadge.label}</span>
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Gestión determinista de tenencias, valuación bimoneda y rebalanceo cuantitativo
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => evaluateRisk()}
              disabled={evaluating || !currentPortfolio || currentPortfolio.holdings.length === 0}
              className="flex items-center space-x-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-semibold px-3.5 py-2 rounded-lg transition shadow-md shadow-emerald-700/20"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>{evaluating ? "Evaluando..." : "Evaluar Riesgo"}</span>
            </button>

            <button
              onClick={() => setIsRebalanceOpen(true)}
              disabled={!currentPortfolio || currentPortfolio.holdings.length === 0}
              className="flex items-center space-x-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-semibold px-3.5 py-2 rounded-lg transition shadow-md shadow-sky-700/20"
            >
              <Scale className="w-3.5 h-3.5" />
              <span>Rebalancear por Bandas</span>
            </button>
          </div>
        </div>

        {/* 1. Metrics Overview */}
        <MetricsOverview portfolio={currentPortfolio} riskReport={riskReport} />

        {/* 2. Visual Distribution: Allocation by Asset Type & Sector */}
        <AllocationChart portfolio={currentPortfolio} />

        {/* 3. Holdings Table & Ingestion Upload Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          <div className="lg:col-span-2">
            <HoldingsTable
              holdings={currentPortfolio ? currentPortfolio.holdings : []}
              onAddHolding={handleAddHolding}
              onDeleteHolding={handleDeleteHolding}
            />
          </div>
          <div>
            <FileUploader
              portfolioId={selectedId}
              onUploadFile={handleUploadFile}
              onUploadSuccess={() => selectedId && loadPortfolioDetails(selectedId)}
            />
          </div>
        </div>

        {/* 4. Risk Assessment Panel */}
        <RiskAlertsPanel
          report={riskReport}
          onEvaluate={() => evaluateRisk()}
          loading={evaluating}
        />
      </main>

      {/* Modal Rebalanceo */}
      <RebalanceModal
        isOpen={isRebalanceOpen}
        onClose={() => setIsRebalanceOpen(false)}
        holdings={currentPortfolio ? currentPortfolio.holdings : []}
        onGeneratePlan={handleGenerateRebalance}
      />
    </div>
  );
};
