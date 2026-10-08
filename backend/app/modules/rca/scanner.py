"""Periodic scan: diagnose new problems before anyone asks.

Every RCA_SCAN_INTERVAL_MINUTES, each namespace in RCA_SCAN_NAMESPACES is
analysed — or the WHOLE CLUSTER in one analysis when that list is empty
(the deterministic part only, a few seconds). A stored run — with
the AI report — is created only when a CRITICAL symptom shows up that wasn't
there on the previous scans: a crash loop that has lasted for days is
diagnosed once, not every cycle.

"Seen" symptoms live in memory: a symptom is forgotten FORGET_MINUTES after
it was last seen (so a recurring problem is diagnosed again), and a backend
restart forgets everything (the first scan after it diagnoses whatever is
broken, once). Both settings are re-read every cycle, so changing them on the
Settings page needs no restart. One backend process = one scanner; with
several replicas each would scan (there is no leader election yet).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.modules.rca import pipeline
from app.modules.rca.causality import is_symptom
from app.modules.rca.triggers import SCAN_REQUESTER
from app.modules.tools.guard import ToolInputError, check_namespace

logger = logging.getLogger(__name__)

FORGET_MINUTES = 60
IDLE_SECONDS = 60  # how often to re-check the settings while the scan is off

# symptom key ("CrashLoop:Pod/shop/api-1") -> last time a scan saw it
_seen: dict[str, datetime] = {}


def new_symptoms(keys: set[str], now: datetime) -> set[str]:
    """Keys not seen recently; marks all of `keys` as seen now."""
    for k, last in list(_seen.items()):
        if now - last > timedelta(minutes=FORGET_MINUTES):
            del _seen[k]
    fresh = {k for k in keys if k not in _seen}
    for k in keys:
        _seen[k] = now
    return fresh


async def scan_namespace(namespace: str | None) -> str | None:
    """Analyse one namespace (None = the whole cluster); returns the new run id,
    or None if nothing new."""
    analysis = await pipeline.analyze(namespace)
    keys = {e.id for e in analysis.events if is_symptom(e) and e.severity == "critical"}
    fresh = new_symptoms(keys, datetime.now(UTC))
    if not fresh:
        return None
    run = await pipeline.create_run(
        namespace=namespace,
        trigger="scan",
        requested_by=None,
        requested_by_email=SCAN_REQUESTER,
        end=analysis.end,
        lookback_minutes=int((analysis.end - analysis.start).total_seconds() // 60),
    )
    await pipeline.record_analysis(run.id, analysis)
    pipeline.spawn(pipeline.report_job(run.id))
    logger.info(
        "Scan of %s found %d new symptom(s): run %s", namespace or "the cluster", len(fresh), run.id
    )
    return str(run.id)


async def scan_once() -> list[str]:
    started: list[str] = []
    targets: list[str | None] = list(get_settings().RCA_SCAN_NAMESPACES) or [None]
    for namespace in targets:
        try:
            if namespace is not None:
                check_namespace(namespace)
            run_id = await scan_namespace(namespace)
        except ToolInputError as exc:
            logger.warning("Scan skips %s: %s", namespace, exc)
            continue
        except Exception:
            logger.exception("Scan of %s failed", namespace)
            continue
        if run_id:
            started.append(run_id)
    return started


async def loop() -> None:
    """Runs for the life of the backend (started in lifespan)."""
    while True:
        settings = get_settings()
        interval = settings.RCA_SCAN_INTERVAL_MINUTES
        if interval <= 0:
            await asyncio.sleep(IDLE_SECONDS)
            continue
        try:
            await scan_once()
        except Exception:  # never let the loop die
            logger.exception("Periodic scan failed")
        await asyncio.sleep(interval * 60)


__all__ = ["FORGET_MINUTES", "loop", "new_symptoms", "scan_namespace", "scan_once"]
