/**
 * Auth Storage Abstraction for InvestAI Enterprise Frontend.
 * Provides type-safe token persistence, lifecycle event broadcasting, and local storage safety.
 */

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

export type AuthChangeListener = (tokens: AuthTokens | null) => void;

class AuthStorage {
  private static ACCESS_TOKEN_KEY = "investai_access_token";
  private static REFRESH_TOKEN_KEY = "investai_refresh_token";
  private listeners: Set<AuthChangeListener> = new Set();

  /**
   * Retrieves the current access token.
   */
  getAccessToken(): string | null {
    try {
      return localStorage.getItem(AuthStorage.ACCESS_TOKEN_KEY);
    } catch {
      return null;
    }
  }

  /**
   * Retrieves the current refresh token.
   */
  getRefreshToken(): string | null {
    try {
      return localStorage.getItem(AuthStorage.REFRESH_TOKEN_KEY);
    } catch {
      return null;
    }
  }

  /**
   * Retrieves both tokens as a unified AuthTokens object.
   */
  getTokens(): AuthTokens | null {
    const accessToken = this.getAccessToken();
    const refreshToken = this.getRefreshToken();
    if (accessToken && refreshToken) {
      return { accessToken, refreshToken };
    }
    return null;
  }

  /**
   * Atomically persists new tokens and notifies active listeners.
   */
  setTokens(tokens: AuthTokens): void {
    try {
      localStorage.setItem(AuthStorage.ACCESS_TOKEN_KEY, tokens.accessToken);
      localStorage.setItem(AuthStorage.REFRESH_TOKEN_KEY, tokens.refreshToken);
      this.notifyListeners(tokens);
    } catch (err) {
      console.error("Failed to persist auth tokens to storage:", err);
    }
  }

  /**
   * Updates the access token preserving the existing refresh token.
   */
  setAccessToken(accessToken: string): void {
    const refreshToken = this.getRefreshToken();
    if (refreshToken) {
      this.setTokens({ accessToken, refreshToken });
    } else {
      try {
        localStorage.setItem(AuthStorage.ACCESS_TOKEN_KEY, accessToken);
      } catch (err) {
        console.error("Failed to persist access token:", err);
      }
    }
  }

  /**
   * Purges all tokens from storage and broadcasts null session event.
   */
  clearTokens(): void {
    try {
      localStorage.removeItem(AuthStorage.ACCESS_TOKEN_KEY);
      localStorage.removeItem(AuthStorage.REFRESH_TOKEN_KEY);
      this.notifyListeners(null);
    } catch (err) {
      console.error("Failed to clear auth tokens from storage:", err);
    }
  }

  /**
   * Subscribes a listener to session token changes.
   * Returns an unsubscribe function.
   */
  subscribe(listener: AuthChangeListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notifyListeners(tokens: AuthTokens | null): void {
    this.listeners.forEach((listener) => {
      try {
        listener(tokens);
      } catch (err) {
        console.error("Error invoking auth storage listener:", err);
      }
    });
  }
}

export const authStorage = new AuthStorage();

