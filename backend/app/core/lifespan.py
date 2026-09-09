"""Application startup / shutdown hooks.

TODO: init DB engine, Redis pool, K8s client, Langfuse client, MCP skill registry.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- startup ---
    yield
    # --- shutdown ---
