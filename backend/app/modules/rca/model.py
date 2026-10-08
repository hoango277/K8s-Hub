"""The vocabulary of the RCA module: entities, events, evidence, causal edges.

Groot (eBay, ASE'21) builds its causality graph out of EVENTS — "latency spike
on checkout", "deployment of service E" — not out of services. Two events are
linked only when a rule says one can cause the other (rules.py). This file is
the shared data model for that graph; nothing here talks to the cluster.

Kept free of raw data on purpose: an Event carries a one-line summary and a
few short Evidence quotes, never a log dump or a metric series. That is what
keeps the LLM step (report.py) within a fixed token budget.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Category = Literal["symptom", "state", "resource", "change", "dependency"]
Severity = Literal["info", "warning", "critical"]

MAX_EVIDENCE_CHARS = 300


@dataclass(frozen=True)
class Entity:
    """A thing on the cluster an event happens to.

    kind: Workload, Pod, Node, Service, Ingress, PVC, ConfigMap, Secret, HPA.
    Workloads keep their real kind (Deployment/StatefulSet/DaemonSet) in `sub`.
    """

    kind: str
    namespace: str | None
    name: str
    # Display only (e.g. "Deployment"): two references to one workload are the
    # same entity whether or not the caller knew its real kind.
    sub: str = field(default="", compare=False)

    @property
    def key(self) -> str:
        ns = self.namespace or "-"
        return f"{self.kind}/{ns}/{self.name}"

    def label(self) -> str:
        shown = self.sub or self.kind
        return f"{shown} {self.namespace + '/' if self.namespace else ''}{self.name}"


@dataclass(frozen=True)
class EventType:
    name: str
    category: Category
    # How likely this KIND of event is to be a root cause, all else equal.
    # Changes and resource limits are usual roots; "pod not ready" almost never is.
    prior: float
    title: str


EVENT_TYPES: dict[str, EventType] = {
    t.name: t
    for t in (
        # --- changes made by someone (Groot's "developer activities") ---
        EventType("Rollout", "change", 1.0, "New rollout"),
        EventType("ConfigChange", "change", 0.95, "ConfigMap/Secret changed"),
        EventType("ScaleChange", "change", 0.9, "Replica count changed"),
        EventType("ApprovalExecuted", "change", 1.0, "Change applied through K8s-Hub"),
        EventType("NodeCordon", "change", 0.8, "Node cordoned"),
        EventType("GitOpsSync", "change", 0.95, "Argo CD synced a new revision"),
        EventType("HelmRelease", "change", 0.95, "Helm release upgraded"),
        EventType("SecretChange", "change", 0.9, "Secret changed"),
        # --- resources and capacity ---
        EventType("MemoryNearLimit", "resource", 0.9, "Memory close to its limit"),
        EventType("MemoryLeak", "resource", 0.85, "Memory growing toward its limit"),
        EventType("CpuThrottling", "resource", 0.7, "CPU throttled"),
        EventType("NodePressure", "resource", 0.9, "Node under pressure"),
        EventType("NodeSaturated", "resource", 0.85, "Node out of allocatable resources"),
        EventType("NodeNotReady", "resource", 0.9, "Node not ready"),
        EventType("PvcPending", "resource", 0.9, "Volume claim pending"),
        EventType("HpaAtMax", "resource", 0.5, "Autoscaler at its maximum"),
        # --- pod / container states ---
        EventType("ImagePullError", "state", 0.8, "Image can't be pulled"),
        EventType("ContainerConfigError", "state", 0.8, "Container config invalid"),
        EventType("OOMKilled", "state", 0.7, "Container OOM-killed"),
        EventType("ProbeFailed", "state", 0.6, "Health probe failing"),
        EventType("VolumeMountFailed", "state", 0.7, "Volume mount failed"),
        EventType("Unschedulable", "state", 0.6, "Pod can't be scheduled"),
        EventType("Evicted", "state", 0.5, "Pod evicted"),
        EventType("LogErrorSpike", "state", 0.5, "Error logs increased"),
        EventType("CrashLoop", "symptom", 0.5, "Container crash-looping"),
        EventType("RestartSpike", "symptom", 0.3, "Container restarted"),
        EventType("PodNotReady", "symptom", 0.3, "Pod not ready"),
        EventType("ReplicasUnavailable", "symptom", 0.2, "Replicas unavailable"),
        EventType("RolloutStuck", "symptom", 0.4, "Rollout stuck"),
        EventType("ServiceNoEndpoints", "symptom", 0.4, "Service has no ready endpoints"),
        # --- request-level symptoms and their propagation ---
        EventType("ErrorRateSpike", "symptom", 0.3, "Request errors increased"),
        EventType("LatencySpike", "symptom", 0.3, "Request latency increased"),
        EventType("DownstreamErrors", "dependency", 0.6, "Errors in a called service"),
    )
}


@dataclass
class Evidence:
    """One short, quotable fact behind an event — what a person can check."""

    id: str
    source: str  # k8s | events | prometheus | loki | tempo | approvals
    text: str
    at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.text) > MAX_EVIDENCE_CHARS:
            self.text = self.text[: MAX_EVIDENCE_CHARS - 1] + "…"


@dataclass
class Event:
    id: str
    type: str
    entity: Entity
    start: datetime
    summary: str
    severity: Severity = "warning"
    end: datetime | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def kind(self) -> EventType:
        return EVENT_TYPES[self.type]

    @property
    def prior(self) -> float:
        """Root-cause likelihood of this event: its type's prior, lowered by the
        detector when the event is weaker than its type (`prior_factor`) — a
        ConfigMap CREATED in the window is a much weaker suspect than one EDITED."""
        return self.kind.prior * float(self.attrs.get("prior_factor", 1.0))

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["entity"] = {**asdict(self.entity), "key": self.entity.key}
        data["category"] = self.kind.category
        data["title"] = self.kind.title
        return _isoformat(data)


@dataclass
class CausalEdge:
    cause: str  # event id
    effect: str  # event id
    rule: str
    weight: float
    why: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Hypothesis:
    rank: int
    event_id: str
    score: float
    # Event ids from this root cause down to a symptom, and the rules between them.
    chain: list[str]
    rules: list[str]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _isoformat(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _isoformat(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_isoformat(v) for v in value]
    return value


__all__ = [
    "EVENT_TYPES",
    "MAX_EVIDENCE_CHARS",
    "CausalEdge",
    "Entity",
    "Event",
    "EventType",
    "Evidence",
    "Hypothesis",
]
