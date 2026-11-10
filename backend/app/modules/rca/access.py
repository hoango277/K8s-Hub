"""Who may see which diagnosis — one rule for every door.

A `user` sees the runs they started and the ones the system started (alerts,
periodic scans); engineers and admins see all. The API, a chat thread opened
from a diagnosis and the assistant's get_diagnosis tool all go through here,
so none of them can show a run another one would hide.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rca import RcaRun

SYSTEM_TRIGGERS = ("alert", "scan")


def visible_to(user: Any):
    """SQL filter on RcaRun. `user` needs `.id` and `.role` (a User or an approval Actor)."""
    from app.api.deps import has_role  # lazy: deps imports half the app

    if has_role(user, ("engineer",)):
        return true()
    return or_(RcaRun.requested_by == user.id, RcaRun.trigger.in_(SYSTEM_TRIGGERS))


async def get_visible(db: AsyncSession, run_id: uuid.UUID, user: Any) -> RcaRun | None:
    """The run, or None when it doesn't exist OR the user may not see it — callers
    answer both the same way, so the answer never reveals that a run exists."""
    return await db.scalar(select(RcaRun).where(RcaRun.id == run_id, visible_to(user)))


__all__ = ["SYSTEM_TRIGGERS", "get_visible", "visible_to"]
