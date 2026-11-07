export interface Asset {
	ticker: string;
	name: string;
	asset_type: string;
	currency: string;
	sector: string;
	market: string;
	cedear_ratio?: number | null;
	underlying_ticker?: string | null;
}

export interface Holding {
	id: number;
	portfolio_id: string;
	asset_ticker: string;
	quantity: number;
	average_buy_price: number;
	current_price: number;
	total_cost: number;
	market_value: number;
	unrealized_pnl: number;
	unrealized_pnl_pct: number;
	weight_pct?: number | null;
	asset?: Asset | null;
}

export type InvestorProfile = "CONSERVATIVE" | "MODERATE" | "AGGRESSIVE";

export interface PortfolioListItem {
	id: string;
	user_id: string;
	name: string;
	investor_profile?: InvestorProfile;
	cash_balance_ars: number;
	cash_balance_usd: number;
	total_market_value_ars: number;
	holdings_count: number;
	updated_at: string;
}

export interface Portfolio {
	id: string;
	user_id: string;
	name: string;
	investor_profile?: InvestorProfile;
	cash_balance_ars: number;
	cash_balance_usd: number;
	total_market_value_ars: number;
	total_market_value_usd: number;
	holdings_count: number;
	holdings: Holding[];
	updated_at: string;
}

export interface HoldingCreatePayload {
	ticker: string;
	quantity: number;
	average_buy_price: number;
	current_price: number;
	currency?: string;
	market?: string;
	asset_type?: string;
	sector?: string;
}

export interface PortfolioCreatePayload {
	name: string;
	investor_profile?: InvestorProfile;
	cash_balance_ars?: number;
	cash_balance_usd?: number;
	holdings?: HoldingCreatePayload[];
}

export interface PortfolioUpdatePayload {
	name?: string;
	investor_profile?: InvestorProfile | string;
	cash_balance_ars?: number;
	cash_balance_usd?: number;
}

export interface RuleResult {
	rule_id: string;
	rule_name: string;
	severity: "INFO" | "WARNING" | "CRITICAL";
	passed: boolean;
	message: string;
	details: Record<string, unknown>;
	timestamp: string;
}

export interface RiskAssessmentReport {
	portfolio_id: string;
	portfolio_name: string;
	compliance_status: "COMPLIANT" | "WARNING" | "NON_COMPLIANT";
	total_rules_evaluated: number;
	passed_rules_count: number;
	failed_rules_count: number;
	critical_alerts_count: number;
	warning_alerts_count: number;
	evaluated_at: string;
	results: RuleResult[];
	snapshot_id?: string | null;
}

export interface IngestionReport {
	portfolio_id: string;
	total_rows: number;
	valid_records_count: number;
	discarded_records_count: number;
	is_successful: boolean;
	has_partial_errors: boolean;
	errors: Array<{
		row?: number;
		ticker?: string;
		error_type: string;
		message?: string;
		detail?: string;
	}>;
}

export interface TargetAllocationInput {
	ticker: string;
	target_weight: number;
	tolerance_band?: number;
}

export interface RebalanceRequest {
	targets: TargetAllocationInput[];
	custom_prices?: Record<string, number>;
	fx_ccl?: number;
	include_hold?: boolean;
}

export interface RebalanceOrder {
	ticker: string;
	side: "BUY" | "SELL" | "HOLD";
	current_weight: number;
	target_weight: number;
	delta_weight: number;
	delta_amount: number;
	estimated_shares: number;
	price_used: number;
	justification: string;
}

export interface RebalancePlan {
	portfolio_id: string;
	orders: RebalanceOrder[];
	total_buy_amount: number;
	total_sell_amount: number;
	net_cash_flow: number;
	available_cash: number;
	is_liquidity_sufficient: boolean;
	liquidity_warning?: string | null;
}
