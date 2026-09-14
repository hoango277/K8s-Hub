/**
 * Gọi backend FastAPI.
 *
 * Mặc định đi qua rewrite trong next.config.ts (/api/backend/* -> backend/api/v1/*)
 * để tránh CORS lúc phát triển.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/backend";

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

/** Bóc thông báo lỗi từ nhiều dạng body khác nhau của FastAPI. */
function extractMessage(body: unknown, fallback: string): string {
  if (typeof body === "string" && body) return body;

  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;

    // Lỗi validate của FastAPI: [{loc: [...], msg: "..."}]
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
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "Không kết nối được tới máy chủ. Backend đã chạy chưa?");
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
    throw new ApiError(res.status, extractMessage(body, `Lỗi ${res.status}`), body);
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
