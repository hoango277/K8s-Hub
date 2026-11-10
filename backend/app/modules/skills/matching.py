"""Which skills to suggest for a root cause found by RCA.

A skill declares the event types it helps with in its SKILL.md front matter
(`metadata.rca-events`, parser.rca_events). A cause gets the enabled skills
matching any event of its chain, root first — a rollout that ends in a
crash-loop still points to the crash-loop runbook — so the suggestion is a
lookup anyone can read, not a guess by the model.

Computed when a run is read, not stored with it: a skill tagged (or switched
off) later shows up (or disappears) on old diagnoses too.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.skills.parser import Skill, rca_events
from app.modules.skills.store import store

MAX_SUGGESTIONS = 2


def event_type(event_id: str) -> str:
    """'RestartSpike:Pod/langfuse/x' → 'RestartSpike' (model.Event ids)."""
    return event_id.partition(":")[0]


def skills_for(chain: Iterable[str], *, skills: list[Skill] | None = None) -> list[Skill]:
    """Enabled skills for a cause's chain of event ids, best first, at most two."""
    pool = store.enabled() if skills is None else skills
    tagged = [(s, set(rca_events(s.frontmatter))) for s in pool]
    found: dict[str, Skill] = {}
    for eid in chain:
        etype = event_type(eid)
        for skill, types in tagged:
            if etype in types and skill.name not in found:
                found[skill.name] = skill
                if len(found) == MAX_SUGGESTIONS:
                    return list(found.values())
    return list(found.values())


__all__ = ["MAX_SUGGESTIONS", "event_type", "skills_for"]
