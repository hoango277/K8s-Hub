/**
 * A question prepared on another page and waiting in the chat composer — e.g.
 * "Investigate in chat" on a diagnosis writes "Use the diagnose-crashloop skill on
 * cause #1…" for the user to read, edit and send. Never sent automatically: a
 * chat turn costs tokens, and the user should see what is asked in their name.
 *
 * sessionStorage, per thread: it only has to survive one navigation. Storage can
 * be blocked (private mode, site settings); a lost draft is an empty composer, so
 * every access is wrapped.
 */

const PREFIX = "k8shub.draft.";

export function saveDraft(threadId: string, text: string): void {
  try {
    sessionStorage.setItem(PREFIX + threadId, text);
  } catch {
    // Storage blocked: the chat opens with an empty composer instead.
  }
}

/** Read without removing — safe in a render (React may run initializers twice). */
export function peekDraft(threadId: string): string | null {
  try {
    return sessionStorage.getItem(PREFIX + threadId);
  } catch {
    return null;
  }
}

export function clearDraft(threadId: string): void {
  try {
    sessionStorage.removeItem(PREFIX + threadId);
  } catch {
    // Nothing stored, or storage blocked.
  }
}
