/**
 * Order Execution Service for InvestAI Enterprise Frontend.
 * Interacts with FastAPI /api/v1/orders endpoints with strict idempotency headers
 * and pre-trade cost computation for BYMA/CNV market orders.
 */

import { apiClient } from "@/lib/apiClient";
import { calculateOrderCostBreakdown } from "@/lib/formatters";
import { CreateOrderPayload, OrderRecord, OrderStatus } from "@/types/api";

interface BackendOrderDTO {
  id: string;
  portfolio_id: string;
  ticker: string;
  side: string;
  estimated_shares: number;
  price_used: number;
  delta_amount: number;
  status: string;
  justification?: string;
  created_at: string;
}

export const orderService = {
  /**
   * Dispatches a validated market or limit order with an idempotency key header.
   */
  async createOrder(payload: CreateOrderPayload): Promise<OrderRecord> {
    const idempotencyKey =
      payload.idempotency_key ||
      (typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `ord-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`);

    const requestBody = {
      portfolio_id: payload.portfolio_id,
      ticker: payload.ticker.trim().toUpperCase(),
      side: payload.side,
      order_type: payload.order_type,
      quantity: payload.quantity,
      price: payload.price,
      currency: payload.currency || "ARS",
      justification: payload.justification || "Operación manual asistida con cómputo de aranceles",
    };

    const response = await apiClient.post<BackendOrderDTO | { data: BackendOrderDTO }>(
      "/orders",
      requestBody,
      {
        headers: {
          "Idempotency-Key": idempotencyKey,
        },
      }
    );

    const raw = response.data;
    const item: BackendOrderDTO =
      raw && typeof raw === "object" && "data" in raw
        ? (raw as { data: BackendOrderDTO }).data
        : (raw as BackendOrderDTO);

    const shares = item.estimated_shares || payload.quantity;
    const price = item.price_used || payload.price || 0;
    const breakdown = calculateOrderCostBreakdown({
      quantity: shares,
      price,
      side: payload.side,
    });

    return {
      id: item.id,
      portfolio_id: item.portfolio_id,
      ticker: item.ticker,
      side: item.side.toUpperCase() as "BUY" | "SELL",
      order_type: payload.order_type,
      quantity: shares,
      price,
      gross_amount: breakdown.grossAmount,
      total_fees: breakdown.totalFees,
      net_amount: breakdown.netTotal,
      status: (item.status.toUpperCase() as OrderStatus) || "PENDING",
      justification: item.justification,
      created_at: item.created_at || new Date().toISOString(),
    };
  },

  /**
   * Retrieves recent orders across all user portfolios or scoped to a specific portfolio.
   */
  async getRecentOrders(portfolioId?: string): Promise<OrderRecord[]> {
    const params = portfolioId ? { portfolio_id: portfolioId } : undefined;
    const response = await apiClient.get<BackendOrderDTO[] | { data: BackendOrderDTO[] }>(
      "/orders",
      { params }
    );

    const raw = response.data;
    const list: BackendOrderDTO[] = Array.isArray(raw)
      ? raw
      : raw && typeof raw === "object" && "data" in raw && Array.isArray((raw as any).data)
      ? (raw as any).data
      : [];

    return list.map((item) => {
      const shares = item.estimated_shares || 1;
      const price = item.price_used || 0;
      const side = (item.side || "BUY").toUpperCase() as "BUY" | "SELL";
      const breakdown = calculateOrderCostBreakdown({
        quantity: shares,
        price,
        side,
      });

      return {
        id: item.id,
        portfolio_id: item.portfolio_id,
        ticker: item.ticker,
        side,
        order_type: "MARKET",
        quantity: shares,
        price,
        gross_amount: breakdown.grossAmount,
        total_fees: breakdown.totalFees,
        net_amount: breakdown.netTotal,
        status: (item.status.toUpperCase() as OrderStatus) || "PENDING",
        justification: item.justification,
        created_at: item.created_at,
      };
    });
  },
};

