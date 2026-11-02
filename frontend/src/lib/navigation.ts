/**
 * URL-First Hash Navigation and Deep-Linking Router for InvestAI Enterprise Frontend.
 * Manages synchronized hash routing (#portfolios, #portfolios?id=<uuid>, #health, #metrics).
 */

import { useEffect, useState } from "react";

export type NavSection = "portfolios" | "health" | "metrics";

export interface HashRoute {
  section: NavSection;
  portfolioId: string | null;
}

/**
 * Parses current window.location.hash into section and optional portfolioId query param.
 */
export function parseHashRoute(): HashRoute {
  if (typeof window === "undefined") {
    return { section: "portfolios", portfolioId: null };
  }

  const rawHash = window.location.hash.replace(/^#/, "").trim();
  if (!rawHash) {
    return { section: "portfolios", portfolioId: null };
  }

  const [path, queryString] = rawHash.split("?");
  const sectionLower = path.toLowerCase();

  let section: NavSection = "portfolios";
  if (sectionLower === "health") {
    section = "health";
  } else if (sectionLower === "metrics") {
    section = "metrics";
  }

  let portfolioId: string | null = null;
  if (queryString) {
    const params = new URLSearchParams(queryString);
    const id = params.get("id");
    if (id && id.trim()) {
      portfolioId = id.trim();
    }
  }

  return { section, portfolioId };
}

/**
 * Deep-links into the detail view of an investment portfolio.
 */
export function navigateToPortfolioDetail(id: string): void {
  if (typeof window !== "undefined") {
    window.location.hash = `#portfolios?id=${encodeURIComponent(id)}`;
  }
}

/**
 * Returns to the primary portfolios catalog list.
 */
export function navigateToPortfoliosList(): void {
  if (typeof window !== "undefined") {
    window.location.hash = "#portfolios";
  }
}

/**
 * Navigates to a top-level section.
 */
export function navigateToSection(section: NavSection): void {
  if (typeof window !== "undefined") {
    window.location.hash = `#${section}`;
  }
}

/**
 * React hook to observe and navigate URL-first hash routes with strict lifecycle cleanup.
 */
export function useHashRoute(): HashRoute & {
  navigateToPortfolioDetail: (id: string) => void;
  navigateToPortfoliosList: () => void;
  navigateToSection: (section: NavSection) => void;
} {
  const [route, setRoute] = useState<HashRoute>(parseHashRoute);

  useEffect(() => {
    const handleHashChange = () => {
      setRoute(parseHashRoute());
    };

    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  return {
    ...route,
    navigateToPortfolioDetail,
    navigateToPortfoliosList,
    navigateToSection,
  };
}

