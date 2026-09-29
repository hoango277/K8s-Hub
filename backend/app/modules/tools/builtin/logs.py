"""Built-in tool: search cluster logs in Loki, from validated fields.

LogQL is assembled here from discrete inputs — the model never writes it.
The free-text `contains` filter is the only user text that reaches the query,
and it goes in as an escaped string literal, never as an operator.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from langchain_core.tools import tool

from app.core.config import get_settings
from app.integrations.loki import client as loki
from app.modules.tools.guard import ToolInputError, check_namespace, clamp
from app.modules.tools.schema import Category, Danger, ToolSpec

_POD_PREFIX = re.compile(r"^[a-z0-9]([-a-z0-9]{0,62})?$")
_LABEL_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ERROR_PATTERN = "(?i)(error|exception|fatal|panic|traceback|failed)"
MAX_LINE = 400
MAX_TOTAL = 7000


def _literal(text: str) -> str:
    """A LogQL double-quoted string: escape backslash and quote, drop newlines."""
    clean = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{clean}"'


def build_logql(
    *, namespace: str, pod: str | None, app: str | None, contains: str | None, errors_only: bool
) -> str:
    matchers = [f'namespace="{namespace}"']
    if pod:
        if not _POD_PREFIX.match(pod):
            raise ToolInputError(f"Invalid pod name or prefix: {pod!r}.")
        matchers.append(f'pod=~"{pod}.*"')
    if app:
        if not _LABEL_VALUE.match(app):
            raise ToolInputError(f"Invalid app label: {app!r}.")
        matchers.append(f'app="{app}"')
    query = "{" + ", ".join(matchers) + "}"
    if contains:
        if len(contains) > 200:
            raise ToolInputError("The search text is too long (200 characters max).")
        query += f" |= {_literal(contains)}"
    if errors_only:
        query += f" |~ {_literal(ERROR_PATTERN)}"
    return query


@tool(parse_docstring=True)
async def search_logs(
    namespace: str,
    pod: str | None = None,
    app: str | None = None,
    contains: str | None = None,
    errors_only: bool = False,
    since_minutes: int = 60,
    limit: int = 50,
) -> str:
    """Search container logs of the cluster (from Loki), newest first.

    Use to find error messages around an incident, across all pods of a
    workload and including pods that no longer exist (unlike get_pod_logs).

    Args:
        namespace: Kubernetes namespace.
        pod: pod name or prefix, e.g. a deployment name.
        app: value of the "app" label.
        contains: only lines containing this text (case-sensitive).
        errors_only: only lines that look like errors or exceptions.
        since_minutes: how far back, 1–1440 (default 60).
        limit: max lines, 1–200 (default 50).
    """
    try:
        check_namespace(namespace)
        query = build_logql(
            namespace=namespace, pod=pod, app=app, contains=contains, errors_only=errors_only
        )
        minutes = clamp(since_minutes, 1, 1440)
        lines = await loki.query_range(query, minutes=minutes, limit=clamp(limit, 1, 200))
    except (ToolInputError, loki.LokiError) as exc:
        return str(exc)
    if not lines:
        return f"No log lines matched {query} in the last {minutes} minutes."

    out = [f"{len(lines)} line(s) matching {query}, last {minutes} min, newest first:"]
    total = 0
    for entry in lines:
        when = datetime.fromtimestamp(entry.ts_ns / 1e9, UTC).strftime("%H:%M:%S")
        line = entry.line.rstrip()
        text = line if len(line) <= MAX_LINE else line[:MAX_LINE] + "…"
        row = f"{when} {entry.labels.get('pod', '?')}: {text}"
        total += len(row)
        if total > MAX_TOTAL:
            out.append("… more lines cut to keep the answer short; narrow the search")
            break
        out.append(row)
    return "\n".join(out)


def _unavailable() -> str | None:
    return None if get_settings().LOKI_URL.strip() else "LOKI_URL is empty in .env."


TOOLS = [ToolSpec(search_logs, "Search logs", Category.LOGS, Danger.READ, unavailable=_unavailable)]
