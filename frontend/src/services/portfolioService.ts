/**
 * Portfolio Service for InvestAI Frontend.
 * Interacts with FastAPI /api/v1/portfolios endpoints.
 */

import { apiClient } from "@/lib/apiClient";
import { parseDecimalSafe } from "@/lib/formatters";
import { APIResponse, Portfolio, PortfolioCreateInput } from "@/types/api";

export const portfolioService = {
  /**
   * Retrieves all investment portfolios accessible to the current user.
   * Handles both direct array responses and standardized APIResponse<{ data: [...] }> envelopes.
   */
  async getPortfolios(): Promise<Portfolio[]> {
    const response = await apiClient.get<
      Portfolio[] | APIResponse<Portfolio[]>
    >("/portfolios");

    const data = response.data;
    if (Array.isArray(data)) {
      return data;
    }
    if (data && typeof data === "object" && "data" in data) {
      const inner = (data as APIResponse<Portfolio[]>).data;
      if (Array.isArray(inner)) {
        return inner;
      }
    }
    return [];
  },

  /**
   * Retrieves full details, positions and valuations of a specific portfolio by ID.
   */
  async getPortfolioById(id: string): Promise<Portfolio> {
    const response = await apiClient.get<Portfolio | APIResponse<Portfolio>>(
      `/portfolios/${encodeURIComponent(id)}`
    );

    const data = response.data;
    if (data && typeof data === "object" && "data" in data) {
      return (data as APIResponse<Portfolio>).data;
    }
    return data as Portfolio;
  },

  /**
   * Creates a new investment portfolio.
   * Sanitizes and parses cash balances into numeric floats expected by FastAPI PortfolioCreate.
   */
  async createPortfolio(data: PortfolioCreateInput): Promise<Portfolio> {
    const payload = {
      name: data.name.trim(),
      investor_profile: (data.investor_profile || "MODERATE").toString().toUpperCase(),
      cash_balance_ars: parseDecimalSafe(data.cash_balance_ars),
      cash_balance_usd: parseDecimalSafe(data.cash_balance_usd),
      holdings: data.holdings?.map((h) => ({
        ticker: h.ticker.trim().toUpperCase(),
        quantity: parseDecimalSafe(h.quantity),
        average_buy_price: parseDecimalSafe(h.average_buy_price),
        current_price: parseDecimalSafe(h.current_price),
        currency: h.currency || "ARS",
        market: h.market || "BYMA",
        asset_type: h.asset_type,
        sector: h.sector || "OTHER",
      })),
    };

    const response = await apiClient.post<Portfolio | APIResponse<Portfolio>>(
      "/portfolios",
      payload
    );

    const resData = response.data;
    if (resData && typeof resData === "object" && "data" in resData) {
      return (resData as APIResponse<Portfolio>).data;
    }
    return resData as Portfolio;
  },
};

