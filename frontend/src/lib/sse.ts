/**
 * Reads an SSE stream with `fetch`.
 *
 * Why not the browser's built-in `EventSource`: `EventSource` can only send
 * GET, but the user's question has to go in the request body (POST). It also
 * can't set headers. The price is parsing SSE frames ourselves — that part
 * lives entirely in this file.
 *
 * SSE format: each frame is a set of `field: value` lines ending with a blank
 * line. Lines starting with ':' are comments — the server's keep-alive
 * heartbeat travels this way and must be ignored.
 */

import { getValidAccessToken } from "@/lib/auth-tokens";
import { parseAgentEvent, type AgentEvent } from "@/types/events";

export interface SseOptions {
  signal?: AbortSignal;
  /** Called when the server returns an HTTP error before the stream opens. */
  onHttpError?: (status: number, body: string) => void;
}

/** A parsed SSE frame. */
interface Frame {
  event: string;
  data: string;
  id: string;
}

function parseFrame(block: string): Frame | null {
  const frame: Frame = { event: "message", data: "", id: "" };
  const data: string[] = [];

  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // blank line or comment

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // Strip exactly ONE space after the colon, per the spec.
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") frame.event = value;
    else if (field === "data") data.push(value);
    else if (field === "id") frame.id = value;
  }

  if (data.length === 0) return null;
  frame.data = data.join("\n");
  return frame;
}

/**
 * Send a POST and yield each assistant event in real time.
 *
 * Malformed events are skipped rather than breaking the whole stream — one bad
 * frame isn't worth losing the rest of the answer.
 */
export async function* streamAgentEvents(
  url: string,
  body: unknown,
  options: SseOptions = {},
): AsyncGenerator<AgentEvent> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };

  // Refresh before opening the stream, not after: once SSE is open there is no
  // way to re-attach headers or retry mid-stream — unlike regular requests in
  // lib/api.ts, which still get a chance to catch a 401 and retry.
  const token = await getValidAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    options.onHttpError?.(res.status, text);
    throw new Error(text || `Error ${res.status}`);
  }
  if (!res.body) throw new Error("The server did not return a data stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      // stream: true so multi-byte characters split across chunks are rejoined correctly.
      buffer += decoder.decode(value, { stream: true });

      // A frame ends with a blank line. Accept both \n\n and \r\n\r\n.
      let boundary: number;
      while ((boundary = findFrameBoundary(buffer)) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary).replace(/^(\r?\n){2}/, "");

        const frame = parseFrame(block);
        if (!frame) continue;

        const event = parseAgentEvent(frame.data);
        if (event) yield event;
      }
    }
  } finally {
    // If we stop mid-stream we must close, otherwise the connection hangs.
    reader.cancel().catch(() => undefined);
  }
}

function findFrameBoundary(text: string): number {
  const a = text.indexOf("\n\n");
  const b = text.indexOf("\r\n\r\n");
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}
