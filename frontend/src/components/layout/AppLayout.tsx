/**
 * Institutional Application Layout for InvestAI Enterprise.
 * Unifies fixed Sidebar, TopHeader, and dedicated responsive scrollable viewport.
 */

import React from "react";
import { NavSection, Sidebar } from "./Sidebar";
import { TopHeader } from "./TopHeader";

interface AppLayoutProps {
  activeSection: NavSection;
  portfolioId?: string | null;
  onNavigate: (section: NavSection) => void;
  onOpenAuthModal: () => void;
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  activeSection,
  portfolioId,
  onNavigate,
  onOpenAuthModal,
  children,
}) => {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 font-sans selection:bg-sky-500 selection:text-white">
      {/* Institutional Left Sidebar */}
      <Sidebar activeSection={activeSection} onNavigate={onNavigate} />

      {/* Main Viewport Column */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Sticky Top Header */}
        <TopHeader
          activeSection={activeSection}
          portfolioId={portfolioId}
          onOpenAuthModal={onOpenAuthModal}
        />

        {/* Scrollable Content Body */}
        <main className="flex-1 overflow-y-auto px-6 py-8">
          <div className="max-w-7xl mx-auto w-full">{children}</div>
        </main>

        {/* Institutional Status Sub-Footer */}
        <footer className="h-9 border-t border-slate-800/80 bg-slate-950 px-6 flex items-center justify-between text-[11px] text-slate-400 select-none">
          <div className="flex items-center gap-3">
            <span>InvestAI Enterprise — Quantitative Portfolio & Risk Engineering</span>
            <span className="text-slate-400">•</span>
            <span className="font-mono">Proxy /api/v1 -&gt; FastAPI 0.115</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span className="font-mono">Engine: Online</span>
          </div>
        </footer>
      </div>
    </div>
  );
};

