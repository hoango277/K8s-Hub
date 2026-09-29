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

/** Parse a response body: JSON when it is JSON, the raw text otherwise, null when empty (204). */
async function readBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Send a request with the session token attached; throws ApiError on any non-2xx. */
async function send(path: string, init?: RequestInit): Promise<Response> {
  // FormData must NOT get a JSON content type: the browser has to write its
  // own `multipart/form-data; boundary=…` header, or the server can't split
  // the parts apart.
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isForm ? {} : { "Content-Type": "application/json" }),
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

  if (!res.ok) {
    const body = await readBody(res);
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
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  return (await readBody(res)) as T;
}

/** File name from `Content-Disposition: attachment; filename="x.zip"`, if any. */
function filenameFrom(res: Response): string | null {
  const header = res.headers.get("content-disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Download a file from an authenticated endpoint.
 *
 * A plain `<a href>` can't carry the Bearer token, so fetch it as a blob and
 * hand the browser a temporary object URL to save instead.
 */
async function download(path: string, fallbackName: string): Promise<void> {
  const res = await send(path);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filenameFrom(res) ?? fallbackName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Revoke on the next tick: some browsers start the download
    // asynchronously and would find the URL already gone.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) }),
  put: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(data) }),
  patch: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(data) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** POST a multipart form (file uploads). */
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
  download,
};
