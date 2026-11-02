/**
 * URL-First Hash Navigation and Deep-Linking Router for InvestAI Enterprise Frontend.
 * Manages synchronized hash routing (#portfolios, #portfolios?id=<uuid>&tab=<tab>, #health, #metrics).
 */

import { useEffect, useState } from "react";

export type NavSection = "portfolios" | "health" | "metrics";
export type DetailTab = "holdings" | "rebalance" | "audit";

export interface HashRoute {
  section: NavSection;
  portfolioId: string | null;
  tab: DetailTab;
}

/**
 * Parses current window.location.hash into section, optional portfolioId, and detail tab.
 */
export function parseHashRoute(): HashRoute {
  if (typeof window === "undefined") {
    return { section: "portfolios", portfolioId: null, tab: "holdings" };
  }

  const rawHash = window.location.hash.replace(/^#/, "").trim();
  if (!rawHash) {
    return { section: "portfolios", portfolioId: null, tab: "holdings" };
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
  let tab: DetailTab = "holdings";

  if (queryString) {
    const params = new URLSearchParams(queryString);
    const id = params.get("id");
    if (id && id.trim()) {
      portfolioId = id.trim();
    }
    const rawTab = params.get("tab")?.toLowerCase();
    if (rawTab === "rebalance") {
      tab = "rebalance";
    } else if (rawTab === "audit") {
      tab = "audit";
    }
  }

  return { section, portfolioId, tab };
}

/**
 * Deep-links into the detail view of an investment portfolio with an optional tab.
 */
export function navigateToPortfolioDetail(
  id: string,
  tab: DetailTab = "holdings"
): void {
  if (typeof window !== "undefined") {
    const tabSuffix = tab !== "holdings" ? `&tab=${tab}` : "";
    window.location.hash = `#portfolios?id=${encodeURIComponent(id)}${tabSuffix}`;
  }
}

/**
 * Switches the active tab inside a portfolio detail view.
 */
export function navigateToPortfolioTab(id: string, tab: DetailTab): void {
  if (typeof window !== "undefined") {
    const tabSuffix = tab !== "holdings" ? `&tab=${tab}` : "";
    window.location.hash = `#portfolios?id=${encodeURIComponent(id)}${tabSuffix}`;
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
  navigateToPortfolioDetail: (id: string, tab?: DetailTab) => void;
  navigateToPortfolioTab: (id: string, tab: DetailTab) => void;
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
    navigateToPortfolioTab,
    navigateToPortfoliosList,
    navigateToSection,
  };
}
