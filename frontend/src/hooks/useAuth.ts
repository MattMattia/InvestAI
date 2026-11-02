/**
 * Hook to consume the InvestAI Authentication Context.
 * Guarantees invocation inside an AuthProvider.
 */

import { useContext } from "react";
import { AuthContext, AuthContextType } from "@/context/AuthContext";

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be invoked within an AuthProvider");
  }
  return context;
};

