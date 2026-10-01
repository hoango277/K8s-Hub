"""Before/after diff of an object, as the approver reads it.

Both sides are cleaned the same way (resources.clean) and `status` is
dropped: a dry-run returns the object as it WOULD be stored, and status noise
(timestamps, observed generation) would bury the one line that matters.
"""

from __future__ import annotations

import difflib
from typing import Any

import yaml

from app.integrations.k8s.resources import clean

MAX_DIFF_CHARS = 12_000


def _yaml(obj: dict[str, Any] | None) -> list[str]:
    if obj is None:
        return []
    obj = clean(obj)
    obj.pop("status", None)
    (obj.get("metadata") or {}).pop("creationTimestamp", None)
    return yaml.safe_dump(obj, sort_keys=True, allow_unicode=True).splitlines(keepends=True)


def object_diff(before: dict[str, Any] | None, after: dict[str, Any] | None, label: str) -> str:
    """Unified diff; a new object shows as all '+', a deleted one as all '-'."""
    lines = difflib.unified_diff(
        _yaml(before),
        _yaml(after),
        fromfile=f"{label} (now)" if before is not None else "/dev/null",
        tofile=f"{label} (after)" if after is not None else "/dev/null",
        n=3,
    )
    text = "".join(lines)
    if not text:
        return f"--- {label}\n(no change: the object already looks like this)\n"
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS] + "\n… (diff cut)\n"
    return text


__all__ = ["object_diff"]
