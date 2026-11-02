/**
 * Canonical TypeScript Domain & API Contracts mirroring FastAPI Backend Models.
 * Synchronized 1:1 with InvestAI Core Specifications.
 */

// Domain Enums & Literals
export type UserRole = "VIEWER" | "TRADER" | "ADMIN";

export type InvestorProfile = "CONSERVATIVE" | "MODERATE" | "AGGRESSIVE";

export type OrderStatus =
  | "PENDING"
  | "VALIDATED"
  | "ROUTED"
  | "EXECUTED"
  | "FAILED"
  | "REJECTED";

export type OrderSide = "BUY" | "SELL";

export type MarketCloseJobStatus =
  | "SCHEDULED"
  | "RUNNING"
  | "COMPLETED"
  | "PARTIALLY_COMPLETED"
  | "SKIPPED_HOLIDAY"
  | "SKIPPED_ALREADY_RUNNING"
  | "FAILED";

export type MarketCloseTriggerType =
  | "AUTOMATIC_SCHEDULE"
  | "MANUAL_OVERRIDE"
  | "BACKTEST_SIMULATION";

// Canonical Entity Contracts
export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  investor_profile?: InvestorProfile;
}

export interface Asset {
  ticker: string;
  name: string;
  asset_type: string;
  currency: string;
  sector: string;
  market: string;
  cedear_ratio?: number | null;
}

export interface Holding {
  id: number;
  portfolio_id: string;
  asset_ticker: string;
  quantity: number | string;
  average_buy_price: number | string;
  current_price: number | string;
  total_cost?: number | string;
  market_value?: number | string;
  unrealized_pnl?: number | string;
  unrealized_pnl_pct?: number | string;
  weight_pct?: number | string | null;
  asset?: Asset | null;
}

export interface HoldingWithMetrics {
  id: number;
  portfolio_id: string;
  asset_ticker: string;
  quantity: number;
  average_buy_price: number;
  current_price: number;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight_pct: number;
  currency: "ARS" | "USD";
  asset?: Asset | null;
}

export interface Portfolio {
  id: string;
  user_id: string;
  name: string;
  investor_profile: InvestorProfile | string;
  cash_balance_ars: number | string;
  cash_balance_usd: number | string;
  total_market_value_ars?: number | string;
  total_market_value_usd?: number | string;
  holdings_count?: number;
  holdings?: Holding[];
  created_at?: string;
  updated_at?: string;
}

export interface PortfolioCreateInput {
  name: string;
  investor_profile?: InvestorProfile | string;
  cash_balance_ars?: number | string;
  cash_balance_usd?: number | string;
  holdings?: Array<{
    ticker: string;
    quantity: number;
    average_buy_price?: number;
    current_price?: number;
    currency?: string;
    market?: string;
    asset_type?: string;
    sector?: string;
  }>;
}

export interface RebalanceOrder {
  id?: string;
  portfolio_id: string;
  ticker: string;
  side: OrderSide | string;
  current_weight: string | number;
  target_weight: string | number;
  delta_weight?: string | number;
  delta_amount: string | number;
  estimated_shares: string | number;
  price_used: string | number;
  status: OrderStatus | string;
  justification?: string;
  created_at?: string;
}

export interface ToleranceBandItem {
  ticker: string;
  current_weight: number;
  target_weight: number;
  lower_band: number;
  upper_band: number;
  is_breached: boolean;
  breach_direction: "UPPER" | "LOWER" | "NONE";
  delta_weight: number;
}

export interface RebalanceSimulationResult {
  portfolio_id: string;
  needs_rebalancing: boolean;
  total_portfolio_value: number;
  base_currency: "ARS" | "USD";
  breached_tickers: string[];
  orders: RebalanceOrder[];
  generated_at: string;
  total_buy_amount?: number;
  total_sell_amount?: number;
  net_cash_flow?: number;
  available_cash?: number;
  is_liquidity_sufficient?: boolean;
  liquidity_warning?: string | null;
}

export interface RiskAuditSnapshot {
  id: string;
  portfolio_id: string;
  compliance_status: "COMPLIANCE_OK" | "BREACH_DETECTED" | string;
  total_rules_evaluated?: number;
  critical_alerts_count: number;
  notification_status?: string;
  report_payload: Record<string, unknown> | string;
  created_at: string;
  metrics?: Record<string, unknown>;
}

export interface PortfolioCloseProcessResult {
  portfolio_id: string;
  status: "SUCCESS" | "FAILED" | "SKIPPED";
  total_portfolio_value: string;
  needs_rebalancing: boolean;
  breached_tickers: string[];
  orders_generated_count: number;
  fsm_batch_id: string | null;
  error_message: string | null;
  snapshot_id?: string | null;
}

export interface MarketCloseJobReport {
  job_id: string;
  target_date: string;
  trigger_type: MarketCloseTriggerType;
  status: MarketCloseJobStatus;
  portfolios_evaluated: number;
  portfolios_succeeded: number;
  portfolios_failed: number;
  portfolios_skipped: number;
  orders_generated_total: number;
  duration_seconds: number;
  dry_run: boolean;
  base_currency: "ARS" | "USD";
  portfolio_results: PortfolioCloseProcessResult[];
}

// API Envelopes
export interface ResponseMeta {
  request_id: string;
  timestamp?: string;
}

export interface APIResponse<T> {
  success: boolean;
  data: T;
  meta: ResponseMeta;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in?: number;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  password: string;
  full_name: string;
  investor_profile?: InvestorProfile;
}

// Broker Statement Ingestion Contracts
export interface BrokerReportUploadResponse {
  job_id?: string;
  filename: string;
  detected_broker?: string;
  total_rows_parsed: number;
  valid_records_count: number;
  rejected_records_count: number;
  message: string;
  portfolio_id?: string;
  created_at?: string;
  reconciliation?: {
    mode?: string;
    holdings_added?: number;
    holdings_updated?: number;
    holdings_removed?: number;
    warnings?: string[];
  };
  warnings?: string[];
}

// Market Data & Real-Time BYMA Contracts
export interface MarketQuote {
  ticker: string;
  name: string;
  asset_type: "STOCK" | "CEDEAR" | "BOND" | "OTHER";
  currency: "ARS" | "USD";
  last_price: number;
  open_price?: number;
  high_price?: number;
  low_price?: number;
  previous_close?: number;
  change_pct: number;
  change_nominal: number;
  volume_shares?: number;
  volume_amount?: number;
  updated_at: string;
}

export interface MarketStatusInfo {
  is_open: boolean;
  market_name: string;
  timezone: string;
  current_time: string;
  next_change: string;
  message: string;
}

export interface HistoricalBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// Order Execution Contracts
export interface CreateOrderPayload {
  portfolio_id: string;
  ticker: string;
  side: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT";
  quantity: number;
  price?: number;
  currency?: "ARS" | "USD";
  justification?: string;
  idempotency_key?: string;
}

export interface OrderRecord {
  id: string;
  portfolio_id: string;
  ticker: string;
  side: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT";
  quantity: number;
  price: number;
  gross_amount: number;
  total_fees: number;
  net_amount: number;
  status: OrderStatus;
  justification?: string;
  created_at: string;
}

