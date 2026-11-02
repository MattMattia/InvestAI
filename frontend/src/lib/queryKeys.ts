/**
 * TanStack Query v5 Key Factory for InvestAI Enterprise Frontend.
 * Provides hierarchical, strongly-typed query keys for optimal cache management and invalidation.
 */

export const portfolioKeys = {
  all: ["portfolios"] as const,
  lists: () => [...portfolioKeys.all, "list"] as const,
  list: (filters?: Record<string, unknown>) =>
    [...portfolioKeys.lists(), filters] as const,
  details: () => [...portfolioKeys.all, "detail"] as const,
  detail: (id: string) => [...portfolioKeys.details(), id] as const,
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

