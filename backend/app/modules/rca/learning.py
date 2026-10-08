"""Learn rule weights and event-type priors from feedback — the step Groot postponed.

Engineers mark a ranked cause "right" or "not it" on the diagnosis page; the
evaluation can record its ground truth the same way (`rca_eval --feedback`).
Each judgement counts for:
  - the root cause's event TYPE  (`type:Rollout`)   → its prior;
  - every RULE of its causal chain (`rule:rollout-image-pull`) → its weight.

The factor is a smoothed ratio, not the raw one:

    factor = clamp( 2 · (pos + A) / (pos + neg + 2A), 0.5, 1.5 ),   A = 2

No feedback → 1.0 (the hand-set weights stand). Three "right" → 1.43; three
"not it" → 0.57. The clamp keeps a few clicks from overturning the knowledge
the rules encode — one wrong button press must not hide a whole class of
causes. The AI's own verdicts are NOT used: the AI can be wrong, and learning
from it would just make the ranking agree with the model.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models.rca import RcaHypothesis, RcaWeight
from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)

SMOOTHING = 2.0
MIN_FACTOR, MAX_FACTOR = 0.5, 1.5
CACHE_SECONDS = 60


def factor(positive: int, negative: int) -> float:
    raw = 2 * (positive + SMOOTHING) / (positive + negative + 2 * SMOOTHING)
    return max(MIN_FACTOR, min(MAX_FACTOR, raw))


@dataclass
class Weights:
    """Factors by key; anything without feedback is 1.0."""

    factors: dict[str, float] = field(default_factory=dict)

    def rule(self, rule_id: str) -> float:
        return self.factors.get(f"rule:{rule_id}", 1.0)

    def type(self, event_type: str) -> float:
        return self.factors.get(f"type:{event_type}", 1.0)


NEUTRAL = Weights()
_cache: tuple[float, Weights] | None = None


async def load() -> Weights:
    """Current factors, cached for a minute (every diagnosis asks)."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    try:
        async with get_sessionmaker()() as db:
            rows = (await db.scalars(select(RcaWeight))).all()
    except Exception as exc:  # no database: rank with the hand-set weights
        logger.warning("RCA weights unavailable, using defaults: %s", exc)
        return NEUTRAL
    weights = Weights({r.key: factor(r.positive, r.negative) for r in rows})
    _cache = (time.monotonic(), weights)
    return weights


def keys_for(hypothesis: RcaHypothesis, root_type: str) -> list[str]:
    return [f"type:{root_type}", *(f"rule:{r}" for r in dict.fromkeys(hypothesis.rules or []))]


async def record(run_id: uuid.UUID, rank: int, correct: bool, *, by: str) -> RcaHypothesis | None:
    """Store one judgement and update the counts. Changing your mind moves the
    counts (the previous judgement is taken back first), it never double-counts."""
    global _cache
    verdict = "correct" if correct else "wrong"
    async with get_sessionmaker()() as db:
        hyp = await db.scalar(
            select(RcaHypothesis).where(RcaHypothesis.run_id == run_id, RcaHypothesis.rank == rank)
        )
        if hyp is None:
            return None
        root_type = hyp.event_id.partition(":")[0]
        previous = hyp.feedback
        if previous != verdict:
            for key in keys_for(hyp, root_type):
                row = await db.get(RcaWeight, key) or RcaWeight(key=key, positive=0, negative=0)
                if previous == "correct":
                    row.positive = max(0, row.positive - 1)
                elif previous == "wrong":
                    row.negative = max(0, row.negative - 1)
                if correct:
                    row.positive += 1
                else:
                    row.negative += 1
                db.add(row)
        hyp.feedback, hyp.feedback_by_email, hyp.feedback_at = verdict, by, datetime.now(UTC)
        await db.commit()
        await db.refresh(hyp)
    _cache = None  # the next diagnosis sees it at once
    return hyp


async def table() -> list[dict]:
    """Every learned key with its counts and factor, most-judged first."""
    async with get_sessionmaker()() as db:
        rows = (await db.scalars(select(RcaWeight))).all()
    out = [
        {
            "key": r.key,
            "positive": r.positive,
            "negative": r.negative,
            "factor": round(factor(r.positive, r.negative), 3),
            "updated_at": r.updated_at,
        }
        for r in rows
    ]
    return sorted(out, key=lambda x: -(x["positive"] + x["negative"]))


__all__ = ["NEUTRAL", "Weights", "factor", "keys_for", "load", "record", "table"]
