"""Kubernetes events in an analysis window — live ones and the history.

The API server keeps events for 1 hour (default `--event-ttl`), so an incident
from this morning has none left there. Alloy ships every event to Loki
(`loki.source.kubernetes_events`, deploy/observability/alloy-values.yaml);
this module merges both:

  - the API's events, already in the snapshot (exact, structured);
  - Loki (`job="kubernetes-events"` on lab1, or Alloy's default job name) for the rest.

Duplicates (the same event seen in both) are dropped. When Loki is
unreachable or Alloy isn't shipping events, the run keeps the API's events
and records a warning — older history is then simply unknown, not "no events".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.integrations.loki import client as loki

# Alloy's default job name, and the one lab1 uses (`job_name = "kubernetes-events"`).
LOKI_JOBS = ("kubernetes-events", "loki.source.kubernetes_events")
MAX_LOKI_LINES = 2000
# logfmt pair: key=value or key="quoted value with \"escapes\"".
_LOGFMT = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')


@dataclass(frozen=True)
class KEvent:
    at: datetime
    type: str  # Normal | Warning
    reason: str
    kind: str  # involved object kind: Pod, Deployment, Node…
    name: str
    namespace: str | None
    message: str
    count: int = 1
    source: str = "events"  # "events" (API) or "loki"
    # First occurrence. The API folds repeats into one event (count=9551,
    # firstTimestamp…lastTimestamp); `at` is the LAST one, this the first.
    first: datetime | None = None

    @property
    def since(self) -> datetime:
        return self.first or self.at


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def from_api(obj: dict[str, Any]) -> KEvent | None:
    involved = obj.get("involvedObject") or {}
    at = (
        _parse_time(obj.get("lastTimestamp"))
        or _parse_time(obj.get("eventTime"))
        or _parse_time(obj.get("firstTimestamp"))
        or _parse_time((obj.get("metadata") or {}).get("creationTimestamp"))
    )
    if at is None:
        return None
    return KEvent(
        at=at,
        type=str(obj.get("type") or "Normal"),
        reason=str(obj.get("reason") or ""),
        kind=str(involved.get("kind") or ""),
        name=str(involved.get("name") or ""),
        namespace=involved.get("namespace") or (obj.get("metadata") or {}).get("namespace"),
        message=str(obj.get("message") or obj.get("note") or "").strip(),
        count=int(obj.get("count") or 1),
        first=_parse_time(obj.get("firstTimestamp")) or _parse_time(obj.get("eventTime")),
    )


def from_loki(line: loki.LogLine) -> KEvent | None:
    """One Alloy event line. Field names differ between Alloy versions and
    formats (json/logfmt), so several spellings are accepted."""
    fields: dict[str, Any] = {}
    try:
        fields = json.loads(line.line)
    except ValueError:
        for key, value in _LOGFMT.findall(line.line):
            if value.startswith('"'):
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            fields[key] = value
    if not isinstance(fields, dict):
        return None

    def pick(*keys: str) -> str:
        for k in keys:
            if fields.get(k) not in (None, ""):
                return str(fields[k])
        return ""

    reason = pick("reason", "Reason")
    if not reason:
        return None
    return KEvent(
        at=datetime.fromtimestamp(line.ts_ns / 1e9, tz=UTC),
        type=pick("type", "Type") or "Normal",
        reason=reason,
        kind=pick("kind", "objectKind", "involvedObjectKind"),
        name=pick("name", "objectName", "involvedObjectName"),
        namespace=line.labels.get("namespace"),
        message=pick("msg", "message", "Message"),
        count=int(pick("count") or 1),
        source="loki",
    )


def _relevant(e: KEvent, namespaces: set[str] | None) -> bool:
    # Node events belong to no namespace (the API files them under "default").
    return namespaces is None or e.kind == "Node" or e.namespace in namespaces


async def _loki_has_events(minutes: int, end: datetime) -> bool:
    """Whether Loki holds ANY Kubernetes event in the window, in any namespace:
    "none for these namespaces" is normal, "none at all" means nothing ships them."""
    try:
        sample = await loki.query_range(
            f'{{job=~"{"|".join(LOKI_JOBS)}"}}', minutes=minutes, limit=1, end=end.timestamp()
        )
    except loki.LokiError:
        return False
    return bool(sample)


async def in_window(
    namespaces: list[str] | None,
    start: datetime,
    end: datetime,
    api_events: list[dict[str, Any]],
) -> tuple[list[KEvent], list[str]]:
    """Events of `namespaces` (None = every namespace), plus node events, between start and end."""
    warnings: list[str] = []
    scope = set(namespaces) if namespaces is not None else None
    # Kept when its span [first, last] overlaps the window.
    found = [
        e
        for e in (from_api(o) for o in api_events)
        if e and e.since <= end and e.at >= start and _relevant(e, scope)
    ]

    minutes = max(1, int((end - start).total_seconds() // 60) + 1)
    selector = ".*" if namespaces is None else "|".join([*namespaces, ""])
    query = f'{{job=~"{"|".join(LOKI_JOBS)}", namespace=~"{selector}"}}'
    try:
        lines = await loki.query_range(
            query, minutes=minutes, limit=MAX_LOKI_LINES, end=end.timestamp()
        )
    except loki.LokiError as exc:
        warnings.append(f"Event history from Loki unavailable: {exc}")
        lines = []
    if (
        not lines
        and (end - start).total_seconds() > 3600
        and not await _loki_has_events(minutes, end)
    ):
        warnings.append(
            "No Kubernetes events in Loki for this window: events older than 1 hour are "
            "unknown (is Alloy shipping them? see deploy/observability/alloy-values.yaml)."
        )

    def key(e: KEvent) -> tuple:
        return (e.namespace, e.kind, e.name, e.reason, e.at.replace(second=0, microsecond=0))

    seen = {key(e) for e in found}
    for line in lines:
        ev = from_loki(line)
        if not ev or not (start <= ev.at <= end) or not _relevant(ev, scope):
            continue
        if key(ev) not in seen:
            seen.add(key(ev))
            found.append(ev)
    found.sort(key=lambda e: e.at)
    return found, warnings


__all__ = ["LOKI_JOBS", "KEvent", "from_api", "from_loki", "in_window"]
