"""Event detectors: turn cluster state and telemetry into Groot-style EVENTS.

Each detector reads the shared snapshot / topology / event history (and at
most a few bounded queries of its own) and reports what it found through
`Found.add`. Nothing raw leaves a detector — only an Event with a one-line
summary and a few ≤300-char evidence quotes (model.py).

Detectors are deterministic and independent: one failing (Prometheus down,
Loki unreachable) adds a warning and the run goes on with the others, because
a partial graph that says what it's missing beats no answer.
"""

from __future__ import annotations

import statistics
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.rca.events_store import KEvent
from app.modules.rca.model import EVENT_TYPES, Entity, Event, Evidence, Severity
from app.modules.rca.snapshot import Snapshot, namespace_of
from app.modules.rca.topology import Topology

MAX_EVIDENCE_PER_EVENT = 5


@dataclass
class Context:
    snap: Snapshot
    topo: Topology
    kevents: list[KEvent]
    # The analysis window. Causes are looked for in all of it; it starts well
    # before the symptom (RCA_LOOKBACK_MINUTES) because rollouts precede crashes.
    start: datetime
    end: datetime
    # Executed approvals of the scope in the window, loaded by the pipeline
    # (dicts: id, kind, title, namespace, target, status, executed_at,
    # requested_by_email, decided_by_email) so detectors never touch the database.
    approvals: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Namespaces to analyse; None = the whole cluster. The snapshot and the
    # topology always cover everything, so dependencies outside stay visible.
    namespaces: set[str] | None = None

    def in_scope(self, namespace: str | None) -> bool:
        return self.namespaces is None or namespace in self.namespaces

    def objects(self, attr: str) -> list[dict[str, Any]]:
        """Snapshot objects of one kind (`pods`, `deployments`…) inside the scope."""
        return [o for o in getattr(self.snap, attr) if self.in_scope(namespace_of(o))]

    @property
    def scope(self) -> list[str]:
        return sorted(self.namespaces) if self.namespaces is not None else self.snap.namespaces

    def namespace_regex(self) -> str:
        """For `namespace=~"…"` in PromQL/LogQL. Names are DNS labels: no escaping needed."""
        return "|".join(self.scope) if self.namespaces is not None else ".+"

    @property
    def minutes(self) -> int:
        return max(1, int((self.end - self.start).total_seconds() // 60) + 1)

    def in_window(self, at: datetime | None) -> bool:
        return at is not None and self.start <= at <= self.end

    def since(self, events: Sequence[KEvent]) -> datetime:
        """When these events started, but not before the window."""
        return max(min(e.since for e in events), self.start)

    def kevents_for(
        self,
        kind: str,
        name: str,
        reasons: Sequence[str] | None = None,
        namespace: str | None = None,
    ) -> list[KEvent]:
        return [
            e
            for e in self.kevents
            if e.kind == kind
            and e.name == name
            and (namespace is None or e.namespace in (namespace, None))
            and (reasons is None or e.reason in reasons)
        ]


class Found:
    """The events found so far, one per (type, entity).

    The same fact often shows up twice — a pod's status AND its event history
    both say CrashLoopBackOff. They merge into one event: earliest start,
    evidence from both.
    """

    def __init__(self) -> None:
        self.events: dict[str, Event] = {}

    def add(
        self,
        type_: str,
        entity: Entity,
        at: datetime,
        summary: str,
        *,
        severity: Severity = "warning",
        evidence: Sequence[tuple[str, str, datetime | None]] = (),
        **attrs: Any,
    ) -> Event:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"Unknown event type {type_!r}")
        event_id = f"{type_}:{entity.key}"
        ev = self.events.get(event_id)
        if ev is None:
            ev = Event(event_id, type_, entity, at, summary, severity, attrs=dict(attrs))
            self.events[event_id] = ev
        else:
            if at < ev.start:
                ev.start = at
            ev.attrs.update({k: v for k, v in attrs.items() if v is not None})
        seen = {e.text for e in ev.evidence}
        for source, text, when in evidence:
            if text and text not in seen and len(ev.evidence) < MAX_EVIDENCE_PER_EVENT:
                seen.add(text)
                ev.evidence.append(
                    Evidence(f"{event_id}#{len(ev.evidence) + 1}", source, text, when)
                )
        return ev

    def all(self) -> list[Event]:
        return sorted(self.events.values(), key=lambda e: e.start)


Detector = Callable[[Context, Found], Awaitable[None]]


# --- small shared helpers -------------------------------------------------------


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def from_unix(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=UTC)


def meta(obj: dict[str, Any]) -> dict[str, Any]:
    return obj.get("metadata") or {}


def hhmm(at: datetime | None) -> str:
    return at.strftime("%H:%M:%S") if at else "?"


def kevent_evidence(events: Sequence[KEvent], limit: int = 2) -> list[tuple[str, str, datetime]]:
    """The most recent few events as quotes: 'BackOff ×12: Back-off restarting…'."""
    out = []
    for e in sorted(events, key=lambda e: e.at, reverse=True)[:limit]:
        count = f" ×{e.count}" if e.count > 1 else ""
        out.append((e.source, f"{e.reason}{count}: {e.message}", e.at))
    return out


def series_values(series: dict[str, Any]) -> list[tuple[float, float]]:
    """[(unix_ts, value)] of one Prometheus/Loki matrix series, NaN/Inf dropped."""
    out = []
    for ts, raw in series.get("values") or []:
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v == v and v not in (float("inf"), float("-inf")):
            out.append((float(ts), v))
    return out


def first_at_or_above(points: Sequence[tuple[float, float]], threshold: float) -> int | None:
    return next((i for i, (_, v) in enumerate(points) if v >= threshold), None)


def spike(
    points: Sequence[tuple[float, float]],
    *,
    baseline_share: float = 0.3,
    min_ratio: float = 3.0,
    min_absolute: float = 0.0,
) -> tuple[int, float, float] | None:
    """First point after the baseline that is clearly above it.

    Baseline = the first `baseline_share` of the window; "clearly above" =
    above median + 4·MAD (robust to a noisy baseline), at least `min_ratio`
    times the median and at least `min_absolute`. Plain statistics on
    purpose: Groot's lesson is that rules matter more than clever detectors.
    Returns (index, baseline median, value) or None.
    """
    if len(points) < 6:
        return None
    cut = max(3, int(len(points) * baseline_share))
    base = [v for _, v in points[:cut]]
    med = statistics.median(base)
    mad = statistics.median(abs(v - med) for v in base)
    threshold = max(med + 4 * mad, med * min_ratio, min_absolute)
    for i in range(cut, len(points)):
        if points[i][1] > threshold:
            return i, med, points[i][1]
    return None


def change_point(
    points: Sequence[tuple[float, float]],
    *,
    min_ratio: float = 3.0,
    min_absolute: float = 0.0,
    min_segment: int = 3,
    min_score: float = 4.0,
) -> tuple[int, float, float] | None:
    """Where the series steps UP, wherever that is in the window.

    Tries every split into before/after and keeps the one where the after
    level stands out most from the before level (difference of medians in
    units of the before segment's MAD) — a robust single change-point test.
    Unlike `spike`, the baseline isn't a fixed first 30% of the window: a
    change early in the window is found too, and the reported time is when
    the level actually changed. Returns (first "after" index, median before,
    median after) or None when no split is clearly higher.
    """
    values = [v for _, v in points]
    n = len(values)
    if n < 2 * min_segment:
        return None
    best: tuple[float, int, float, float] | None = None
    for k in range(min_segment, n - min_segment + 1):
        before, after = values[:k], values[k:]
        mb, ma = statistics.median(before), statistics.median(after)
        mad = statistics.median(abs(v - mb) for v in before)
        # A flat baseline has MAD 0: use a small fraction of its level instead.
        scale = 1.4826 * mad or max(abs(mb) * 0.05, 1e-9)
        score = (ma - mb) / scale
        if best is None or score > best[0]:
            best = (score, k, mb, ma)
    if best is None:
        return None
    score, k, mb, ma = best
    if score < min_score or ma < max(min_absolute, mb * min_ratio):
        return None
    return k, mb, ma


def linear_trend(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares (slope per second, r²) of the series."""
    n = len(points)
    if n < 3:
        return 0.0, 0.0
    xs = [t for t, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys, strict=True))
    return slope, (1 - ss_res / ss_tot) if ss_tot else 0.0


__all__ = [
    "change_point",
    "linear_trend",
    "Context",
    "Detector",
    "Found",
    "first_at_or_above",
    "from_unix",
    "hhmm",
    "kevent_evidence",
    "meta",
    "parse_time",
    "series_values",
    "spike",
]
