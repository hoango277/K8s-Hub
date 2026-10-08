"""Diagnoses nobody clicked: Alertmanager alerts (webhook) and the periodic scan.

Alertmanager sends a batch of alerts per notification (webhook payload v4).
Each FIRING alert with a `namespace` label becomes a diagnosis of that
namespace, focused on the workload/pod its labels name. Two things keep this
from flooding the system:

  - one run per object (`subject()`: a pod counts as its workload) per
    SUBJECT_DEDUP_MINUTES, whatever alert names it — seen on lab1: one bad
    image fired two alerts (ErrImagePull, then ImagePullBackOff) in two
    notifications at the same second, and both started a diagnosis;
  - an alert fingerprint that already has a run in the last DEDUP_MINUTES is
    skipped: Alertmanager re-sends unresolved alerts every repeat_interval.
Notifications are handled one at a time (a lock), so concurrent ones see each
other's runs.

These runs are started by "the system", not a person: requested_by is NULL,
every role can see them, and a fix they suggest still has to be proposed by a
user and approved by an engineer (remediation.py).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db.models.rca import RcaRun
from app.db.session import get_sessionmaker
from app.modules.rca import pipeline
from app.modules.tools.guard import ToolInputError, check_name, check_namespace

logger = logging.getLogger(__name__)

ALERT_REQUESTER = "alertmanager@k8s-hub"
SCAN_REQUESTER = "scanner@k8s-hub"
DEDUP_MINUTES = 60
# One diagnosis per object for this long, whatever alert names it: the first
# run already explains the incident; more runs only cost LLM calls.
SUBJECT_DEDUP_MINUTES = 10
MAX_RUNS_PER_NOTIFICATION = 5

# Alert label → target kind, best first. kube-state-metrics alerts carry these.
_TARGET_LABELS = (
    ("deployment", "Workload"),
    ("statefulset", "Workload"),
    ("daemonset", "Workload"),
    ("pod", "Pod"),
    ("service", "Service"),
)


@dataclass
class AlertTarget:
    namespace: str
    kind: str | None
    name: str | None
    fingerprint: str
    alertname: str

    @property
    def key(self) -> tuple[str, str | None, str | None]:
        return (self.namespace, self.kind, self.name)


def parse_alerts(payload: dict[str, Any]) -> tuple[list[AlertTarget], list[str]]:
    """Firing alerts that can be diagnosed, and why the others were skipped."""
    targets: list[AlertTarget] = []
    skipped: list[str] = []
    for alert in payload.get("alerts") or []:
        labels = alert.get("labels") or {}
        name = labels.get("alertname", "?")
        if alert.get("status", "firing") != "firing":
            continue  # resolved: nothing to diagnose
        ns = labels.get("namespace")
        if not ns:
            skipped.append(f"{name}: no namespace label")
            continue
        try:
            check_namespace(ns)
        except ToolInputError as exc:
            skipped.append(f"{name}: {exc}")
            continue
        kind = obj = None
        for label, target_kind in _TARGET_LABELS:
            if labels.get(label):
                try:
                    obj = check_name(label, labels[label])
                except ToolInputError:
                    continue
                kind = target_kind
                break
        fingerprint = str(alert.get("fingerprint") or f"{name}/{ns}/{obj or ''}")[:64]
        targets.append(AlertTarget(ns, kind, obj, fingerprint, name))
    return targets, skipped


async def _recent_fingerprints(fingerprints: list[str]) -> set[str]:
    since = datetime.now(UTC) - timedelta(minutes=DEDUP_MINUTES)
    async with get_sessionmaker()() as db:
        rows = await db.scalars(
            select(RcaRun.alert_fingerprint).where(
                RcaRun.alert_fingerprint.in_(fingerprints), RcaRun.created_at >= since
            )
        )
        return set(rows.all())


def subject(namespace: str, kind: str | None, name: str | None) -> tuple[str, str]:
    """What a diagnosis is about, so different alerts on one thing count once.

    A failing rollout fires on the pod (`web-7887c7b74c-vc56k`, first
    ErrImagePull, then ImagePullBackOff: two fingerprints) and later on the
    Deployment (`web`). The pod's owner is its name minus the ReplicaSet hash
    and pod suffix — a heuristic, but alerts carry no ownerReferences.
    """
    if kind == "Pod" and name and name.count("-") >= 2:
        name = name.rsplit("-", 2)[0]
    return namespace, name or ""


async def _recent_subjects() -> set[tuple[str, str]]:
    since = datetime.now(UTC) - timedelta(minutes=SUBJECT_DEDUP_MINUTES)
    async with get_sessionmaker()() as db:
        rows = await db.execute(
            select(RcaRun.namespace, RcaRun.target_kind, RcaRun.target_name).where(
                RcaRun.trigger == "alert", RcaRun.created_at >= since
            )
        )
        return {subject(*r) for r in rows.all()}


# Alertmanager sends one notification per alert group, often several at the
# same second: without this lock two of them would both see "no recent run"
# and start duplicate diagnoses.
_lock = asyncio.Lock()


async def handle_alerts(payload: dict[str, Any]) -> dict[str, Any]:
    async with _lock:
        return await _handle(payload)


async def _handle(payload: dict[str, Any]) -> dict[str, Any]:
    targets, skipped = parse_alerts(payload)
    recent = await _recent_fingerprints([t.fingerprint for t in targets]) if targets else set()
    subjects = await _recent_subjects() if targets else set()

    started: list[str] = []
    for t in targets:
        if t.fingerprint in recent:
            skipped.append(f"{t.alertname}: already diagnosed in the last {DEDUP_MINUTES} min")
            continue
        about = subject(t.namespace, t.kind, t.name)
        if about in subjects:
            skipped.append(
                f"{t.alertname}: {'/'.join(filter(None, about))} already has a diagnosis "
                f"from the last {SUBJECT_DEDUP_MINUTES} min"
            )
            continue
        if len(started) >= MAX_RUNS_PER_NOTIFICATION:
            skipped.append(f"{t.alertname}: too many targets in one notification")
            continue
        subjects.add(about)
        run = await pipeline.create_run(
            namespace=t.namespace,
            trigger="alert",
            requested_by=None,
            requested_by_email=ALERT_REQUESTER,
            target_kind=t.kind,
            target_name=t.name,
            alert_fingerprint=t.fingerprint,
        )
        pipeline.spawn(pipeline.run_with_report(run.id, with_report=True))
        started.append(str(run.id))
        logger.info(
            "Alert %s: diagnosing %s (run %s)", t.alertname, "/".join(filter(None, t.key)), run.id
        )
    return {"started": started, "skipped": skipped}


__all__ = [
    "ALERT_REQUESTER",
    "DEDUP_MINUTES",
    "SCAN_REQUESTER",
    "AlertTarget",
    "handle_alerts",
    "parse_alerts",
]
