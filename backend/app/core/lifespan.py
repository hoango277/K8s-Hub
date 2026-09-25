"""Work that runs when the application starts up and shuts down.

TODO: initialize Redis, the K8s client, the MCP skill catalog.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings, load_persisted_overrides
from app.db.session import check_connection, dispose_engine, get_sessionmaker
from app.modules.observability.langfuse_client import (
    check_langfuse,
    init_langfuse,
    shutdown_langfuse,
)
from app.services.settings_service import load_overrides
from app.services.user_service import bootstrap_admin

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- startup ---
    config = get_settings()
    logger.info("Starting %s (environment: %s)", config.APP_NAME, config.APP_ENV)

    db = await check_connection()
    if db["ok"]:
        logger.info("Connected to the database: PostgreSQL %s", db["server_version"])
    else:
        # Don't stop the app: let it come up and report the error through the
        # health endpoint, to avoid editing .env and restarting over and over
        # during development.
        logger.error("Could NOT connect to the database: %s", db["error"])

    # Make sure there is at least one admin — only created when the database
    # has NO admin yet and .env is filled in. Skipped entirely if it is NOT
    # filled in, so a forgotten config never accidentally creates an admin
    # account with an empty password.
    if db["ok"] and config.ADMIN_BOOTSTRAP_EMAIL and config.ADMIN_BOOTSTRAP_PASSWORD:
        async with get_sessionmaker()() as session:
            try:
                admin = await bootstrap_admin(
                    session,
                    email=config.ADMIN_BOOTSTRAP_EMAIL,
                    password=config.ADMIN_BOOTSTRAP_PASSWORD,
                )
                await session.commit()
                if admin is not None:
                    logger.info("Bootstrapped admin account: %s", admin.email)
            except Exception:
                await session.rollback()
                logger.exception("Could not bootstrap the admin account")

    # Restore what admins changed on the Settings page in earlier runs. Before
    # Langfuse/LLM setup, although today none of the persisted fields affect them.
    if db["ok"]:
        async with get_sessionmaker()() as session:
            try:
                saved = await load_overrides(session)
                applied = load_persisted_overrides(saved)
                if saved and not applied:
                    logger.warning(
                        "Saved settings are invalid together; running on .env values only"
                    )
                elif applied:
                    logger.info("Restored saved settings: %s", ", ".join(sorted(applied)))
            except Exception:
                logger.exception("Could not load saved settings; running on .env values only")

    # Build the client and TracerProvider. No network calls at this step.
    init_langfuse()

    # Connection check is separate: if it fails we only warn, the app keeps running.
    lf = await check_langfuse()
    if lf.get("enabled") and not lf.get("ok"):
        logger.warning(
            "Langfuse is enabled but authentication failed: %s. "
            "Check the keys, and check that the server is version 3 or later — "
            "the current SDK sends data over OTLP, which version 2 doesn't have.",
            lf.get("error") or "server rejected the request",
        )

    yield

    # --- shutdown ---
    # Flush traces still in the queue BEFORE closing everything, otherwise the
    # last turns will never reach Langfuse.
    shutdown_langfuse()
    await dispose_engine()
    logger.info("All connections closed")
