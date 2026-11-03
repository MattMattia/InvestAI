/**
 * Portfolio Service for InvestAI Frontend.
 * Interacts with FastAPI /api/v1/portfolios endpoints, including Rebalance Engine execution.
 */

import { apiClient } from "@/lib/apiClient";
import { parseDecimalSafe } from "@/lib/formatters";
import {
  APIResponse,
  OrderSide,
  OrderStatus,
  Portfolio,
  PortfolioCreateInput,
  RebalanceSimulationResult,
  RiskAuditSnapshot,
} from "@/types/api";

interface BackendRebalanceOrder {
  ticker: string;
  side: string;
  current_weight: number;
  target_weight: number;
  delta_weight: number;
  delta_amount: number;
  estimated_shares: number;
  price_used: number;
  justification: string;
}

interface BackendRebalancePlan {
  portfolio_id: string;
  orders: BackendRebalanceOrder[];
  total_buy_amount: number;
  total_sell_amount: number;
  net_cash_flow: number;
  available_cash: number;
  is_liquidity_sufficient: boolean;
  liquidity_warning?: string | null;
}

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

  /**
   * Simulates portfolio rebalancing against tolerance bands via the backend engine.
   * If custom targets are not supplied, constructs normalized equal-weight allocations
   * from the active portfolio holdings.
   */
  async simulateRebalance(
    portfolioId: string,
    params: {
      tolerance_pct?: number;
      cash_buffer_pct?: number;
      base_currency?: "ARS" | "USD";
      targets?: Array<{
        ticker: string;
        target_weight: number;
        tolerance_band?: number;
      }>;
    }
  ): Promise<RebalanceSimulationResult> {
    let targets = params.targets;
    const defaultTolerance = params.tolerance_pct ?? 5.0;

    if (!targets || targets.length === 0) {
      const port = await portfolioService.getPortfolioById(portfolioId);
      const holdings = port.holdings || [];
      const count = holdings.length;

      if (count > 0) {
        const equalWeight = Number((100 / count).toFixed(2));
        targets = holdings.map((h) => ({
          ticker: h.asset_ticker,
          target_weight: equalWeight,
          tolerance_band: defaultTolerance,
        }));
      } else {
        targets = [];
      }
    }

    if (targets.length === 0) {
      return {
        portfolio_id: portfolioId,
        needs_rebalancing: false,
        total_portfolio_value: 0,
        base_currency: params.base_currency || "ARS",
        breached_tickers: [],
        orders: [],
        generated_at: new Date().toISOString(),
        is_liquidity_sufficient: true,
      };
    }

    const payload = {
      targets: targets.map((t) => ({
        ticker: t.ticker.trim().toUpperCase(),
        target_weight: parseDecimalSafe(t.target_weight),
        tolerance_band:
          t.tolerance_band !== undefined
            ? parseDecimalSafe(t.tolerance_band)
            : defaultTolerance,
      })),
      include_hold: false,
    };

    const response = await apiClient.post<
      BackendRebalancePlan | APIResponse<BackendRebalancePlan>
    >(`/portfolios/${encodeURIComponent(portfolioId)}/rebalance`, payload, {
      params: { dry_run: true },
    });

    const resData = response.data;
    const plan: BackendRebalancePlan =
      resData && typeof resData === "object" && "data" in resData
        ? (resData as APIResponse<BackendRebalancePlan>).data
        : (resData as BackendRebalancePlan);

    const actionableOrders = (plan.orders || []).filter(
      (o) => o.side !== "HOLD"
    );

    const breachedTickers = actionableOrders.map((o) => o.ticker);

    return {
      portfolio_id: plan.portfolio_id,
      needs_rebalancing: actionableOrders.length > 0,
      total_portfolio_value:
        (plan.available_cash || 0) + (plan.total_buy_amount || 0),
      base_currency: params.base_currency || "ARS",
      breached_tickers: breachedTickers,
      orders: actionableOrders.map((o) => ({
        portfolio_id: plan.portfolio_id,
        ticker: o.ticker,
        side: o.side as OrderSide,
        current_weight: o.current_weight,
        target_weight: o.target_weight,
        delta_weight: o.delta_weight,
        delta_amount: o.delta_amount,
        estimated_shares: o.estimated_shares,
        price_used: o.price_used,
        status: "PENDING" as OrderStatus,
        justification: o.justification,
        created_at: new Date().toISOString(),
      })),
      generated_at: new Date().toISOString(),
      total_buy_amount: plan.total_buy_amount,
      total_sell_amount: plan.total_sell_amount,
      net_cash_flow: plan.net_cash_flow,
      available_cash: plan.available_cash,
      is_liquidity_sufficient: plan.is_liquidity_sufficient,
      liquidity_warning: plan.liquidity_warning,
    };
  },

  /**
   * Retrieves historical immutable risk audit snapshots for a given portfolio.
   */
  async getPortfolioSnapshots(
    portfolioId: string
  ): Promise<RiskAuditSnapshot[]> {
    const response = await apiClient.get<
      RiskAuditSnapshot[] | APIResponse<RiskAuditSnapshot[]>
    >(`/portfolios/${encodeURIComponent(portfolioId)}/snapshots`);

    const data = response.data;
    if (Array.isArray(data)) {
      return data;
    }
    if (data && typeof data === "object" && "data" in data) {
      const inner = (data as APIResponse<RiskAuditSnapshot[]>).data;
      if (Array.isArray(inner)) {
        return inner;
      }
    }
    return [];
  },

  /**
   * Triggers a live forensic risk assessment on the portfolio, evaluating all rules
   * and saving an immutable RiskAuditSnapshotModel in the database.
   */
  async triggerAuditSnapshot(
    portfolioId: string
  ): Promise<RiskAuditSnapshot> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/portfolios/${encodeURIComponent(portfolioId)}/evaluate`
    );

    const data = (response.data?.data ||
      response.data) as Record<string, unknown>;
    const snapshotId = String(data.snapshot_id || `snap-${Date.now()}`);

    const snapshot: RiskAuditSnapshot = {
      id: snapshotId,
      portfolio_id: portfolioId,
      compliance_status: (data.compliance_status as string) || "COMPLIANCE_OK",
      total_rules_evaluated: Number(data.total_rules_evaluated || 0),
      critical_alerts_count: Number(data.critical_alerts_count || 0),
      notification_status: "EVALUATED",
      report_payload: data,
      created_at: (data.evaluated_at as string) || new Date().toISOString(),
    };

    return snapshot;
  },

  /**
   * Updates portfolio metadata (name, investor_profile) or cash balances (cash_balance_ars, cash_balance_usd).
   */
  async updatePortfolio(
    portfolioId: string,
    payload: {
      name?: string;
      investor_profile?: string;
      cash_balance_ars?: number;
      cash_balance_usd?: number;
    }
  ): Promise<Portfolio> {
    const response = await apiClient.patch<Portfolio | APIResponse<Portfolio>>(
      `/portfolios/${encodeURIComponent(portfolioId)}`,
      payload
    );
    const resData = response.data;
    if (resData && typeof resData === "object" && "data" in resData) {
      return (resData as APIResponse<Portfolio>).data;
    }
    return resData as Portfolio;
  },

  /**
   * Deletes an existing portfolio by ID.
   */
  async deletePortfolio(
    portfolioId: string
  ): Promise<{ status: string; portfolio_id: string; message?: string }> {
    const response = await apiClient.delete<{
      status: string;
      portfolio_id: string;
      message?: string;
    }>(`/portfolios/${encodeURIComponent(portfolioId)}`);
    return response.data;
  },
};
