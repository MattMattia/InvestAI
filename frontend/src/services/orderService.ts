/**
 * Order Execution Service for InvestAI Enterprise Frontend.
 * Interacts with FastAPI /api/v1/orders endpoints with strict idempotency headers,
 * pre-trade cost computation for BYMA/CNV market orders, and FSM execution/cancellation.
 */

import { apiClient } from "@/lib/apiClient";
import {
	calculateOrderCostBreakdown,
	inferAssetNativeCurrency,
} from "@/lib/formatters";
import type { CreateOrderPayload, OrderRecord, OrderStatus } from "@/types/api";

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

function mapBackendOrderToRecord(
	item: BackendOrderDTO,
	orderTypeFallback: "MARKET" | "LIMIT" = "MARKET",
): OrderRecord {
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
		order_type: orderTypeFallback,
		quantity: shares,
		price,
		gross_amount: breakdown.grossAmount,
		total_fees: breakdown.totalFees,
		net_amount: breakdown.netTotal,
		status: (item.status.toUpperCase() as OrderStatus) || "PENDING",
		justification: item.justification,
		created_at: item.created_at || new Date().toISOString(),
	};
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

		const cleanTicker = payload.ticker.trim().toUpperCase();
		const nativeCurrency = inferAssetNativeCurrency(
			cleanTicker,
			payload.currency || "ARS",
		);

		const requestBody = {
			portfolio_id: payload.portfolio_id,
			ticker: cleanTicker,
			side: payload.side,
			order_type: payload.order_type,
			quantity: payload.quantity,
			price: payload.price,
			currency: nativeCurrency,
			justification:
				payload.justification ||
				"Operación manual asistida con cómputo de aranceles",
		};

		const response = await apiClient.post<
			BackendOrderDTO | { data: BackendOrderDTO }
		>("/orders", requestBody, {
			headers: {
				"Idempotency-Key": idempotencyKey,
			},
		});

		const raw = response.data;
		const item: BackendOrderDTO =
			raw && typeof raw === "object" && "data" in raw
				? (raw as { data: BackendOrderDTO }).data
				: (raw as BackendOrderDTO);

		return mapBackendOrderToRecord(item, payload.order_type);
	},

	/**
	 * Executes and settles an order in the FSM (transitioning to EXECUTED and updating portfolio cash & holdings).
	 */
	async executeOrder(orderId: string): Promise<OrderRecord> {
		const response = await apiClient.post<
			BackendOrderDTO | { data: BackendOrderDTO }
		>(`/orders/${encodeURIComponent(orderId)}/execute`);
		const raw = response.data;
		const item: BackendOrderDTO =
			raw && typeof raw === "object" && "data" in raw
				? (raw as { data: BackendOrderDTO }).data
				: (raw as BackendOrderDTO);

		return mapBackendOrderToRecord(item, "MARKET");
	},

	/**
	 * Cancels an active order in the FSM (transitioning to CANCELLED).
	 */
	async cancelOrder(orderId: string, reason?: string): Promise<OrderRecord> {
		const response = await apiClient.post<
			BackendOrderDTO | { data: BackendOrderDTO }
		>(
			`/orders/${encodeURIComponent(orderId)}/cancel`,
			reason ? { reason } : {},
		);
		const raw = response.data;
		const item: BackendOrderDTO =
			raw && typeof raw === "object" && "data" in raw
				? (raw as { data: BackendOrderDTO }).data
				: (raw as BackendOrderDTO);

		return mapBackendOrderToRecord(item, "MARKET");
	},

	/**
	 * Retrieves recent orders across all user portfolios or scoped to a specific portfolio.
	 */
	async getRecentOrders(portfolioId?: string): Promise<OrderRecord[]> {
		const params = portfolioId ? { portfolio_id: portfolioId } : undefined;
		const response = await apiClient.get<
			BackendOrderDTO[] | { data: BackendOrderDTO[] }
		>("/orders", { params });

		const raw = response.data;
		const list: BackendOrderDTO[] = Array.isArray(raw)
			? raw
			: raw &&
					typeof raw === "object" &&
					"data" in raw &&
					Array.isArray((raw as any).data)
				? (raw as any).data
				: [];

		return list.map((item) => mapBackendOrderToRecord(item, "MARKET"));
	},
};
