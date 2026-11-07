/**
 * TanStack Query v5 Key Factory for InvestAI Enterprise Frontend.
 * Provides hierarchical, strongly-typed query keys for optimal cache management and invalidation.
 */

export const portfolioKeys = {
  all: ["portfolios"] as const,
  lists: () => [...portfolioKeys.all, "list"] as const,
  list: (filters?: Record<string, unknown>) => [...portfolioKeys.lists(), filters] as const,
  details: () => [...portfolioKeys.all, "detail"] as const,
  detail: (id: string) => [...portfolioKeys.details(), id] as const,
};

export const snapshotKeys = {
  all: ["snapshots"] as const,
  byPortfolio: (portfolioId: string) => [...snapshotKeys.all, "portfolio", portfolioId] as const,
};

export const systemKeys = {
  all: ["system"] as const,
  health: () => [...systemKeys.all, "health"] as const,
  metrics: () => [...systemKeys.all, "metrics"] as const,
};

export const authKeys = {
  all: ["auth"] as const,
  me: () => [...authKeys.all, "me"] as const,
};

export const marketKeys = {
  all: ["market"] as const,
  quotes: (category?: string) => [...marketKeys.all, "quotes", category || "ALL"] as const,
  quote: (ticker: string) => [...marketKeys.all, "quote", ticker] as const,
  status: () => [...marketKeys.all, "status"] as const,
  history: (ticker: string, timeframe?: string) =>
    [...marketKeys.all, "history", ticker, timeframe || "1D"] as const,
};

export const orderKeys = {
  all: ["orders"] as const,
  lists: () => [...orderKeys.all, "list"] as const,
  list: (portfolioId?: string) => [...orderKeys.lists(), portfolioId || "all"] as const,
  details: () => [...orderKeys.all, "detail"] as const,
  detail: (id: string) => [...orderKeys.details(), id] as const,
};
