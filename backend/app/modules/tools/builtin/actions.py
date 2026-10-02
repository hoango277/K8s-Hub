"""Built-in WRITE tools: they PROPOSE changes, they never make them.

Calling one builds an exact plan (planner.py), dry-runs it on the API server,
and stores it as a pending approval (approval_service.py). The chat shows an
approval card; an engineer approves or rejects; only then does it run. The
model is told plainly that nothing has happened yet.

Structured on purpose, instead of kubectl-ai's "the model writes a kubectl
command": each tool takes discrete, validated fields, so the plan can be
checked (namespace allowed? object exists? HPA in the way?) and diffed before
anyone is asked. Free-form commands exist too — as custom tools — and go
through the same approval flow.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.core.config import get_settings
from app.integrations.k8s import client as k8s
from app.modules.nl_command import planner
from app.modules.nl_command.injection import claim_provenance
from app.modules.nl_command.planner import ActionPlan
from app.modules.tools.guard import ToolInputError
from app.modules.tools.schema import Category, Danger, ToolSpec

logger = logging.getLogger(__name__)

APPROVAL_EVENT = "approval_required"


def _thread_id(config: RunnableConfig | None) -> uuid.UUID | None:
    raw = ((config or {}).get("metadata") or {}).get("thread_id")
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


async def propose(
    build: Callable[[], Awaitable[ActionPlan]], *, source: str, config: RunnableConfig | None
) -> str:
    """Build → dry-run → store as pending; tell the chat UI; tell the model."""
    from app.services import approval_service as svc

    # What the user asked in this turn, and any tool output of the turn that
    # looked like planted instructions — shown on the approval card so the
    # approver can tell a requested change from an injected one.
    provenance = claim_provenance()
    question = ((config or {}).get("metadata") or {}).get("question")
    request_text = question or (provenance.request if provenance else None)
    try:
        plan = await build()
        row = await svc.propose(
            plan,
            actor=svc.actor_from_config(config),
            source=source,
            thread_id=_thread_id(config),
            request_text=request_text,
            risk_flags=provenance.flags if provenance else None,
        )
    except (ToolInputError, k8s.K8sError, svc.ApprovalError) as exc:
        return f"Not proposed: {exc}"

    try:
        # Picked up by the streaming layer (on_custom_event) and sent to the
        # browser as an approval_required event carrying this approval's id.
        await adispatch_custom_event(
            APPROVAL_EVENT, {**svc.event_payload(row), "tool": source}, config=config
        )
    except RuntimeError:
        # Run outside a graph (the Tools tab): no stream to tell, nothing lost —
        # the approval is stored and listed on the Approvals page.
        pass
    return svc.message_for_model(row)


@tool(parse_docstring=True)
async def scale_workload(
    kind: Literal["deployment", "statefulset"],
    namespace: str,
    name: str,
    replicas: int,
    config: RunnableConfig,
) -> str:
    """PROPOSE changing the replica count of a deployment or statefulset.

    Nothing changes until an engineer approves it. Check the current state
    first (list_deployments / get_resources) so the proposal makes sense.

    Args:
        kind: deployment or statefulset.
        namespace: the workload's namespace.
        name: the workload's name.
        replicas: the new replica count (0–50; 0 stops every pod).
    """
    return await propose(
        lambda: planner.plan_scale(kind, namespace, name, replicas),
        source="scale_workload",
        config=config,
    )


@tool(parse_docstring=True)
async def restart_workload(
    kind: Literal["deployment", "statefulset", "daemonset"],
    namespace: str,
    name: str,
    config: RunnableConfig,
) -> str:
    """PROPOSE a rolling restart (like `kubectl rollout restart`).

    Pods are replaced one by one. Nothing changes until an engineer approves.

    Args:
        kind: deployment, statefulset or daemonset.
        namespace: the workload's namespace.
        name: the workload's name.
    """
    return await propose(
        lambda: planner.plan_restart(kind, namespace, name),
        source="restart_workload",
        config=config,
    )


@tool(parse_docstring=True)
async def set_image(
    kind: Literal["deployment", "statefulset", "daemonset"],
    namespace: str,
    name: str,
    container: str,
    image: str,
    config: RunnableConfig,
) -> str:
    """PROPOSE changing one container's image, e.g. to roll back to a previous tag.

    Nothing changes until an engineer approves. Look up the current image and
    container name first (describe_resource or get_resources).

    Args:
        kind: deployment, statefulset or daemonset.
        namespace: the workload's namespace.
        name: the workload's name.
        container: the container to change.
        image: the full new image reference, e.g. "ghcr.io/acme/api:1.4.2".
    """
    return await propose(
        lambda: planner.plan_set_image(kind, namespace, name, container, image),
        source="set_image",
        config=config,
    )


@tool(parse_docstring=True)
async def delete_pod(namespace: str, name: str, config: RunnableConfig) -> str:
    """PROPOSE deleting one pod, e.g. to force a stuck pod to be recreated.

    A pod owned by a deployment/statefulset/daemonset is recreated
    automatically; a bare pod is gone for good. Nothing changes until an
    engineer approves.

    Args:
        namespace: the pod's namespace.
        name: the exact pod name.
    """
    return await propose(
        lambda: planner.plan_delete_pod(namespace, name), source="delete_pod", config=config
    )


@tool(parse_docstring=True)
async def delete_resource(kind: str, name: str, config: RunnableConfig, namespace: str = "") -> str:
    """PROPOSE deleting ONE object of any kind: a deployment, service, configmap, namespace…

    One object per call — never delete many things at once; if the user asks
    for a bulk deletion ("delete everything"), ask them to name what to delete.
    Deleting a namespace deletes everything inside it. Nothing changes until an
    engineer approves.

    Args:
        kind: resource kind, plural or short name, e.g. deployment, svc, configmap, namespace.
        name: the exact object name.
        namespace: the object's namespace (empty for cluster-wide kinds such as namespace).
    """
    return await propose(
        lambda: planner.plan_delete(kind, namespace, name), source="delete_resource", config=config
    )


@tool(parse_docstring=True)
async def apply_manifest(manifest: str, config: RunnableConfig) -> str:
    """PROPOSE creating or updating objects from a YAML manifest (server-side apply).

    Up to 10 objects, separated by '---'. Every object needs apiVersion, kind,
    metadata.name (and metadata.namespace, else "default"). Secrets are
    refused. BEFORE calling: gather the specifics from the user and the
    cluster (namespace, image and tag, resources, how to expose it) and show
    a summary — never invent defaults. Nothing changes until an engineer
    approves. It can NOT delete anything: use delete_resource for that.

    Args:
        manifest: the YAML manifest.
    """
    return await propose(
        lambda: planner.plan_apply(manifest), source="apply_manifest", config=config
    )


def _unavailable() -> str | None:
    if get_settings().K8S_EXECUTION_MODE == "read_only":
        return "K8S_EXECUTION_MODE is read_only: changes can't even be proposed."
    return k8s.config_problem()


TOOLS = [
    ToolSpec(
        scale_workload, "Scale workload", Category.KUBERNETES, Danger.WRITE,
        unavailable=_unavailable,
    ),
    ToolSpec(
        restart_workload, "Restart workload", Category.KUBERNETES, Danger.WRITE,
        unavailable=_unavailable,
    ),
    ToolSpec(set_image, "Set image", Category.KUBERNETES, Danger.WRITE, unavailable=_unavailable),
    ToolSpec(
        delete_pod, "Delete pod", Category.KUBERNETES, Danger.DESTRUCTIVE,
        unavailable=_unavailable,
    ),
    ToolSpec(
        delete_resource, "Delete resource", Category.KUBERNETES, Danger.DESTRUCTIVE,
        unavailable=_unavailable,
    ),
    ToolSpec(
        apply_manifest, "Apply manifest", Category.KUBERNETES, Danger.WRITE,
        unavailable=_unavailable,
    ),
]  # fmt: skip

__all__ = ["APPROVAL_EVENT", "TOOLS", "propose"]
