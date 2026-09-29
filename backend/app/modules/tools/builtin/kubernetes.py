"""Built-in tools: read pods, deployments, events and container logs.

Output is written for the model to reason over, not for kubectl parity:
problems come first (CrashLoopBackOff, OOMKilled, not ready), numbers are
already interpreted (age, restarts), and every result is size-capped so one
noisy namespace can't flood the context window.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import tool

from app.integrations.k8s import client as k8s
from app.modules.tools.guard import ToolInputError, check_name, check_namespace, clamp
from app.modules.tools.schema import Category, Danger, ToolSpec

MAX_LOG_CHARS = 6000
_SELECTOR = re.compile(r"^[A-Za-z0-9._/=,!() -]{1,200}$")


def _age(ts: datetime | None) -> str:
    if ts is None:
        return "?"
    seconds = int((datetime.now(UTC) - ts).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _container_problem(status: Any) -> str | None:
    """The most telling thing about one container, or None if it is healthy."""
    state = status.state
    if state and state.waiting and state.waiting.reason not in (None, "ContainerCreating"):
        return f"{status.name}: {state.waiting.reason}"
    if state and state.terminated and state.terminated.exit_code != 0:
        t = state.terminated
        return f"{status.name}: terminated {t.reason} (exit {t.exit_code})"
    last = status.last_state.terminated if status.last_state else None
    if last and last.reason in ("OOMKilled", "Error"):
        return f"{status.name}: last exit {last.reason} (exit {last.exit_code})"
    if not status.ready:
        return f"{status.name}: not ready"
    return None


def _pod_row(pod: Any) -> tuple[bool, str]:
    statuses = pod.status.container_statuses or []
    ready = sum(1 for s in statuses if s.ready)
    restarts = sum(s.restart_count for s in statuses)
    problems = [p for s in statuses if (p := _container_problem(s))]
    phase = pod.status.phase or "?"
    if phase not in ("Running", "Succeeded") and not problems:
        problems.append(f"phase {phase}")
    row = (
        f"- {pod.metadata.name}: {phase}, ready {ready}/{len(statuses)}, restarts {restarts}, "
        f"age {_age(pod.metadata.creation_timestamp)}, node {pod.spec.node_name or '-'}"
    )
    if problems:
        row += " — " + "; ".join(problems)
    return bool(problems), row


def _fail(exc: Exception) -> str:
    return str(exc)


@tool(parse_docstring=True)
async def list_pods(namespace: str, label_selector: str | None = None) -> str:
    """List pods in a namespace with their health: phase, readiness, restarts and problems.

    Use first when the user asks what is failing or why an app is down. Pods
    with problems (CrashLoopBackOff, OOMKilled, not ready) are listed first.

    Args:
        namespace: Kubernetes namespace.
        label_selector: optional label selector, e.g. "app=checkout".
    """
    try:
        check_namespace(namespace)
        if label_selector and not _SELECTOR.match(label_selector):
            raise ToolInputError(f"Invalid label selector: {label_selector!r}.")
        pods = await k8s.list_pods(namespace, label_selector)
    except (ToolInputError, k8s.K8sError) as exc:
        return _fail(exc)
    if not pods:
        return f"No pods in namespace {namespace}" + (
            f" matching {label_selector}." if label_selector else "."
        )
    rows = sorted((_pod_row(p) for p in pods), key=lambda r: (not r[0], r[1]))
    unhealthy = sum(1 for bad, _ in rows if bad)
    head = f"{len(pods)} pod(s) in {namespace}, {unhealthy} with problems:"
    shown = [r for _, r in rows[:50]]
    if len(rows) > 50:
        shown.append(f"… {len(rows) - 50} more healthy pods not shown")
    return "\n".join([head, *shown])


@tool(parse_docstring=True)
async def describe_pod(namespace: str, name: str) -> str:
    """Details of one pod: container states and last exit reasons, resources, and recent events.

    Use to find WHY a pod is unhealthy: OOMKilled, image pull errors, failing
    probes, scheduling problems all show up here.

    Args:
        namespace: Kubernetes namespace.
        name: exact pod name (see list_pods).
    """
    try:
        check_namespace(namespace)
        check_name("pod", name)
        pod = await k8s.read_pod(namespace, name)
        events = await k8s.list_events(namespace, involved_name=name)
    except (ToolInputError, k8s.K8sError) as exc:
        return _fail(exc)

    lines = [
        f"Pod {namespace}/{name}: {pod.status.phase}, node {pod.spec.node_name or '-'}, "
        f"age {_age(pod.metadata.creation_timestamp)}"
    ]
    bad_conditions = [c for c in pod.status.conditions or [] if c.status != "True"]
    for c in bad_conditions:
        lines.append(f"  condition {c.type}=False: {c.reason or ''} {c.message or ''}".rstrip())

    specs = {c.name: c for c in pod.spec.containers or []}
    for s in pod.status.container_statuses or []:
        spec = specs.get(s.name)
        res = spec.resources if spec else None
        limits = (res.limits or {}) if res else {}
        requests = (res.requests or {}) if res else {}
        lines.append(
            f"Container {s.name} ({s.image}): ready={s.ready}, restarts={s.restart_count}, "
            f"requests={dict(requests) or '-'}, limits={dict(limits) or '-'}"
        )
        st = s.state
        if st and st.waiting:
            lines.append(f"  now: waiting {st.waiting.reason}: {st.waiting.message or ''}".rstrip())
        elif st and st.terminated:
            lines.append(f"  now: terminated {st.terminated.reason} exit {st.terminated.exit_code}")
        elif st and st.running:
            lines.append(f"  now: running since {_age(st.running.started_at)} ago")
        last = s.last_state.terminated if s.last_state else None
        if last:
            lines.append(
                f"  last exit: {last.reason} exit {last.exit_code}, {_age(last.finished_at)} ago"
            )

    recent = sorted(
        events,
        key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
        reverse=True,
    )[:15]
    if recent:
        lines.append("Recent events (newest first):")
        for e in recent:
            when = _age(e.last_timestamp or e.event_time or e.metadata.creation_timestamp)
            count = f" x{e.count}" if e.count and e.count > 1 else ""
            lines.append(f"  - {when} ago {e.type} {e.reason}{count}: {e.message}")
    else:
        lines.append("No recent events for this pod.")
    return "\n".join(lines)


@tool(parse_docstring=True)
async def get_pod_logs(
    namespace: str,
    name: str,
    container: str | None = None,
    previous: bool = False,
    tail_lines: int = 100,
) -> str:
    """The last lines of a container's log, straight from the Kubernetes API.

    Use previous=True for a crash-looping container: the CURRENT instance has
    usually just started, while the previous one holds the error that killed it.

    Args:
        namespace: Kubernetes namespace.
        name: exact pod name.
        container: container name; required only when the pod has several.
        previous: read the log of the previous (crashed) instance.
        tail_lines: how many lines from the end, 1–500 (default 100).
    """
    try:
        check_namespace(namespace)
        check_name("pod", name)
        if container:
            check_name("container", container)
        text = await k8s.pod_logs(
            namespace,
            name,
            container=container,
            previous=previous,
            tail_lines=clamp(tail_lines, 1, 500),
        )
    except (ToolInputError, k8s.K8sError) as exc:
        return _fail(exc)
    if not text.strip():
        return "The log is empty."
    if len(text) > MAX_LOG_CHARS:
        # Keep the END: the error that matters is at the bottom of a log.
        text = f"… (earlier lines cut)\n{text[-MAX_LOG_CHARS:]}"
    return text


@tool(parse_docstring=True)
async def list_events(namespace: str, warnings_only: bool = True, since_minutes: int = 60) -> str:
    """Recent Kubernetes events in a namespace (scheduling failures, probe failures, kills, pulls).

    Use to see what the cluster itself reported around the time of a problem.

    Args:
        namespace: Kubernetes namespace.
        warnings_only: only Warning events (default true).
        since_minutes: how far back, 1–1440 (default 60).
    """
    try:
        check_namespace(namespace)
        events = await k8s.list_events(namespace)
    except (ToolInputError, k8s.K8sError) as exc:
        return _fail(exc)
    window = clamp(since_minutes, 1, 1440) * 60
    now = datetime.now(UTC)

    def when(e: Any) -> datetime:
        return e.last_timestamp or e.event_time or e.metadata.creation_timestamp

    picked = [
        e
        for e in events
        if (not warnings_only or e.type == "Warning") and (now - when(e)).total_seconds() <= window
    ]
    if not picked:
        kind = "warning events" if warnings_only else "events"
        return f"No {kind} in {namespace} in the last {since_minutes} minutes."
    picked.sort(key=when, reverse=True)
    lines = [f"{len(picked)} event(s) in {namespace}, newest first:"]
    for e in picked[:30]:
        obj = f"{e.involved_object.kind}/{e.involved_object.name}"
        count = f" x{e.count}" if e.count and e.count > 1 else ""
        lines.append(f"- {_age(when(e))} ago {e.type} {e.reason}{count} {obj}: {e.message}")
    return "\n".join(lines)


@tool(parse_docstring=True)
async def list_deployments(namespace: str) -> str:
    """Deployments in a namespace: ready vs desired replicas, images and rollout conditions.

    Use to spot a stuck rollout or a deployment with fewer ready replicas than desired.

    Args:
        namespace: Kubernetes namespace.
    """
    try:
        check_namespace(namespace)
        items = await k8s.list_deployments(namespace)
    except (ToolInputError, k8s.K8sError) as exc:
        return _fail(exc)
    if not items:
        return f"No deployments in {namespace}."
    lines = [f"{len(items)} deployment(s) in {namespace}:"]
    for d in sorted(items, key=lambda d: d.metadata.name):
        want = d.spec.replicas or 0
        ready = d.status.ready_replicas or 0
        images = ", ".join(c.image for c in d.spec.template.spec.containers)
        updated = d.status.updated_replicas or 0
        row = f"- {d.metadata.name}: ready {ready}/{want}, updated {updated}, image {images}"
        bad = [c for c in d.status.conditions or [] if c.status != "True"]
        if bad or ready < want:
            row += (
                " — " + "; ".join(f"{c.type}: {c.message}" for c in bad)
                if bad
                else " — not all replicas ready"
            )
        lines.append(row)
    return "\n".join(lines)


def _unavailable() -> str | None:
    return k8s.config_problem()


TOOLS = [
    ToolSpec(list_pods, "List pods", Category.KUBERNETES, Danger.READ, unavailable=_unavailable),
    ToolSpec(
        describe_pod, "Describe pod", Category.KUBERNETES, Danger.READ, unavailable=_unavailable
    ),
    ToolSpec(get_pod_logs, "Pod logs", Category.KUBERNETES, Danger.READ, unavailable=_unavailable),
    ToolSpec(
        list_events, "Cluster events", Category.KUBERNETES, Danger.READ, unavailable=_unavailable
    ),
    ToolSpec(
        list_deployments,
        "List deployments",
        Category.KUBERNETES,
        Danger.READ,
        unavailable=_unavailable,
    ),
]
