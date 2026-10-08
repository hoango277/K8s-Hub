"""Fixes for the top root-cause candidates — computed here, never invented by the LLM.

Each candidate is derived from an event's own facts: a bad rollout knows the
previous image (changes.py stores it), a scale-to-zero knows the previous
replica count. The LLM step (report.py) may only PICK one by id; it cannot
make up an action or its parameters.

Proposing a fix goes through the normal approval flow
(approval_service.propose: dry-run, diff, a human approves). The actor always
has role "user" so a fix suggested by RCA is NEVER executed automatically,
even when K8S_EXECUTION_MODE=auto and an engineer clicked "Propose" — the
approver still has to look at the diff.

Causes with no safe automatic fix (memory limits, a full node, a ConfigMap
edit) get ADVICE: a sentence for the report, no button.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.modules.nl_command import planner
from app.modules.nl_command.planner import ActionPlan

Action = Literal["set_image", "scale", "advice"]
_WORKLOAD_KINDS = {
    "Deployment": "deployment",
    "StatefulSet": "statefulset",
    "DaemonSet": "daemonset",
}


@dataclass
class Fix:
    id: str
    event_id: str
    action: Action
    title: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def proposable(self) -> bool:
        return self.action != "advice"

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "proposable": self.proposable}


def _workload_kind(entity: dict[str, Any]) -> str | None:
    return _WORKLOAD_KINDS.get(entity.get("sub") or "")


def _fixes_for(ev: dict[str, Any]) -> list[Fix]:
    """Fix candidates for ONE event (its JSON form, as stored in rca_runs.graph)."""
    etype, ent, attrs = ev["type"], ev["entity"], ev.get("attrs") or {}
    ns, name, eid = ent.get("namespace"), ent.get("name"), ev["id"]
    kind = _workload_kind(ent)
    out: list[Fix] = []

    if etype == "Rollout" and kind and attrs.get("images"):
        for container, (old, new) in attrs["images"].items():
            if old:
                out.append(Fix(
                    f"rollback:{eid}:{container}", eid, "set_image",
                    f"Roll back {name} container {container} to {old} (from {new})",
                    {"kind": kind, "namespace": ns, "name": name, "container": container,
                     "image": old},
                ))  # fmt: skip
    elif etype == "Rollout":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Review what changed in the rollout of {name} "
                       f"({', '.join(attrs.get('env_changed') or []) or 'pod template'}) "
                       "and revert it, e.g. `kubectl rollout undo`."))  # fmt: skip
    elif (
        etype in ("ScaleChange", "ApprovalExecuted")
        and kind
        and attrs.get("action", "scale") == "scale"
    ):
        previous = attrs.get("previous")
        if attrs.get("replicas") == 0 or previous:
            target = previous or 1
            out.append(Fix(
                f"scale:{eid}", eid, "scale",
                f"Scale {name} back to {target} replica{'s' if target != 1 else ''}",
                {"kind": kind, "namespace": ns, "name": name, "replicas": int(target)},
            ))  # fmt: skip
    elif etype == "GitOpsSync":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Roll Argo CD application {attrs.get('application', '?')} back to "
                       f"the revision before {attrs.get('revision', '?')} (History and "
                       "rollback in Argo CD), or revert the commit — a manual change "
                       "would be overwritten."))  # fmt: skip
    elif etype == "HelmRelease":
        version = attrs.get("version") or 0
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Roll Helm release {attrs.get('release', '?')} back: `helm rollback "
                       f"{attrs.get('release', '?')} {max(version - 1, 1)} -n "
                       f"{attrs.get('release_namespace', ns)}`."))  # fmt: skip
    elif etype == "SecretChange":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Check the recent change to Secret {name} (rotated password, "
                       "expired certificate) and restart the pods that read it once it "
                       "is fixed."))  # fmt: skip
    elif etype == "MemoryLeak":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Container {attrs.get('container', '?')} in {name} keeps growing "
                       f"(~{attrs.get('growth_per_hour', 0):.0%} of its limit per hour): profile "
                       "it for a leak; a restart only buys time."))  # fmt: skip
    elif etype in ("MemoryNearLimit", "OOMKilled"):
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Raise the memory limit of container {attrs.get('container', '?')} in "
                       f"{name}, or find what uses the memory (peak "
                       f"{attrs.get('peak', 'near')} of the limit)."))  # fmt: skip
    elif etype == "ConfigChange":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Review the recent edit of ConfigMap {name} and restore the previous "
                       "values; pods read it at start-up."))  # fmt: skip
    elif etype in ("NodeSaturated", "NodePressure", "NodeNotReady"):
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Node {name}: free capacity (lower requests of idle workloads, remove "
                       "unused ones) or add a node."))  # fmt: skip
    elif etype == "PvcPending":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Volume claim {name} can't bind: check that storage class "
                       f"{attrs.get('storage_class') or '(default)'} exists and can "
                       "provision."))  # fmt: skip
    elif etype == "ImagePullError":
        out.append(Fix(f"advice:{eid}", eid, "advice",
                       f"Check the image name/tag {attrs.get('image') or ''} and the registry "
                       "credentials (imagePullSecrets)."))  # fmt: skip
    elif etype == "ContainerConfigError":
        out.append(
            Fix(
                f"advice:{eid}",
                eid,
                "advice",
                "Create the missing ConfigMap/Secret or key the container references.",
            )
        )
    return out


def candidates(graph: dict[str, Any], chains: list[list[str]]) -> list[Fix]:
    """Fixes for the ranked root causes, in rank order.

    `chains`: each hypothesis's chain (root first). When the root itself has
    no concrete fix, the next events of its chain are tried — an approved
    "scale to 0" (ApprovalExecuted) has no replica count, but the ScaleChange
    it caused does.
    """
    events = {e["id"]: e for e in graph.get("events") or []}
    out: list[Fix] = []
    seen: set[str] = set()
    for chain in chains:
        found: list[Fix] = []
        for eid in chain[:3]:
            if eid in events:
                found += [f for f in _fixes_for(events[eid]) if f.id not in seen]
            if any(f.proposable for f in found):
                break
        seen |= {f.id for f in found}
        out += found
    return out


async def build_plan(fix: Fix) -> ActionPlan:
    """The approval plan for a fix (raises ToolInputError when it no longer applies)."""
    p = fix.params
    if fix.action == "set_image":
        return await planner.plan_set_image(
            p["kind"], p["namespace"], p["name"], p["container"], p["image"]
        )
    if fix.action == "scale":
        return await planner.plan_scale(p["kind"], p["namespace"], p["name"], p["replicas"])
    raise ValueError("This suggestion is advice only; there is no change to propose.")


__all__ = ["Fix", "build_plan", "candidates"]
