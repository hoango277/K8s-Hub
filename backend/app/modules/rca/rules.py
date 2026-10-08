"""Causal rules: which event can cause which, and where to look for it.

Groot's central idea: two events are linked ONLY when a rule says one can
cause the other. Being on related objects is not enough — a rollout of `api`
does not explain every symptom of every pod on the same node. No rule, no edge.

Each rule is read from the EFFECT's side:

    effect "CrashLoop on Pod p"  —relation "owner"→  Workload w
    look there for a cause of type "Rollout", started before the effect
    (within `max_lag`), optionally only when `when(cause, effect)` holds.

`relation` is one of topology.RELATIONS, or a chain of them
(`owner+callee+pods`). Weights are this project's own knowledge engineering
(the Groot paper doesn't publish eBay's): 0.9 = "almost always the reason
when both are present", 0.5 = "a plausible contributor".

Rules are plain data on purpose: the next step (planned) is letting engineers
add rules on the web, as Groot lets its SREs extend the rule grammar.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from app.modules.rca.model import EVENT_TYPES, Event
from app.modules.rca.topology import relation_known

# How long after a cause its effect may still appear.
FAST = timedelta(minutes=30)
SLOW = timedelta(hours=6)  # config edits bite when pods next restart
# A cause may be stamped slightly AFTER its effect: metric samples are taken
# every step, events are aggregated, and detectors time different things.
SLACK = timedelta(minutes=3)

Condition = Callable[[Event, Event], bool]


@dataclass(frozen=True)
class Rule:
    id: str
    cause: str
    effect: str
    relation: str
    weight: float
    why: str
    max_lag: timedelta = FAST
    when: Condition | None = None


# --- conditions -------------------------------------------------------------------


def _image_changed(cause: Event, _effect: Event) -> bool:
    return bool(cause.attrs.get("image_changed"))


def _config_or_env_changed(cause: Event, _effect: Event) -> bool:
    return bool(
        cause.attrs.get("env_changed")
        or cause.attrs.get("volumes_changed")
        or cause.attrs.get("command_changed")
    )


def _resources_changed(cause: Event, _effect: Event) -> bool:
    return bool(cause.attrs.get("resources_changed"))


def _killed(_cause: Event, effect: Event) -> bool:
    # 137 = SIGKILL: what the kernel OOM killer sends. The container status
    # often says "Error" instead of "OOMKilled" when a sidecar or the runtime
    # reports first.
    return effect.attrs.get("exit_code") == 137 or effect.attrs.get("exit_reason") == "OOMKilled"


def _not_enough_resources(_cause: Event, effect: Event) -> bool:
    msg = str(effect.attrs.get("message", ""))
    return "Insufficient" in msg or "Too many pods" in msg


def _unbound_claim(_cause: Event, effect: Event) -> bool:
    msg = str(effect.attrs.get("message", ""))
    return not msg or "PersistentVolumeClaim" in msg or "unbound" in msg


def _scaled_to_zero(cause: Event, _effect: Event) -> bool:
    return cause.attrs.get("replicas") == 0


def _scaled_up(cause: Event, _effect: Event) -> bool:
    return (cause.attrs.get("replicas") or 0) > (cause.attrs.get("previous") or 0)


def _readiness(cause: Event, _effect: Event) -> bool:
    return cause.attrs.get("probe") in (None, "readiness")


def _scale_action(cause: Event, _effect: Event) -> bool:
    return cause.attrs.get("action") == "scale"


def _image_action(cause: Event, _effect: Event) -> bool:
    return cause.attrs.get("action") in ("set_image", "apply")


# --- the rules ----------------------------------------------------------------------

_POD_FAILURES = ("CrashLoop", "ImagePullError", "ContainerConfigError", "Unschedulable",
                 "PodNotReady", "Evicted", "OOMKilled", "VolumeMountFailed")  # fmt: skip

RULES: list[Rule] = [
    # --- changes made by someone → what they break -----------------------------
    Rule("rollout-image-pull", "Rollout", "ImagePullError", "owner", 0.95,
         "The rollout changed the image, and the new image can't be pulled", when=_image_changed),
    Rule("rollout-crash", "Rollout", "CrashLoop", "owner", 0.85,
         "Pods of the new rollout crash on start"),
    Rule("rollout-config-error", "Rollout", "ContainerConfigError", "owner", 0.9,
         "The rollout changed env/volumes the container can't resolve",
         when=_config_or_env_changed),
    Rule("rollout-probe", "Rollout", "ProbeFailed", "owner", 0.7,
         "Pods of the new rollout fail their health probe"),
    Rule("rollout-oom", "Rollout", "OOMKilled", "owner", 0.75,
         "The rollout changed resource limits", when=_resources_changed),
    Rule("rollout-unschedulable", "Rollout", "Unschedulable", "owner", 0.85,
         "The rollout raised resource requests beyond what the nodes can fit",
         when=_resources_changed),
    Rule("rollout-memory", "Rollout", "MemoryNearLimit", "owner", 0.6,
         "Memory use rose after the rollout"),
    Rule("rollout-logs", "Rollout", "LogErrorSpike", "owner", 0.6,
         "New errors in the logs right after the rollout"),
    Rule("rollout-errors", "Rollout", "ErrorRateSpike", "same", 0.75,
         "Request errors rose right after the rollout"),
    Rule("rollout-latency", "Rollout", "LatencySpike", "same", 0.6,
         "Latency rose right after the rollout"),
    Rule("rollout-stuck", "Rollout", "RolloutStuck", "same", 0.8,
         "This rollout is the one that can't finish"),
    Rule("config-crash", "ConfigChange", "CrashLoop", "config", 0.8,
         "The pod reads a ConfigMap that was just edited", max_lag=SLOW),
    Rule("config-config-error", "ConfigChange", "ContainerConfigError", "config", 0.9,
         "The pod references a key/ConfigMap that was just changed", max_lag=SLOW),
    Rule("config-probe", "ConfigChange", "ProbeFailed", "config", 0.6,
         "The pod reads a ConfigMap that was just edited", max_lag=SLOW),
    Rule("config-logs", "ConfigChange", "LogErrorSpike", "config", 0.6,
         "Errors began after a ConfigMap the pod reads was edited", max_lag=SLOW),
    Rule("config-mount", "ConfigChange", "VolumeMountFailed", "config", 0.7,
         "A ConfigMap the pod mounts was changed", max_lag=SLOW),
    Rule("scale-zero-endpoints", "ScaleChange", "ServiceNoEndpoints", "backend_workloads", 0.95,
         "The workload behind this Service was scaled to 0", when=_scaled_to_zero),
    Rule("scale-up-unschedulable", "ScaleChange", "Unschedulable", "owner", 0.6,
         "Scaling up added pods the cluster has no room for", when=_scaled_up),
    Rule("approval-scale", "ApprovalExecuted", "ScaleChange", "same", 0.95,
         "This scale was applied through K8s-Hub", when=_scale_action),
    Rule("approval-rollout", "ApprovalExecuted", "Rollout", "same", 0.95,
         "This rollout was applied through K8s-Hub", when=_image_action),
    Rule("approval-endpoints", "ApprovalExecuted", "ServiceNoEndpoints", "backend_workloads", 0.8,
         "A change applied through K8s-Hub to the workload behind this Service"),
    Rule("cordon-unschedulable", "NodeCordon", "Unschedulable", "any_node", 0.5,
         "A node was cordoned, leaving less room to schedule", when=_not_enough_resources),
    # --- resources → pod states ---------------------------------------------------
    Rule("memory-oom", "MemoryNearLimit", "OOMKilled", "same", 0.95,
         "Memory reached the limit, then the container was killed"),
    Rule("memory-crash", "MemoryNearLimit", "CrashLoop", "same", 0.85,
         "Memory reaches the limit and the container is killed (exit 137)", when=_killed),
    Rule("memory-restart", "MemoryNearLimit", "RestartSpike", "same", 0.85,
         "Memory reached the limit and the container was killed (exit 137)", when=_killed),
    Rule("throttle-latency", "CpuThrottling", "LatencySpike", "pods", 0.6,
         "Pods of this workload are CPU-throttled"),
    Rule("throttle-probe", "CpuThrottling", "ProbeFailed", "same", 0.5,
         "A throttled container answers its probe too slowly"),
    Rule("node-pressure-evicted", "NodePressure", "Evicted", "node", 0.9,
         "The node was under pressure and evicted the pod"),
    Rule("node-notready-pod", "NodeNotReady", "PodNotReady", "node", 0.9,
         "The pod's node is not ready"),
    Rule("node-notready-crash", "NodeNotReady", "RestartSpike", "node", 0.6,
         "Containers restarted when their node went down"),
    Rule("node-full-unschedulable", "NodeSaturated", "Unschedulable", "any_node", 0.85,
         "Nodes have no allocatable room left for the pod's requests",
         max_lag=SLOW, when=_not_enough_resources),
    Rule("pvc-unschedulable", "PvcPending", "Unschedulable", "volume", 0.9,
         "The pod waits for a volume claim that isn't bound", max_lag=SLOW, when=_unbound_claim),
    Rule("pvc-mount", "PvcPending", "VolumeMountFailed", "volume", 0.85,
         "The volume claim the pod mounts isn't bound", max_lag=SLOW),
    Rule("hpa-latency", "HpaAtMax", "LatencySpike", "hpa", 0.5,
         "The autoscaler can't add more replicas"),
    # --- within a pod -------------------------------------------------------------
    Rule("oom-crash", "OOMKilled", "CrashLoop", "same", 0.9,
         "The container keeps being OOM-killed"),
    Rule("logs-crash", "LogErrorSpike", "CrashLoop", "same", 0.5,
         "The container logs errors before crashing"),
    Rule("logs-restart", "LogErrorSpike", "RestartSpike", "same", 0.5,
         "The container logged errors before restarting"),
    Rule("probe-notready", "ProbeFailed", "PodNotReady", "same", 0.85,
         "The readiness probe fails, so the pod isn't ready", when=_readiness),
    Rule("probe-restart", "ProbeFailed", "RestartSpike", "same", 0.6,
         "A failing liveness probe restarts the container"),
    Rule("crash-notready", "CrashLoop", "PodNotReady", "same", 0.6,
         "A crash-looping container is never ready"),
    # --- pods → their workload / service ------------------------------------------
    *[
        Rule(f"{failure.lower()}-replicas", failure, "ReplicasUnavailable", "pods", 0.8,
             "Pods of this workload are failing, so replicas are missing")
        for failure in _POD_FAILURES
    ],
    *[
        Rule(f"{failure.lower()}-rollout-stuck", failure, "RolloutStuck", "pods", 0.75,
             "New pods of the rollout fail, so it can't finish")
        for failure in ("CrashLoop", "ImagePullError", "ContainerConfigError", "Unschedulable",
                        "ProbeFailed")  # fmt: skip
    ],
    *[
        Rule(f"{failure.lower()}-endpoints", failure, "ServiceNoEndpoints", "backends", 0.8,
             "The Service's pods are not ready, so it has no endpoints")
        for failure in ("ProbeFailed", "PodNotReady", "CrashLoop", "Evicted")
    ],
    # --- across services (calls) --------------------------------------------------
    Rule("endpoints-caller-errors", "ServiceNoEndpoints", "ErrorRateSpike", "callee_services", 0.85,
         "This workload calls a Service that has no ready endpoints"),
    Rule("downstream-caller-errors", "DownstreamErrors", "ErrorRateSpike", "callee", 0.85,
         "Calls from this workload to a dependency fail"),
    Rule("downstream-caller-latency", "DownstreamErrors", "LatencySpike", "callee", 0.6,
         "Calls from this workload to a dependency fail or retry"),
    Rule("replicas-downstream", "ReplicasUnavailable", "DownstreamErrors", "same", 0.8,
         "The called workload is missing replicas"),
    Rule("crash-downstream", "CrashLoop", "DownstreamErrors", "pods", 0.8,
         "Pods of the called workload are crash-looping"),
    Rule("logs-downstream", "LogErrorSpike", "DownstreamErrors", "pods", 0.6,
         "The called workload logs new errors"),
    Rule("errors-downstream", "ErrorRateSpike", "DownstreamErrors", "same", 0.7,
         "The called workload itself returns errors"),
    Rule("replicas-caller-errors", "ReplicasUnavailable", "ErrorRateSpike", "callee", 0.7,
         "A workload this one calls is missing replicas"),
]  # fmt: skip

# --- more changes and resources (cải tiến 07/10/2026) ----------------------------
RULES += [
    Rule("gitops-rollout", "GitOpsSync", "Rollout", "same", 0.95,
         "This rollout came from an Argo CD sync"),
    Rule("gitops-config", "GitOpsSync", "ConfigChange", "same", 0.95,
         "This ConfigMap was changed by an Argo CD sync"),
    Rule("helm-rollout", "HelmRelease", "Rollout", "same", 0.95,
         "This rollout came from a Helm upgrade"),
    Rule("helm-config", "HelmRelease", "ConfigChange", "same", 0.95,
         "This ConfigMap was changed by a Helm upgrade"),
    *[
        Rule(f"secret-{effect.lower()}", "SecretChange", effect, "config", weight,
             "The pod reads a Secret that was just changed", max_lag=SLOW)
        for effect, weight in (("CrashLoop", 0.8), ("ContainerConfigError", 0.9),
                               ("ProbeFailed", 0.6), ("LogErrorSpike", 0.6))
    ],
    Rule("leak-near-limit", "MemoryLeak", "MemoryNearLimit", "same", 0.9,
         "Memory kept growing until it reached the limit", max_lag=SLOW),
    Rule("leak-oom", "MemoryLeak", "OOMKilled", "same", 0.9,
         "Memory kept growing until the container was killed", max_lag=SLOW),
    Rule("leak-crash", "MemoryLeak", "CrashLoop", "same", 0.8,
         "Memory keeps growing and the container is killed (exit 137)",
         max_lag=SLOW, when=_killed),
    Rule("leak-restart", "MemoryLeak", "RestartSpike", "same", 0.8,
         "Memory kept growing and the container was killed (exit 137)",
         max_lag=SLOW, when=_killed),
    Rule("rollout-leak", "Rollout", "MemoryLeak", "owner", 0.6,
         "Memory started growing after the rollout", max_lag=SLOW),
]  # fmt: skip

# --- failures that travel along dependencies ----------------------------------------
# A caller fails when something it depends on is down: its pods crash on start
# ("can't connect to the database"), log errors, fail readiness, or its
# requests fail. "owner+callee+pods" = from the caller's pod to the pods of the
# workloads its workload calls — in any namespace (topology is cluster-wide).
_CALLEE_DOWN = (
    ("ReplicasUnavailable", "callee", 0.75),
    ("ServiceNoEndpoints", "callee_services", 0.8),
    ("CrashLoop", "callee+pods", 0.7),
    ("PodNotReady", "callee+pods", 0.65),
    ("RestartSpike", "callee+pods", 0.55),
    ("OOMKilled", "callee+pods", 0.6),
)
_POD_EFFECTS = ("CrashLoop", "RestartSpike", "LogErrorSpike", "ProbeFailed")
_EXISTING = {(r.cause, r.effect, r.relation) for r in RULES}
for cause, relation, weight in _CALLEE_DOWN:
    for effect in _POD_EFFECTS:
        RULES.append(
            Rule(f"dep-{cause.lower()}-{effect.lower()}", cause, effect, f"owner+{relation}",
                 weight, f"A service this pod depends on is failing ({cause})")
        )  # fmt: skip
    for effect in ("ErrorRateSpike", "LatencySpike"):
        if (cause, effect, relation) not in _EXISTING:
            RULES.append(
                Rule(f"dep-{cause.lower()}-{effect.lower()}", cause, effect, relation,
                     weight, f"A service this workload calls is failing ({cause})")
            )  # fmt: skip


def _validate(rules: list[Rule]) -> dict[str, list[Rule]]:
    """Index by effect type; fail at import on a typo rather than silently never matching."""
    ids: set[str] = set()
    by_effect: dict[str, list[Rule]] = defaultdict(list)
    for r in rules:
        problems = [
            f"unknown event type {t!r}" for t in (r.cause, r.effect) if t not in EVENT_TYPES
        ]
        if not relation_known(r.relation):
            problems.append(f"unknown relation {r.relation!r}")
        if r.id in ids:
            problems.append("duplicate id")
        if not 0 < r.weight <= 1:
            problems.append("weight must be in (0, 1]")
        if problems:
            raise ValueError(f"RCA rule {r.id}: {', '.join(problems)}")
        ids.add(r.id)
        by_effect[r.effect].append(r)
    return dict(by_effect)


BY_EFFECT = _validate(RULES)


def rules_for(effect_type: str) -> list[Rule]:
    return BY_EFFECT.get(effect_type, [])


__all__ = ["BY_EFFECT", "FAST", "RULES", "SLACK", "SLOW", "Rule", "rules_for"]
