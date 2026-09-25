/**
 * Stores the access/refresh token pair and refreshes the access token before it
 * expires.
 *
 * WHY LOCALSTORAGE, NOT AN HTTPONLY COOKIE:
 * It is simpler to debug through `/docs` (you can paste a Bearer token by
 * hand). The trade-off is that any script running on the page can read the
 * token — if an XSS hole ever shows up in the chat's Markdown rendering, the
 * token leaks with it. This is a deliberate trade-off, not an oversight.
 *
 * WHY REFRESH PROACTIVELY INSTEAD OF JUST CATCHING 401:
 * Refresh tokens ROTATE on the backend — each use revokes the old token and
 * issues a new one (see app/services/auth_service.py). If two parallel requests
 * both hit 401 and both call refresh, the second one uses a refresh token the
 * first already revoked — which is read as "token was stolen", and the backend
 * then revokes EVERY session. Checking expiry BEFORE sending, plus coalescing
 * simultaneous refresh calls into one, avoids both problems.
 */

const STORAGE_KEY = "k8shub.auth";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

function readRaw(): TokenPair | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw) as Partial<TokenPair>;
    if (typeof d.access_token !== "string" || typeof d.refresh_token !== "string") return null;
    return { access_token: d.access_token, refresh_token: d.refresh_token };
  } catch {
    return null;
  }
}

export function saveTokenPair(pair: TokenPair): void {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(pair));
    } catch {
      // Couldn't persist (storage blocked, quota full) — the session still
      // works in memory until the page reloads; we only lose persistence
      // across visits.
    }
  }
  notifyListeners();
}

export function clearTokens(): void {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }
  notifyListeners();
}

/** Whether a stored session exists — used to decide whether to ask `/auth/me`
 * on page load or go straight to /login. */
export function hasSession(): boolean {
  return readRaw() !== null;
}

/** The raw refresh token, for logging out — we don't care whether the access
 * token is still valid, only need something to tell the backend which session
 * to revoke. */
export function getRawRefreshToken(): string | null {
  return readRaw()?.refresh_token ?? null;
}

// --------------------------------------------------------------------------
// Read expiry from the JWT — READ ONLY, the signature is not verified. Real
// verification is the backend's job; here we only need to know "should we
// proactively ask for a new token yet".
// --------------------------------------------------------------------------

function expiryOf(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof decoded.exp === "number" ? decoded.exp : null;
  } catch {
    return null;
  }
}

/** With less than this many seconds left, treat the token as about to expire
 * and refresh early — rather than waiting until the last second and then
 * sending a request with a token that just expired. */
const REFRESH_THRESHOLD_SECONDS = 20;

function isExpiringSoon(token: string): boolean {
  const exp = expiryOf(token);
  if (exp === null) return true; // unreadable: assume it's expiring, which is safer
  return exp - Date.now() / 1000 < REFRESH_THRESHOLD_SECONDS;
}

// --------------------------------------------------------------------------
// Refresh — coalesce simultaneous calls into ONE refresh request.
// --------------------------------------------------------------------------

let inflightRefresh: Promise<string | null> | null = null;

async function callRefresh(refreshToken: string): Promise<string | null> {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api/backend";
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return null;
    const pair = (await res.json()) as TokenPair;
    saveTokenPair(pair);
    return pair.access_token;
  } catch {
    return null;
  }
}

/**
 * An access token that is usable right now, refreshed first if needed.
 *
 * Returning `null` means there is no salvageable session — the refresh token
 * has also expired or been revoked. Callers must treat this as a logout.
 */
export async function getValidAccessToken(): Promise<string | null> {
  const raw = readRaw();
  if (raw === null) return null;

  if (!isExpiringSoon(raw.access_token)) return raw.access_token;

  // Several requests may notice the access token is about to expire at the
  // same moment (e.g. a few TanStack Query queries firing in parallel on page
  // load) — only the first actually calls refresh, the rest AWAIT that same
  // result.
  inflightRefresh ??= callRefresh(raw.refresh_token).finally(() => {
    inflightRefresh = null;
  });
  return inflightRefresh;
}

// --------------------------------------------------------------------------
// Tell the rest of the app the session just changed (login/logout), so
// AuthProvider can update the UI without polling localStorage itself.
// --------------------------------------------------------------------------

type Listener = () => void;
const listeners = new Set<Listener>();

export function subscribeSession(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notifyListeners(): void {
  for (const listener of listeners) listener();
}
