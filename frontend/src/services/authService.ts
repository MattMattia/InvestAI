/**
 * Authentication Service for InvestAI Frontend.
 * Interacts with FastAPI /api/v1/auth endpoints using structured JSON envelopes.
 */

import { apiClient } from "@/lib/apiClient";
import { authStorage } from "@/lib/authStorage";
import {
  APIResponse,
  AuthTokenResponse,
  LoginCredentials,
  RegisterData,
  User,
} from "@/types/api";

export const authService = {
  /**
   * Authenticates user credentials against /auth/login and stores JWT pair in storage.
   */
  async login(credentials: LoginCredentials): Promise<AuthTokenResponse> {
    const response = await apiClient.post<APIResponse<AuthTokenResponse>>(
      "/auth/login",
      {
        email: credentials.email.trim().toLowerCase(),
        password: credentials.password,
      }
    );

    const tokenData =
      response.data?.data || (response.data as unknown as AuthTokenResponse);

    if (!tokenData.access_token || !tokenData.refresh_token) {
      throw new Error("Invalid token envelope returned from login endpoint.");
    }

    authStorage.setTokens({
      accessToken: tokenData.access_token,
      refreshToken: tokenData.refresh_token,
    });

    return tokenData;
  },

  /**
   * Registers a new user account with /auth/register.
   * Note: omits extra fields to prevent 422 errors under backend extra="forbid".
   */
  async register(data: RegisterData): Promise<User> {
    const payload = {
      email: data.email.trim().toLowerCase(),
      full_name: data.full_name.trim(),
      password: data.password,
    };

    const response = await apiClient.post<APIResponse<User>>(
      "/auth/register",
      payload
    );

    return response.data?.data || (response.data as unknown as User);
  },

  /**
   * Retrieves the authenticated user profile via /auth/me.
   */
  async getCurrentUser(): Promise<User> {
    const response = await apiClient.get<APIResponse<User>>("/auth/me");
    return response.data?.data || (response.data as unknown as User);
  },

  /**
   * Cleanses the active session and token storage.
   */
  async logout(): Promise<void> {
    try {
      // Optional backend session revocation hook
    } finally {
      authStorage.clearTokens();
    }
  },
};

