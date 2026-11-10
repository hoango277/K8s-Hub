/**
 * The sentence to show for a failed assistant turn.
 *
 * Since 10/2026 the backend stores a readable sentence (`_error_message` in
 * backend/app/integrations/llm/streaming.py). Older rows hold the provider's raw
 * exception — "RateLimitError: Error code: 429 - {'error': {'message': …,
 * 'org_…'}}" — which leaks internals and helps nobody. Those are mapped to the
 * same sentences the backend uses now; already-readable text passes through.
 * A stored "try again in 16m" is stale by the time the row is read, so the
 * historic wording has no wait time.
 */
export function friendlyChatError(raw: string): string {
  const looksTechnical =
    /Error code:|Traceback|Exception|\{['"]|Error:/.test(raw) || raw.length > 240;
  if (!looksTechnical) return raw;

  const text = raw.toLowerCase();
  if (text.includes("rate limit") || text.includes("ratelimit") || text.includes("429")) {
    return text.includes("tokens per day") || raw.includes("(TPD)")
      ? "This model's daily token quota was used up. Pick another model or try again later."
      : "Hit the provider's rate limit. Wait and try again.";
  }
  if (text.includes("413") || text.includes("too large")) {
    return "The request was too large for this model. Ask about a narrower scope (one namespace, one app), or pick a model with a larger context.";
  }
  if (text.includes("timeout") || text.includes("timed out")) {
    return "The model took too long to respond. Try again or switch to a faster model.";
  }
  if (text.includes("401") || text.includes("api key") || text.includes("authentication")) {
    return "Invalid API key. Check it in Settings.";
  }
  if (text.includes("recursion")) {
    return "The assistant called tools too many times without reaching an answer. Try a more specific question.";
  }
  return "Something went wrong while answering. Try again; if it keeps happening, check the server log.";
}
