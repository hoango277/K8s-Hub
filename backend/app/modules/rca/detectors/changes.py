"""Changes made by someone — Groot's "developer activities", the usual root cause.

  Rollout          a workload got a new pod template in the window: a new
                   ReplicaSet (Deployment) or ControllerRevision (StatefulSet,
                   DaemonSet). The template is diffed against the previous one
                   (image, env NAMES, resources, command) so rules can ask "did
                   the image change?" instead of guessing.
  ScaleChange      replicas changed without a new template (deployment events).
  ConfigChange     a ConfigMap a pod uses was edited (or created) in the window,
                   timed by its managedFields.
  SecretChange     the same for Secrets — from METADATA only (managedFields
                   times, never values: resources.list_secret_metadata).
  GitOpsSync       Argo CD deployed a new revision of an Application that
                   manages the object (Application.status.history).
  HelmRelease      a Helm release that manages the object got a new revision
                   (Helm's release Secrets, metadata only).
  ApprovalExecuted a change K8s-Hub itself applied after approval.

Something CREATED in the window is a weaker suspect than something EDITED
(the evaluation's missing-key scenario ranked a freshly created ConfigMap #2):
created ones carry `prior_factor`. Env VALUES are never copied into evidence:
only which variable names changed.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.modules.rca.detectors import Context, Found, hhmm, meta, parse_time
from app.modules.rca.model import Entity
from app.modules.rca.topology import workload

REVISION = "deployment.kubernetes.io/revision"
_SCALED = re.compile(
    r"Scaled (?P<dir>up|down) replica set (?P<rs>\S+?)(?: from (?P<from>\d+))? to (?P<to>\d+)"
)
_WORKLOAD_KINDS = {
    "deployment": "Deployment",
    "statefulset": "StatefulSet",
    "daemonset": "DaemonSet",
}
CREATED_FACTOR = 0.4
HELM_RELEASE = "meta.helm.sh/release-name"
HELM_NAMESPACE = "meta.helm.sh/release-namespace"


def _ns(obj: dict[str, Any]) -> str:
    return meta(obj).get("namespace") or ""


def _template(rs: dict[str, Any]) -> dict[str, Any]:
    return ((rs.get("spec") or {}).get("template") or {}).get("spec") or {}


def _containers(rs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c.get("name", "?"): c for c in _template(rs).get("containers") or []}


def diff_templates(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """What changed in the pod template between two ReplicaSets (or revision data)."""
    before, after = _containers(old), _containers(new)
    images, env, resources, command = {}, [], [], []
    for name, c in after.items():
        prev = before.get(name)
        if prev is None:
            images[name] = [None, c.get("image")]
            continue
        if prev.get("image") != c.get("image"):
            images[name] = [prev.get("image"), c.get("image")]
        old_env = {e.get("name"): e for e in prev.get("env") or []}
        new_env = {e.get("name"): e for e in c.get("env") or []}
        env += [
            f"{name}.{k}"
            for k in sorted(set(old_env) | set(new_env))
            if old_env.get(k) != new_env.get(k)
        ]
        if (prev.get("envFrom") or []) != (c.get("envFrom") or []):
            env.append(f"{name}.envFrom")
        if (prev.get("resources") or {}) != (c.get("resources") or {}):
            resources.append(name)
        if (prev.get("command"), prev.get("args")) != (c.get("command"), c.get("args")):
            command.append(name)
    old_vols = [v.get("name") for v in _template(old).get("volumes") or []]
    new_vols = [v.get("name") for v in _template(new).get("volumes") or []]
    return {
        "images": images,
        "env_changed": env,
        "resources_changed": resources,
        "command_changed": command,
        "volumes_changed": old_vols != new_vols,
    }


def _describe(diff: dict[str, Any]) -> str:
    parts = [f"image {c}: {o or '-'} → {n}" for c, (o, n) in diff["images"].items()]
    if diff["env_changed"]:
        parts.append("env changed: " + ", ".join(diff["env_changed"][:6]))
    if diff["resources_changed"]:
        parts.append("resources changed: " + ", ".join(diff["resources_changed"]))
    if diff["command_changed"]:
        parts.append("command/args changed: " + ", ".join(diff["command_changed"]))
    if diff["volumes_changed"]:
        parts.append("volumes changed")
    return "; ".join(parts) or "pod template changed (no image/env/resources difference)"


def _add_rollout(
    found: Found,
    w: Entity,
    at: datetime,
    revision: Any,
    current: tuple[str, dict[str, Any]],
    previous: tuple[str, dict[str, Any]],
) -> None:
    """`current`/`previous`: (object name, object whose spec.template is the pod template)."""
    diff = diff_templates(previous[1], current[1])
    found.add(
        "Rollout",
        w,
        at,
        f"New rollout of {w.name} (revision {revision}): {_describe(diff)}",
        severity="info",
        evidence=[
            (
                "k8s",
                f"{current[0]} created {hhmm(at)}, previous {previous[0]}: {_describe(diff)}",
                at,
            )
        ],
        revision=revision,
        replicaset=current[0],
        previous_replicaset=previous[0],
        previous_images={n: c.get("image") for n, c in _containers(previous[1]).items()},
        image_changed=bool(diff["images"]),
        **{k: v for k, v in diff.items() if k != "images"},
        images=diff["images"],
    )


def _rollouts(
    ctx: Context, found: Found
) -> tuple[dict[tuple[str, str], datetime], dict[tuple[str, str], str]]:
    """Deployment rollouts.

    Returns ({(ns, new RS): creation time}, {(ns, deployment): newest RS}).
    """
    by_deploy: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rs in ctx.objects("replicasets"):
        for ref in meta(rs).get("ownerReferences") or []:
            if ref.get("kind") == "Deployment":
                by_deploy[(_ns(rs), ref["name"])].append(rs)
    created: dict[tuple[str, str], datetime] = {}
    newest: dict[tuple[str, str], str] = {}
    for (ns, deploy), sets in by_deploy.items():
        sets.sort(key=lambda r: int((meta(r).get("annotations") or {}).get(REVISION, 0) or 0))
        newest[(ns, deploy)] = meta(sets[-1])["name"]
        for i, rs in enumerate(sets):
            at = parse_time(meta(rs).get("creationTimestamp"))
            if not ctx.in_window(at):
                continue
            # Every new ReplicaSet counts as "born" — also the first one of a new
            # Deployment, whose 0 → 1 scale-up is creation, not someone scaling
            # (seen in the evaluation: a fresh Deployment ranked "ScaleChange" #2).
            created[(ns, meta(rs)["name"])] = at  # type: ignore[assignment]
            if i == 0:
                continue  # nothing to diff against: a new Deployment, not a rollout
            revision = (meta(rs).get("annotations") or {}).get(REVISION)
            _add_rollout(
                found, workload(ns, deploy, "Deployment"), at, revision,  # type: ignore[arg-type]
                (meta(rs)["name"], rs), (meta(sets[i - 1])["name"], sets[i - 1]),
            )  # fmt: skip
    return created, newest


def _revision_rollouts(ctx: Context, found: Found) -> None:
    """StatefulSet/DaemonSet rollouts: their history is ControllerRevisions, whose
    `data` holds the pod template in the same shape as a ReplicaSet spec."""
    by_owner: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for cr in ctx.objects("controllerrevisions"):
        for ref in meta(cr).get("ownerReferences") or []:
            if ref.get("kind") in ("StatefulSet", "DaemonSet"):
                by_owner[(_ns(cr), ref["kind"], ref["name"])].append(cr)
    for (ns, kind, name), revs in by_owner.items():
        revs.sort(key=lambda r: int(r.get("revision") or 0))
        for i in range(1, len(revs)):
            at = parse_time(meta(revs[i]).get("creationTimestamp"))
            if not ctx.in_window(at):
                continue
            _add_rollout(
                found, workload(ns, name, kind), at, revs[i].get("revision"),  # type: ignore[arg-type]
                (meta(revs[i])["name"], revs[i].get("data") or {}),
                (meta(revs[i - 1])["name"], revs[i - 1].get("data") or {}),
            )  # fmt: skip


def _scales(
    ctx: Context,
    found: Found,
    new_rs: dict[tuple[str, str], datetime],
    newest: dict[tuple[str, str], str],
) -> None:
    for e in ctx.kevents:
        if e.kind != "Deployment" or e.reason != "ScalingReplicaSet":
            continue
        if not ctx.in_scope(e.namespace):
            continue
        m = _SCALED.search(e.message)
        if not m:
            continue
        ns = e.namespace or ""
        # A rollout scales the new ReplicaSet up and the old ones down; a real
        # "kubectl scale" changes the newest one long after it was created.
        if m["rs"] != newest.get((ns, e.name)):
            continue
        born = new_rs.get((ns, m["rs"]))
        if born and m["dir"] == "up" and (e.at - born).total_seconds() < 300:
            # The rollout (or a new Deployment) bringing its own ReplicaSet up —
            # already an event. Scaling the newest ReplicaSet DOWN is never part
            # of a rollout: a "scale to 0" minutes after creation is still a change.
            continue
        found.add(
            "ScaleChange",
            workload(ns, e.name, "Deployment"),
            e.at,
            f"{e.name} scaled {m['dir']} to {m['to']} replicas",
            severity="info",
            evidence=[(e.source, f"{e.reason}: {e.message}", e.at)],
            replicas=int(m["to"]),
            previous=int(m["from"]) if m["from"] else None,
        )


def _edit_time(m: dict[str, Any]) -> tuple[datetime | None, str]:
    """(when, "edited"|"created") from managedFields; edits a couple of seconds
    after creation are the creator finishing its own write."""
    created = parse_time(m.get("creationTimestamp"))
    updates = [
        t
        for t in (parse_time(f.get("time")) for f in m.get("managedFields") or [])
        if t and created and t - created > timedelta(seconds=2)
    ]
    return (max(updates), "edited") if updates else (created, "created")


def _config_changes(ctx: Context, found: Found) -> None:
    for cm in ctx.objects("configmaps"):
        m = meta(cm)
        name, ns = m["name"], _ns(cm)
        entity = Entity("ConfigMap", ns, name)
        if name == "kube-root-ca.crt" or entity.key not in ctx.topo.entities:
            continue  # not used by any pod: can't explain a symptom
        at, how = _edit_time(m)
        if not ctx.in_window(at):
            continue
        keys = sorted(cm.get("data") or {})
        found.add(
            "ConfigChange",
            entity,
            at,  # type: ignore[arg-type]
            f"ConfigMap {name} was {how} at {hhmm(at)}",
            severity="info",
            evidence=[
                (
                    "k8s",
                    f"ConfigMap {ns}/{name} {how} {hhmm(at)}; keys: " + ", ".join(keys[:10]),
                    at,
                )
            ],
            how=how,
            keys=keys,
            prior_factor=CREATED_FACTOR if how == "created" else 1.0,
        )


def _secret_changes(ctx: Context, found: Found) -> None:
    for s in ctx.snap.secret_metadata:
        m = s["metadata"]
        if not ctx.in_scope(m.get("namespace")) or (m.get("labels") or {}).get("owner") == "helm":
            continue
        entity = Entity("Secret", m.get("namespace"), m.get("name") or "")
        if entity.key not in ctx.topo.entities:
            continue  # no pod references it
        at, how = _edit_time(m)
        if not ctx.in_window(at):
            continue
        managers = sorted(
            {f.get("manager") for f in m.get("managedFields") or [] if f.get("manager")}
        )
        found.add(
            "SecretChange",
            entity,
            at,  # type: ignore[arg-type]
            f"Secret {entity.name} was {how} at {hhmm(at)}",
            severity="info",
            evidence=[("k8s", f"Secret {entity.namespace}/{entity.name} {how} {hhmm(at)} by "
                       f"{', '.join(managers) or 'unknown'} (metadata only)", at)],
            how=how,
            prior_factor=CREATED_FACTOR if how == "created" else 1.0,
        )  # fmt: skip


def _managed_entity(kind: str, ns: str, name: str) -> Entity | None:
    if kind in ("Deployment", "StatefulSet", "DaemonSet"):
        return workload(ns, name, kind)
    if kind == "ConfigMap":
        return Entity("ConfigMap", ns, name)
    return None


def _gitops_syncs(ctx: Context, found: Found) -> None:
    for app in ctx.snap.argocd_apps:
        status = app.get("status") or {}
        syncs = [
            h for h in status.get("history") or [] if ctx.in_window(parse_time(h.get("deployedAt")))
        ]
        if not syncs:
            continue
        last = max(syncs, key=lambda h: h.get("deployedAt") or "")
        at = parse_time(last.get("deployedAt"))
        revision = str(last.get("revision") or "?")[:12]
        for r in status.get("resources") or []:
            ns = r.get("namespace") or ""
            entity = _managed_entity(r.get("kind", ""), ns, r.get("name", ""))
            if entity is None or not ctx.in_scope(ns):
                continue
            found.add(
                "GitOpsSync",
                entity,
                at,  # type: ignore[arg-type]
                f"Argo CD application {meta(app)['name']} synced revision {revision}",
                severity="info",
                evidence=[("argocd", f"Application {meta(app)['name']}: revision {revision} "
                           f"deployed at {hhmm(at)} ({len(syncs)} sync(s) in the window)", at)],
                application=meta(app)["name"],
                revision=revision,
            )  # fmt: skip


def _helm_releases(ctx: Context, found: Found) -> None:
    # (namespace, release) -> newest revision created in the window
    upgrades: dict[tuple[str, str], tuple[datetime, int, str]] = {}
    for s in ctx.snap.secret_metadata:
        m = s["metadata"]
        labels = m.get("labels") or {}
        if labels.get("owner") != "helm":
            continue
        at = parse_time(m.get("creationTimestamp"))
        version = int(labels.get("version") or 0)
        key = (m.get("namespace") or "", labels.get("name") or "")
        if ctx.in_window(at) and (key not in upgrades or version > upgrades[key][1]):
            upgrades[key] = (at, version, labels.get("status") or "?")  # type: ignore[assignment]
    if not upgrades:
        return
    for attr, kind in (("deployments", "Deployment"), ("statefulsets", "StatefulSet"),
                       ("daemonsets", "DaemonSet"), ("configmaps", "ConfigMap")):  # fmt: skip
        for obj in ctx.objects(attr):
            ann = meta(obj).get("annotations") or {}
            key = (ann.get(HELM_NAMESPACE) or _ns(obj), ann.get(HELM_RELEASE) or "")
            if key not in upgrades:
                continue
            at, version, state = upgrades[key]
            entity = _managed_entity(kind, _ns(obj), meta(obj)["name"])
            if entity is None:
                continue
            found.add(
                "HelmRelease",
                entity,
                at,
                f"Helm release {key[1]} moved to revision {version} ({state})",
                severity="info",
                evidence=[("helm", f"release {key[0]}/{key[1]} revision {version} {state} at "
                           f"{hhmm(at)} (from Helm's release record, metadata only)", at)],
                release=key[1],
                release_namespace=key[0],
                version=version,
                prior_factor=CREATED_FACTOR if version == 1 else 1.0,
            )  # fmt: skip


def _target_entity(ns: str, target: str | None) -> Entity | None:
    if not target or "/" not in target:
        return None
    kind, _, name = target.split(",")[0].strip().partition("/")
    if kind.lower() in _WORKLOAD_KINDS:
        return workload(ns, name, _WORKLOAD_KINDS[kind.lower()])
    if kind == "Pod":
        return Entity("Pod", ns, name)
    if kind == "ConfigMap":
        return Entity("ConfigMap", ns, name)
    return None


def _approvals(ctx: Context, found: Found) -> None:
    for a in ctx.approvals:
        at = a.get("executed_at")
        entity = _target_entity(a.get("namespace") or "", a.get("target"))
        if entity is None or not ctx.in_window(at) or not ctx.in_scope(entity.namespace):
            continue
        found.add(
            "ApprovalExecuted",
            entity,
            at,
            f"Approved change applied: {a.get('title', '')}",
            severity="info",
            evidence=[
                (
                    "approvals",
                    f"{a.get('title', '')} — requested by {a.get('requested_by_email')}, "
                    f"approved by {a.get('decided_by_email')}, {a.get('status')} at {hhmm(at)}",
                    at,
                )
            ],
            approval_id=str(a.get("id")),
            action=a.get("kind"),
        )


async def detect(ctx: Context, found: Found) -> None:
    new_rs, newest = _rollouts(ctx, found)
    _revision_rollouts(ctx, found)
    _scales(ctx, found, new_rs, newest)
    _config_changes(ctx, found)
    _secret_changes(ctx, found)
    _gitops_syncs(ctx, found)
    _helm_releases(ctx, found)
    _approvals(ctx, found)


__all__ = ["CREATED_FACTOR", "REVISION", "detect", "diff_templates"]
