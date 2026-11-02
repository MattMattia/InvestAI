/**
 * Financial Formatting Utilities for InvestAI Enterprise Frontend.
 * Provides defensive decimal parsing, institutional bimonetary representations,
 * localized date-time rendering, and portfolio holding metrics calculation.
 */

import { Holding, HoldingWithMetrics } from "@/types/api";

/**
 * Safely parses any numeric or decimal string representation into a finite JavaScript number.
 * Returns 0 if null, undefined, invalid string, or non-finite (NaN / Infinity).
 */
export function parseDecimalSafe(
  value: string | number | null | undefined
): number {
  if (value === null || value === undefined) {
    return 0;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return 0;
    // Replace any localized commas if formatted as "1.234,56" or clean standard strings
    const cleaned = trimmed.replace(/,/g, "");
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

/**
 * Formats a numeric or decimal string value as institutional currency (ARS or USD).
 * Uses institutional convention: "$ " for ARS and "US$ " for USD with standard thousand separators.
 * Example: 1250000.5 -> "US$ 1.250.000,50" or "$ 1.250.000,50"
 */
export function formatMoney(
  amount: string | number | null | undefined,
  currency: "ARS" | "USD" = "USD"
): string {
  const num = parseDecimalSafe(amount);
  const formatter = new Intl.NumberFormat("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const prefix = currency === "ARS" ? "$ " : "US$ ";
  return `${prefix}${formatter.format(num)}`;
}

/**
 * Formats a date string (ISO 8601) to standard Argentina locale (es-AR).
 * Example: "2026-11-02T18:30:00Z" -> "02/11/2026 15:30"
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("es-AR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  } catch {
    return "—";
  }
}

/**
 * Formats a ratio as percentage with sign and 2 decimals.
 * Example: 0.125 -> "+12.50%", -0.04 -> "-4.00%"
 */
export function formatPercent(
  value: string | number | null | undefined,
  showSign: boolean = true
): string {
  const num = parseDecimalSafe(value);
  const pct = num * 100;
  const sign = showSign && pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

/**
 * Formats a ratio with semantic sign and metadata flags for financial chip styling.
 */
export function formatSignedPercent(
  value: string | number | null | undefined
): { text: string; isPositive: boolean; isZero: boolean } {
  const num = parseDecimalSafe(value);
  const pct = num * 100;
  const isZero = Math.abs(pct) < 0.005;
  const isPositive = !isZero && pct > 0;
  const sign = isPositive ? "+" : "";

  return {
    text: `${sign}${pct.toFixed(2)}%`,
    isPositive,
    isZero,
  };
}

/**
 * Formats raw numeric values with thousand separators.
 */
export function formatNumber(
  value: string | number | null | undefined,
  decimals: number = 2
): string {
  const num = parseDecimalSafe(value);
  return new Intl.NumberFormat("es-AR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
}

/**
 * Safely calculates holding financial metrics with strict zero-division protection.
 */
export function calculateHoldingMetrics(
  holding: Holding,
  totalPortfolioValue: number
): HoldingWithMetrics {
  const qty = parseDecimalSafe(holding.quantity);
  const buyPrice = parseDecimalSafe(holding.average_buy_price);
  const curPrice = parseDecimalSafe(holding.current_price);

  const marketValue = qty * curPrice;
  const costBasis = qty * buyPrice;
  const unrealizedPnl = marketValue - costBasis;
  const unrealizedPnlPct = costBasis > 0 ? unrealizedPnl / costBasis : 0;
  const weightPct =
    totalPortfolioValue > 0 ? (marketValue / totalPortfolioValue) * 100 : 0;

  const rawCurrency = holding.asset?.currency?.toUpperCase();
  const currency: "ARS" | "USD" = rawCurrency === "USD" ? "USD" : "ARS";

  return {
    id: holding.id,
    portfolio_id: holding.portfolio_id,
    asset_ticker: holding.asset_ticker,
    quantity: qty,
    average_buy_price: buyPrice,
    current_price: curPrice,
    market_value: marketValue,
    cost_basis: costBasis,
    unrealized_pnl: unrealizedPnl,
    unrealized_pnl_pct: unrealizedPnlPct,
    weight_pct: weightPct,
    currency,
    asset: holding.asset,
  };
}

/**
 * Normalizes an audit report payload into a JavaScript object.
 * Safely parses JSON strings or returns native objects, with fallback to an empty object.
 */
export function normalizeSnapshotPayload(
  payload: unknown
): Record<string, unknown> {
  if (!payload) return {};
  if (typeof payload === "object" && !Array.isArray(payload)) {
    return payload as Record<string, unknown>;
  }
  if (typeof payload === "string") {
    try {
      const parsed = JSON.parse(payload);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      return { raw: payload };
    }
  }
  return {};
}
