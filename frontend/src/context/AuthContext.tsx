/**
 * React Authentication Context for InvestAI Enterprise Frontend.
 * Manages synchronous token inspection, initial profile hydration, multi-tab sync,
 * live RBAC / investor profile hot-swapping, and secure cache purges upon session termination.
 */

import { useQueryClient } from "@tanstack/react-query";
import type React from "react";
import { createContext, type ReactNode, useEffect, useState } from "react";
import { authStorage } from "@/lib/authStorage";
import { authService, type UpdateProfilePayload } from "@/services/authService";
import type { LoginCredentials, RegisterData, User } from "@/types/api";

export interface AuthContextType {
	user: User | null;
	isAuthenticated: boolean;
	isLoading: boolean;
	isAdmin: boolean;
	isTrader: boolean;
	isViewer: boolean;
	login: (credentials: LoginCredentials) => Promise<void>;
	register: (data: RegisterData) => Promise<void>;
	updateUserProfile: (payload: UpdateProfilePayload) => Promise<User>;
	logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextType | undefined>(
	undefined,
);

interface AuthProviderProps {
	children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
	const queryClient = useQueryClient();

	// Synchronous initial state based on persistent storage
	const [user, setUser] = useState<User | null>(null);
	const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => {
		return Boolean(authStorage.getAccessToken());
	});
	const [isLoading, setIsLoading] = useState<boolean>(() => {
		return Boolean(authStorage.getAccessToken());
	});

	const isAdmin = user?.role === "ADMIN";
	const isTrader = user?.role === "TRADER";
	const isViewer = user?.role === "VIEWER";

	// Initial Profile Hydration
	useEffect(() => {
		let isMounted = true;
		const hasToken = Boolean(authStorage.getAccessToken());

		if (!hasToken) {
			setIsLoading(false);
			setIsAuthenticated(false);
			setUser(null);
			return;
		}

		authService
			.getCurrentUser()
			.then((currentUser) => {
				if (isMounted) {
					setUser(currentUser);
					setIsAuthenticated(true);
					setIsLoading(false);
				}
			})
			.catch((err) => {
				if (isMounted) {
					console.warn(
						"Session token expired or invalid, clearing session:",
						err,
					);
					authStorage.clearTokens();
					setUser(null);
					setIsAuthenticated(false);
					setIsLoading(false);
				}
			});

		return () => {
			isMounted = false;
		};
	}, []);

	// Multi-tab Session Synchronization
	useEffect(() => {
		const handleStorageChange = (event: StorageEvent) => {
			if (
				event.key === "investai_access_token" ||
				event.key === "investai_refresh_token"
			) {
				if (event.newValue === null) {
					// Tokens were purged in another tab: clear memory & query cache immediately
					queryClient.cancelQueries();
					queryClient.clear();
					setUser(null);
					setIsAuthenticated(false);
					setIsLoading(false);
				} else if (event.newValue && !user) {
					// Tokens appeared in another tab: rehydrate profile
					setIsLoading(true);
					authService
						.getCurrentUser()
						.then((currentUser) => {
							setUser(currentUser);
							setIsAuthenticated(true);
						})
						.catch(() => {
							setUser(null);
							setIsAuthenticated(false);
						})
						.finally(() => {
							setIsLoading(false);
						});
				}
			}
		};

		window.addEventListener("storage", handleStorageChange);

		// Intra-tab listener
		const unsubscribe = authStorage.subscribe((tokens) => {
			if (!tokens) {
				setUser(null);
				setIsAuthenticated(false);
			}
		});

		return () => {
			window.removeEventListener("storage", handleStorageChange);
			unsubscribe();
		};
	}, [user, queryClient]);

	const login = async (credentials: LoginCredentials): Promise<void> => {
		try {
			setIsLoading(true);
			await authService.login(credentials);
			const currentUser = await authService.getCurrentUser();
			setUser(currentUser);
			setIsAuthenticated(true);
		} catch (err) {
			authStorage.clearTokens();
			setUser(null);
			setIsAuthenticated(false);
			throw err;
		} finally {
			setIsLoading(false);
		}
	};

	const register = async (data: RegisterData): Promise<void> => {
		try {
			setIsLoading(true);
			await authService.register(data);
			// Auto-authenticate newly registered user
			await authService.login({
				email: data.email,
				password: data.password,
			});
			// Immediately assign operational TRADER role and selected investor_profile
			const updatedUser = await authService.updateProfile({
				role: "TRADER",
				investor_profile: data.investor_profile || "MODERATE",
			});
			setUser(updatedUser);
			setIsAuthenticated(true);
		} catch (err) {
			throw err;
		} finally {
			setIsLoading(false);
		}
	};

	const updateUserProfile = async (
		payload: UpdateProfilePayload,
	): Promise<User> => {
		const updatedUser = await authService.updateProfile(payload);
		setUser(updatedUser);
		await queryClient.invalidateQueries();
		return updatedUser;
	};

	const logout = async (): Promise<void> => {
		try {
			await queryClient.cancelQueries();
			queryClient.clear();
			await authService.logout();
		} finally {
			setUser(null);
			setIsAuthenticated(false);
		}
	};

	const value: AuthContextType = {
		user,
		isAuthenticated,
		isLoading,
		isAdmin,
		isTrader,
		isViewer,
		login,
		register,
		updateUserProfile,
		logout,
	};

	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
