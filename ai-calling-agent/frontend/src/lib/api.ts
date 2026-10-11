import type { ApiErrorBody, TokenPair } from "@/types/api";

const BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

/**
 * The request never reached the server.
 *
 * Worth its own type: a dead backend used to surface as whatever generic
 * message the calling screen happened to use ("Could not draft the agent"),
 * which sends you looking in entirely the wrong place.
 */
export class NetworkError extends Error {
  constructor(
    message = "Cannot reach the server. Check that the backend is running.",
  ) {
    super(message);
    this.name = "NetworkError";
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field-level messages from a 422, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    if (!Array.isArray(this.details)) return {};
    const out: Record<string, string> = {};
    for (const item of this.details) {
      const entry = item as { field?: string; message?: string };
      if (entry?.field && entry.message && !(entry.field in out))
        out[entry.field] = entry.message;
    }
    return out;
  }
}

/**
 * Token access is injected by the auth store rather than imported, so this
 * module stays free of React and free of a circular dependency on the store.
 */
interface TokenBridge {
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  onRefreshed: (tokens: TokenPair) => void;
  onSessionLost: () => void;
}

let bridge: TokenBridge = {
  getAccessToken: () => null,
  getRefreshToken: () => null,
  onRefreshed: () => {},
  onSessionLost: () => {},
};

export function configureApi(next: TokenBridge): void {
  bridge = next;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = "http_error";
  let message = response.statusText || "Request failed";
  let details: unknown;
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details;
    }
  } catch {
    // Non-JSON error body (proxy timeout, gateway page); keep the status text.
  }
  return new ApiError(response.status, code, message, details);
}

/** Single-flight refresh: concurrent 401s wait on one refresh call, not N. */
let refreshInFlight: Promise<TokenPair | null> | null = null;

async function refreshTokens(): Promise<TokenPair | null> {
  const refreshToken = bridge.getRefreshToken();
  if (!refreshToken) return null;

  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) return null;
      const tokens = (await response.json()) as TokenPair;
      bridge.onRefreshed(tokens);
      return tokens;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

async function send(
  path: string,
  options: RequestOptions,
  accessToken: string | null,
) {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  try {
    return await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch {
    // fetch only rejects when the request never completed: DNS failure, the
    // host being down, or CORS refusing it outright.
    throw new NetworkError();
  }
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const authenticated = options.auth ?? true;
  let response = await send(
    path,
    options,
    authenticated ? bridge.getAccessToken() : null,
  );

  if (response.status === 401 && authenticated) {
    const tokens = await refreshTokens();
    if (tokens) {
      response = await send(path, options, tokens.access_token);
    } else {
      bridge.onSessionLost();
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(
    path: string,
    body?: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(
    path: string,
    options?: Omit<RequestOptions, "method" | "body">,
  ) => request<T>(path, { ...options, method: "DELETE" }),
};
