/**
 * Financial Formatting Utilities for InvestAI Enterprise Frontend.
 * Provides defensive decimal parsing, institutional bimonetary representations,
 * and localized date-time rendering.
 */

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
 * Formats with 2 decimal places and standard thousand grouping separators.
 * Example: 1250000.5 -> "USD 1,250,000.50" or "ARS 1,250,000.50"
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

  return `${currency} ${formatter.format(num)}`;
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

