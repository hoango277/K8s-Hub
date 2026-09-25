/**
 * Forwards every /api/backend/* call to the FastAPI backend.
 *
 * WHY NOT `rewrites` IN next.config.ts:
 * A rewrite buffers the whole response and returns it in one go. Fine for
 * regular requests, but it completely breaks SSE streams: measurements showed
 * all 25 events of a chat turn arriving AT THE SAME TIME at 12.7 seconds
 * instead of spread over 4 seconds. The user watches a frozen screen and then
 * the answer appears in one lump — losing the whole point of streaming.
 *
 * A route handler returns `upstream.body` (a ReadableStream) directly, so data
 * comes out as fast as it flows in.
 *
 * Going through here instead of calling the backend directly from the browser
 * means the browser only sees a single origin — no CORS configuration, and API
 * keys never have to be exposed client-side.
 */

import type { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

// Always dynamic: buffering at any layer breaks streaming.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Headers not forwarded to the backend. */
const SKIP_REQUEST_HEADERS = new Set(["host", "connection", "content-length"]);

/**
 * Headers not copied back to the client.
 * fetch has already decompressed the response body; keeping the old
 * content-encoding or content-length would make the browser misread it.
 */
const SKIP_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);

async function forward(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const url = `${BACKEND}/api/v1/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((v, k) => {
    if (!SKIP_REQUEST_HEADERS.has(k.toLowerCase())) headers.set(k, v);
  });

  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      // Read the whole request body before sending. Our requests are all
      // small, and this avoids having to enable fetch's duplex mode.
      body: hasBody ? await req.text() : undefined,
      cache: "no-store",
      // If the user closes the tab, cancel the backend call too.
      signal: req.signal,
    });
  } catch {
    return Response.json(
      { detail: `Can't reach the backend at ${BACKEND}. Is it running?` },
      { status: 502 },
    );
  }

  const resHeaders = new Headers();
  upstream.headers.forEach((v, k) => {
    if (!SKIP_RESPONSE_HEADERS.has(k.toLowerCase())) resHeaders.set(k, v);
  });

  if (resHeaders.get("content-type")?.includes("text/event-stream")) {
    resHeaders.set("Cache-Control", "no-cache, no-transform");
    // Tell nginx/ingress in front not to buffer the data.
    resHeaders.set("X-Accel-Buffering", "no");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;
