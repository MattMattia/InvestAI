/**
 * Enterprise Axios HTTP Client for InvestAI.
 * Features:
 * - Distributed request tracing with unique X-Request-ID (UUIDv4)
 * - Automatic JWT Bearer authorization header injection
 * - Thread-safe (promise-based) token refresh mutex queue preventing stampedes on 401
 * - Normalized ApiError abstraction with Pydantic 422 validation detail parsing
 */

import axios, {
	type AxiosError,
	type AxiosInstance,
	type AxiosResponse,
	type InternalAxiosRequestConfig,
} from "axios";
import { type AuthTokens, authStorage } from "./authStorage";

export interface ValidationErrorDetail {
	field?: string | null;
	issue: string;
}

export class ApiError extends Error {
	public status: number;
	public code?: string;
	public detail: string;
	public traceId?: string | null;
	public validationErrors?: ValidationErrorDetail[];
	public raw?: unknown;

	constructor(
		message: string,
		status: number,
		options?: {
			code?: string;
			detail?: string;
			traceId?: string | null;
			validationErrors?: ValidationErrorDetail[];
			raw?: unknown;
		},
	) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.code = options?.code;
		this.detail = options?.detail || message;
		this.traceId = options?.traceId;
		this.validationErrors = options?.validationErrors;
		this.raw = options?.raw;
		Object.setPrototypeOf(this, ApiError.prototype);
	}
}

/**
 * Normalizes any error (AxiosError, Error, or unknown) into a structured ApiError.
 */
export function normalizeError(error: unknown): ApiError {
	if (error instanceof ApiError) {
		return error;
	}

	if (axios.isAxiosError(error) && error.response) {
		const status = error.response.status;
		const data = error.response.data as Record<string, unknown> | undefined;

		// Extract X-Request-ID from response headers or envelope meta
		const headerTrace =
			(error.response.headers?.["x-request-id"] as string | undefined) || null;
		const metaTrace =
			data?.meta && typeof data.meta === "object"
				? (data.meta as Record<string, unknown>).request_id
				: null;
		const traceId = (metaTrace as string | null) || headerTrace;

		// Parse Error Detail and Code
		const errorObj =
			data?.error && typeof data.error === "object"
				? (data.error as Record<string, unknown>)
				: undefined;

		const code =
			(errorObj?.code as string | undefined) ||
			(status === 422 ? "VALIDATION_ERROR" : `HTTP_${status}`);

		const detailMessage =
			(errorObj?.message as string | undefined) ||
			(typeof data?.detail === "string"
				? data.detail
				: "An unexpected server error occurred.");

		// Extract 422 Pydantic Validation Errors
		let validationErrors: ValidationErrorDetail[] | undefined;
		if (errorObj?.details && Array.isArray(errorObj.details)) {
			validationErrors = errorObj.details.map((d: Record<string, unknown>) => ({
				field: typeof d.field === "string" ? d.field : null,
				issue: typeof d.issue === "string" ? d.issue : String(d),
			}));
		} else if (Array.isArray(data?.detail)) {
			validationErrors = (data.detail as Array<Record<string, unknown>>).map(
				(err) => ({
					field: Array.isArray(err.loc) ? err.loc.join(".") : null,
					issue: String(err.msg || "Validation error"),
				}),
			);
		}

		return new ApiError(detailMessage, status, {
			code,
			detail: detailMessage,
			traceId,
			validationErrors,
			raw: data,
		});
	}

	if (error instanceof Error) {
		return new ApiError(error.message, 0, { detail: error.message });
	}

	return new ApiError("Network or transport failure", 0, {
		detail: String(error),
	});
}

function generateRequestId(): string {
	if (
		typeof crypto !== "undefined" &&
		typeof crypto.randomUUID === "function"
	) {
		return `req-${crypto.randomUUID()}`;
	}
	return `req-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

// Global Refresh Mutex State
let isRefreshing = false;
interface QueueItem {
	resolve: (value: AxiosResponse | PromiseLike<AxiosResponse>) => void;
	reject: (reason?: unknown) => void;
	config: InternalAxiosRequestConfig;
}
let failedQueue: QueueItem[] = [];

function processQueue(error: unknown, token: string | null = null): void {
	failedQueue.forEach((prom) => {
		if (error) {
			prom.reject(error);
		} else if (token) {
			prom.config.headers.Authorization = `Bearer ${token}`;
			apiClient(prom.config).then(prom.resolve).catch(prom.reject);
		}
	});
	failedQueue = [];
}

const rawBaseUrl =
	(typeof import.meta !== "undefined" &&
		import.meta.env &&
		import.meta.env.VITE_API_BASE_URL) ||
	"/api/v1";

export const apiClient: AxiosInstance = axios.create({
	baseURL: rawBaseUrl,
	timeout: 15000,
	headers: {
		"Content-Type": "application/json",
		Accept: "application/json",
	},
});

// Request Interceptor: Auth Bearer, Multipart FormData Boundary, and X-Request-ID Injection
apiClient.interceptors.request.use(
	(config: InternalAxiosRequestConfig) => {
		// 0. If payload is FormData, remove default application/json Content-Type so browser sets multipart boundary
		if (typeof FormData !== "undefined" && config.data instanceof FormData) {
			if (typeof config.headers?.delete === "function") {
				config.headers.delete("Content-Type");
			} else if (config.headers) {
				delete config.headers["Content-Type"];
			}
		}

		// 1. Inject distributed trace header
		if (!config.headers["X-Request-ID"]) {
			config.headers["X-Request-ID"] = generateRequestId();
		}

		// 2. Inject Authorization token if not already set
		const token = authStorage.getAccessToken();
		if (token && !config.headers.Authorization) {
			config.headers.Authorization = `Bearer ${token}`;
		}

		return config;
	},
	(error: unknown) => Promise.reject(normalizeError(error)),
);

// Response Interceptor: 401 Refresh Mutex Queue
apiClient.interceptors.response.use(
	(response: AxiosResponse) => response,
	async (error: AxiosError) => {
		const originalRequest = error.config as
			| (InternalAxiosRequestConfig & { _retry?: boolean })
			| undefined;

		if (!originalRequest) {
			return Promise.reject(normalizeError(error));
		}

		const requestUrl = originalRequest.url || "";
		const isAuthEndpoint =
			requestUrl.includes("/auth/token") ||
			requestUrl.includes("/auth/refresh") ||
			requestUrl.includes("/auth/register");

		// If 401 and not an authentication endpoint
		if (error.response?.status === 401 && !isAuthEndpoint) {
			if (originalRequest._retry) {
				// Already retried once and still 401: clear session
				authStorage.clearTokens();
				return Promise.reject(normalizeError(error));
			}

			// Mark request as retried
			originalRequest._retry = true;

			if (isRefreshing) {
				// Enqueue request until active refresh completes
				return new Promise<AxiosResponse>((resolve, reject) => {
					failedQueue.push({ resolve, reject, config: originalRequest });
				});
			}

			isRefreshing = true;
			const currentRefreshToken = authStorage.getRefreshToken();

			if (!currentRefreshToken) {
				isRefreshing = false;
				authStorage.clearTokens();
				return Promise.reject(normalizeError(error));
			}

			try {
				// Perform atomic refresh using isolated axios instance to prevent interceptor loops
				const refreshResponse = await axios.post(
					`${apiClient.defaults.baseURL}/auth/refresh`,
					{ refresh_token: currentRefreshToken },
					{
						headers: {
							"Content-Type": "application/json",
							"X-Request-ID": generateRequestId(),
						},
					},
				);

				const data = refreshResponse.data as Record<string, unknown>;
				const payloadData =
					data.data && typeof data.data === "object"
						? (data.data as Record<string, unknown>)
						: data;

				const newAccessToken = String(payloadData.access_token || "");
				const newRefreshToken = String(
					payloadData.refresh_token || currentRefreshToken,
				);

				if (!newAccessToken) {
					throw new Error(
						"Invalid token refresh payload received from backend",
					);
				}

				const tokens: AuthTokens = {
					accessToken: newAccessToken,
					refreshToken: newRefreshToken,
				};

				authStorage.setTokens(tokens);

				// Notify and drain all enqueued requests
				processQueue(null, newAccessToken);

				// Retry original request with newly acquired access token
				originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
				return apiClient(originalRequest);
			} catch (refreshErr) {
				authStorage.clearTokens();
				processQueue(refreshErr, null);
				return Promise.reject(normalizeError(refreshErr));
			} finally {
				isRefreshing = false;
			}
		}

		return Promise.reject(normalizeError(error));
	},
);

export type ErrorMessageField = "detail" | "message" | "error.message";

/**
 * Extracts a human-readable message from an unknown thrown value.
 * Looks at the HTTP response body fields (in the given order), then at the
 * error's own `message`, and finally falls back to the provided text.
 */
export function extractErrorMessage(
	error: unknown,
	fallback: string,
	fields: ErrorMessageField[] = ["detail", "message", "error.message"],
): string {
	const asRecord = (value: unknown): Record<string, unknown> | undefined =>
		value && typeof value === "object"
			? (value as Record<string, unknown>)
			: undefined;

	const err = asRecord(error);
	const data = asRecord(asRecord(err?.response)?.data);

	for (const field of fields) {
		const value =
			field === "error.message"
				? asRecord(data?.error)?.message
				: data?.[field];
		if (value) {
			return typeof value === "string" ? value : JSON.stringify(value);
		}
	}

	if (typeof err?.message === "string" && err.message) {
		return err.message;
	}
	return fallback;
}
