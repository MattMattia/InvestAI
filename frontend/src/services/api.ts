import axios from "axios";
import {
  Holding,
  HoldingCreatePayload,
  IngestionReport,
  Portfolio,
  PortfolioCreatePayload,
  PortfolioListItem,
  PortfolioUpdatePayload,
  RebalancePlan,
  RebalanceRequest,
  RiskAssessmentReport,
} from "../types/portfolio";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api/v1";

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

export const api = {
  // Portfolios CRUD
  async listPortfolios(): Promise<PortfolioListItem[]> {
    const res = await apiClient.get<PortfolioListItem[]>("/portfolios");
    return res.data;
  },

  async createPortfolio(data: PortfolioCreatePayload): Promise<Portfolio> {
    const res = await apiClient.post<Portfolio>("/portfolios", data);
    return res.data;
  },

  async getPortfolio(id: string): Promise<Portfolio> {
    const res = await apiClient.get<Portfolio>(`/portfolios/${id}`);
    return res.data;
  },

  async updatePortfolio(id: string, data: PortfolioUpdatePayload): Promise<Portfolio> {
    const res = await apiClient.patch<Portfolio>(`/portfolios/${id}`, data);
    return res.data;
  },

  async deletePortfolio(id: string): Promise<{ status: string; portfolio_id: string }> {
    const res = await apiClient.delete<{ status: string; portfolio_id: string }>(`/portfolios/${id}`);
    return res.data;
  },

  // Holdings
  async addHolding(portfolioId: string, data: HoldingCreatePayload): Promise<Holding> {
    const res = await apiClient.post<Holding>(`/portfolios/${portfolioId}/holdings`, data);
    return res.data;
  },

  async deleteHolding(portfolioId: string, holdingId: number): Promise<{ status: string; holding_id: number }> {
    const res = await apiClient.delete<{ status: string; holding_id: number }>(
      `/portfolios/${portfolioId}/holdings/${holdingId}`
    );
    return res.data;
  },

  // Ingestion File Upload
  async uploadPortfolioFile(portfolioId: string, file: File): Promise<IngestionReport> {
    const formData = new FormData();
    formData.append("file", file);

    const res = await apiClient.post<IngestionReport>(
      `/portfolios/${portfolioId}/upload`,
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    );
    return res.data;
  },

  // Deterministic Risk Engine Evaluation
  async evaluatePortfolioRisk(portfolioId: string, fxCcl: number = 1300.0): Promise<RiskAssessmentReport> {
    const res = await apiClient.get<RiskAssessmentReport>(
      `/portfolios/${portfolioId}/evaluate`,
      {
        params: { fx_ccl: fxCcl },
      }
    );
    return res.data;
  },

  // Tolerance-band Rebalancing Engine
  async generatePortfolioRebalance(
    portfolioId: string,
    data: RebalanceRequest
  ): Promise<RebalancePlan> {
    const res = await apiClient.post<RebalancePlan>(
      `/portfolios/${portfolioId}/rebalance`,
      data
    );
    return res.data;
  },
};
