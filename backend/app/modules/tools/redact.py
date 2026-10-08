"""Hide credentials in cluster data before it reaches the model (OWASP LLM02:2025).

Refusing to read Secret objects is not enough. Passwords sit in plain sight
elsewhere: a Deployment's `env[].value` ("DB_PASSWORD: SuperSecret123" — far
more common than it should be), a ConfigMap key, a connection string, a token
an app prints to its log. Whatever a tool returns goes to the LLM provider (an
outside company), into Langfuse (which stores every prompt) and into the
`tool_calls` table — so it is redacted at the source, in the tools that read
specs and logs, before any of those see it.

Two ways, because neither alone works:
  - by STRUCTURE (`redact_object`): a name/value pair or a ConfigMap key whose
    NAME says it is a secret. Needed for YAML, where the name and the value are
    on different lines and no text pattern can join them.
  - by PATTERN (`redact_text`): shapes that are secrets whatever they are
    called — the password in `scheme://user:pass@host`, `Bearer …`, JWTs,
    private keys, well-known API key formats, `password=…` in a log line.

Only the secret part goes: the host of a connection string, the variable's
name, the rest of the log line stay, because they are what a diagnosis needs
("wrong DB host" must still be visible). The placeholder says something was
hidden, so the model reports it instead of guessing.

A heuristic: a secret in a variable with an unremarkable name (`XYZ=abc123`)
is not caught. It lowers the risk; it does not remove it.
"""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER = "[REDACTED]"

# A name that says "secret". `…KEY` only at the end, so CACHE_KEY_PREFIX stays
# visible while API_KEY, SSH_KEY and ENCRYPTION_KEY do not.
_SENSITIVE_NAME = re.compile(
    r"pass(?:word|wd|phrase)?|pwd|secret|token|credential|private[_.-]?key"
    r"|api[_.-]?key|access[_.-]?key|(?:^|[_.-])key$",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private keys, whole block.
    (
        re.compile(
            r"-----BEGIN ([A-Z ]*)PRIVATE KEY-----[\s\S]*?-----END \1PRIVATE KEY-----"
        ),
        f"-----BEGIN PRIVATE KEY----- {PLACEHOLDER} -----END PRIVATE KEY-----",
    ),
    # Password inside a URL; the scheme, user and host stay.
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(@)", re.IGNORECASE),
     rf"\1{PLACEHOLDER}\2"),
    (re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}"), rf"\1{PLACEHOLDER}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), PLACEHOLDER),
    # Well-known key formats: AWS access key id, GitHub, Groq, OpenAI-style,
    # Google API key, Slack.
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), PLACEHOLDER),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), PLACEHOLDER),
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"), PLACEHOLDER),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), PLACEHOLDER),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), PLACEHOLDER),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), PLACEHOLDER),
    # `password=…`, `api_key: …`, `"token":"…"` in log lines and flat config.
    # Spaces and tabs only, never a newline: on YAML, `secretKeyRef:` followed
    # by a line break would otherwise swallow the next line's `key:` as its value.
    # A value already redacted is left as it is.
    (
        re.compile(
            r"""(\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"""
            r"""\w*["']?[ \t]*[=:][ \t]*["']?)(?!\[REDACTED\])[^\s"',;&]{3,}""",
            re.IGNORECASE,
        ),
        rf"\1{PLACEHOLDER}",
    ),
]


def is_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME.search(name or ""))


def redact_text(text: str) -> str:
    """Replace secret-shaped substrings; everything else is kept as it was."""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_object(obj: Any) -> Any:
    """A copy of a Kubernetes object (or any JSON-like value) with secrets hidden.

    Anywhere in the tree: a `{"name": X, "value": V}` pair — env entries in
    every container of every pod template, CronJob job templates included —
    with a sensitive X loses V; a ConfigMap's `data`/`binaryData` key with a
    sensitive name loses its value; every other string goes through
    `redact_text`. `valueFrom` references (secretKeyRef…) carry no secret and
    stay, so the model can still say where a value comes from.
    """
    if isinstance(obj, dict):
        name = obj.get("name")
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "value" and isinstance(name, str) and is_sensitive_name(name):
                out[key] = PLACEHOLDER
            elif key in ("data", "binaryData", "stringData") and isinstance(value, dict):
                out[key] = {
                    k: PLACEHOLDER if is_sensitive_name(k) else redact_object(v)
                    for k, v in value.items()
                }
            else:
                out[key] = redact_object(value)
        return out
    if isinstance(obj, list):
        return [redact_object(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


__all__ = ["PLACEHOLDER", "is_sensitive_name", "redact_object", "redact_text"]
