/**
 * Calls to the FastAPI backend.
 *
 * By default requests go through the rewrite in next.config.ts
 * (/api/backend/* -> backend/api/v1/*) to avoid CORS during development.
 */

import { getValidAccessToken, clearTokens } from "@/lib/auth-tokens";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/backend";

/** Endpoints that do NOT need — and should not carry — the current session's
 * access token. `/auth/refresh` stands on its own with a separate refresh token
 * (see sse.ts and auth-tokens.ts); `/auth/login` and `/auth/register`
 * authenticate with what the user just typed, so there is no session to attach
 * yet. */
const NO_TOKEN_PATHS = ["/auth/login", "/auth/register", "/auth/refresh"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Extract an error message from the various body shapes FastAPI returns. */
function extractMessage(body: unknown, fallback: string): string {
  if (typeof body === "string" && body) return body;

  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;

    // FastAPI validation error: [{loc: [...], msg: "..."}]
    if (Array.isArray(detail)) {
      const parts = detail
        .map((d) => {
          if (typeof d === "object" && d !== null && "msg" in d) {
            const loc = "loc" in d && Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
            return loc ? `${loc}: ${String(d.msg)}` : String(d.msg);
          }
          return String(d);
        })
        .filter(Boolean);
      if (parts.length) return parts.join(" · ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };

  if (!NO_TOKEN_PATHS.some((p) => path.startsWith(p))) {
    // Proactively refresh the access token BEFORE sending if it is about to
    // expire — see auth-tokens.ts for why we don't wait for a 401 to refresh.
    const token = await getValidAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the backend running?");
  }

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    // A 401 here means the access token was already refreshed (if it could be)
    // and was still rejected — the account is locked, or the refresh token has
    // expired too. Nothing left to salvage: clear the session so AuthProvider
    // sends the user to /login, instead of leaving them stuck on a screen that
    // keeps showing errors without explaining why.
    if (res.status === 401 && !NO_TOKEN_PATHS.some((p) => path.startsWith(p))) {
      clearTokens();
    }
    throw new ApiError(res.status, extractMessage(body, `Error ${res.status}`), body);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) }),
  patch: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(data) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
