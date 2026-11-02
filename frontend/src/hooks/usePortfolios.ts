/**
 * React Query Hooks for Investment Portfolios in InvestAI Enterprise Frontend.
 * Uses TanStack Query v5 object syntax, central query keys, and automatic cache invalidation.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  UseQueryResult,
  UseMutationResult,
} from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { portfolioKeys } from "@/lib/queryKeys";
import { portfolioService } from "@/services/portfolioService";
import { Portfolio, PortfolioCreateInput } from "@/types/api";

/**
 * Hook to retrieve all investment portfolios accessible to the authenticated user.
 */
export function usePortfolios(): UseQueryResult<Portfolio[], Error> {
  const { isAuthenticated } = useAuth();

  return useQuery({
    queryKey: portfolioKeys.lists(),
    queryFn: () => portfolioService.getPortfolios(),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

/**
 * Hook to retrieve a single investment portfolio by ID with holdings and valuations.
 */
export function usePortfolio(id: string): UseQueryResult<Portfolio, Error> {
  const { isAuthenticated } = useAuth();

  return useQuery({
    queryKey: portfolioKeys.detail(id),
    queryFn: () => portfolioService.getPortfolioById(id),
    enabled: isAuthenticated && Boolean(id),
    staleTime: 30_000,
  });
}

/**
 * Hook to create a new investment portfolio and invalidate portfolio lists upon success.
 */
export function useCreatePortfolio(): UseMutationResult<
  Portfolio,
  Error,
  PortfolioCreateInput
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: PortfolioCreateInput) =>
      portfolioService.createPortfolio(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
    },
  });
}

