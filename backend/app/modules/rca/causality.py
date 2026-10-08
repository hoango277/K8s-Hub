"""Build the Event Causality Graph (Groot's ECG) from detected events.

Starting from the SYMPTOMS, walk backwards: for each event, every rule whose
effect is that event's type names one relation to follow and one cause type to
look for. A cause found there, in the right time order, becomes an edge — and
is itself expanded the same way. Bounded: MAX_DEPTH hops, MAX_NODES events.

Time order. A cause must start before its effect (within the rule's lag, plus
SLACK for detection granularity). An effect that started BEFORE the analysis
window — a crash loop going on for days — has a clamped start time, so its
real order is unknown: the edge is still allowed but weighted down
(ONGOING_FACTOR), because "both are happening" is weaker evidence than
"one happened, then the other".
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.rca.learning import NEUTRAL, Weights
from app.modules.rca.model import CausalEdge, Entity, Event
from app.modules.rca.rules import SLACK, Rule, rules_for
from app.modules.rca.topology import Topology

MAX_DEPTH = 5
MAX_NODES = 200
ONGOING_FACTOR = 0.6
MIN_PROXIMITY = 0.3


@dataclass
class CausalGraph:
    events: dict[str, Event]  # every event reached (seeds included)
    edges: list[CausalEdge] = field(default_factory=list)
    seeds: list[str] = field(default_factory=list)
    truncated: bool = False

    def causes_of(self, event_id: str) -> list[CausalEdge]:
        return [e for e in self.edges if e.effect == event_id]

    def effects_of(self, event_id: str) -> list[CausalEdge]:
        return [e for e in self.edges if e.cause == event_id]


def is_symptom(event: Event) -> bool:
    """Something visibly failing, where the backward walk starts.

    Critical pod states count too: during a rolling update the old pod keeps
    serving, so a bad image shows up ONLY as ImagePullError on the new pod —
    no crash, no missing replica. Treating that as "no symptom" would hide it.
    """
    category = event.kind.category
    return category in ("symptom", "dependency") or (
        category == "state" and event.severity == "critical"
    )


def _proximity(lag_seconds: float, max_lag_seconds: float) -> float:
    """1.0 for simultaneous, decaying with the lag; never below MIN_PROXIMITY."""
    if lag_seconds <= 0:
        return 1.0
    return max(MIN_PROXIMITY, math.exp(-lag_seconds / max_lag_seconds))


def edge_weight(
    rule: Rule,
    cause: Event,
    effect: Event,
    window_start: datetime,
    weights: Weights = NEUTRAL,
) -> float | None:
    """The edge's weight, or None when the time order rules it out."""
    lag = (effect.start - cause.start).total_seconds()
    ongoing = effect.start <= window_start
    if not ongoing:
        if lag < -SLACK.total_seconds():
            return None  # the "cause" came after the effect
        if lag > rule.max_lag.total_seconds():
            return None  # too long ago to be related
    if rule.when is not None and not rule.when(cause, effect):
        return None
    # × what feedback taught about this rule (learning.py; 1.0 without feedback).
    weight = (
        rule.weight * weights.rule(rule.id) * _proximity(max(lag, 0), rule.max_lag.total_seconds())
    )
    return weight * ONGOING_FACTOR if ongoing else weight


def related_to_target(topo: Topology, target: Entity) -> set[str]:
    """Entity keys that count as "the target": itself, its pods, its services, its owner."""
    keys = {target.key}
    for relation in ("pods", "backed_by", "owner", "backend_workloads", "backends"):
        keys |= {e.key for e in topo.related(target, relation)}
    return keys


def build(
    events: list[Event],
    topo: Topology,
    window_start: datetime,
    *,
    target: Entity | None = None,
    focus: set[str] | None = None,
    weights: Weights = NEUTRAL,
) -> tuple[CausalGraph, list[str]]:
    """The causal graph, plus warnings for the report.

    `focus`: the namespaces being diagnosed. Events of their dependencies
    (another namespace pulled in because it's called) are candidate CAUSES,
    not starting points: a database that is slow for its own reasons only
    matters here if it explains a symptom of the focus.
    """
    warnings: list[str] = []
    by_entity: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for ev in events:
        by_entity[(ev.type, ev.entity.key)].append(ev)

    symptoms = [e for e in events if is_symptom(e)]
    if focus is not None and target is None:
        in_focus = [e for e in symptoms if e.entity.namespace in focus]
        if in_focus or not symptoms:
            symptoms = in_focus
        else:
            warnings.append(
                f"No symptom found in {', '.join(sorted(focus))}; "
                "analysing the symptoms of its dependencies instead."
            )
    if target is not None:
        scope = related_to_target(topo, target)
        on_target = [e for e in symptoms if e.entity.key in scope]
        if on_target:
            symptoms = on_target
        else:
            warnings.append(
                f"No symptom found on {target.label()} in the window; "
                "analysing every symptom in the namespace instead."
            )
    if not symptoms:
        # Nothing user-visible is wrong, but something may still be (an OOM
        # that recovered, a change). Rank everything, as Groot does when the
        # alerted service shows no anomaly of its own — and say so plainly, or
        # the report will explain a failure that isn't happening.
        symptoms = list(events)
        if events:
            warnings.append(
                "No symptom (crash, unavailable replicas, errors…) was detected in the window. "
                "The candidates are recent changes and resource states, not explanations of a "
                "failure."
            )

    graph = CausalGraph(events={}, seeds=[e.id for e in symptoms])
    seen_edges: set[tuple[str, str]] = set()
    queue: deque[tuple[Event, int]] = deque((e, 0) for e in symptoms)
    for e in symptoms:
        graph.events[e.id] = e

    while queue:
        effect, depth = queue.popleft()
        if depth >= MAX_DEPTH:
            continue
        for rule in rules_for(effect.type):
            for place in topo.related(effect.entity, rule.relation):
                for cause in by_entity.get((rule.cause, place.key), ()):
                    if cause.id == effect.id or (cause.id, effect.id) in seen_edges:
                        continue
                    weight = edge_weight(rule, cause, effect, window_start, weights)
                    if weight is None:
                        continue
                    if cause.id not in graph.events:
                        if len(graph.events) >= MAX_NODES:
                            graph.truncated = True
                            continue
                        graph.events[cause.id] = cause
                        queue.append((cause, depth + 1))
                    seen_edges.add((cause.id, effect.id))
                    graph.edges.append(
                        CausalEdge(cause.id, effect.id, rule.id, round(weight, 4), rule.why)
                    )
    if graph.truncated:
        warnings.append(f"The causal graph was cut at {MAX_NODES} events.")
    return graph, warnings


__all__ = ["MAX_DEPTH", "MAX_NODES", "CausalGraph", "build", "edge_weight", "is_symptom"]
