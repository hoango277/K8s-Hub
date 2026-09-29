"""MCP client: list and call the tools of an external MCP server (Streamable HTTP).

A connection per call, not a long-lived session: tool calls are rare, and a
held session would break silently whenever the remote server restarts or a
proxy drops idle connections. Opening one costs a single extra round trip.

Nothing an MCP server says about itself is trusted for safety decisions: its
`readOnlyHint` is shown to the engineer as a hint only. Every external tool
starts DISABLED and marked WRITE until someone reviews it (see registry.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TIMEOUT = 20.0
MAX_OUTPUT = 8000


class McpError(RuntimeError):
    """The server is unreachable, refused, or the tool failed. Message is user-facing."""


@dataclass
class RemoteTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only_hint: bool | None


def _client(url: str, token: str | None):
    from mcp import Client
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    if not token:
        return Client(url, read_timeout_seconds=TIMEOUT)
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    return Client(streamable_http_client(url, http_client=http), read_timeout_seconds=TIMEOUT)


def _unwrap(exc: BaseException) -> BaseException:
    """anyio task groups wrap the real error in (nested) ExceptionGroups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


async def list_tools(
    url: str, token: str | None = None, *, _server: Any = None
) -> list[RemoteTool]:
    """`_server` lets tests pass an in-process MCPServer instead of a URL."""
    from mcp import Client

    try:
        async with Client(_server) if _server is not None else _client(url, token) as client:
            result = await client.list_tools()
    except BaseException as exc:  # noqa: BLE001 - ExceptionGroup from anyio
        real = _unwrap(exc)
        if isinstance(real, (KeyboardInterrupt, SystemExit)):
            raise
        raise McpError(f"Could not list tools from {url}: {type(real).__name__}: {real}") from real
    return [
        RemoteTool(
            name=t.name,
            description=(t.description or "").strip(),
            input_schema=dict(t.input_schema or {"type": "object", "properties": {}}),
            read_only_hint=getattr(t.annotations, "read_only_hint", None)
            if t.annotations
            else None,
        )
        for t in result.tools
    ]


def _text_of(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else f"[{getattr(item, 'type', 'content')}]")
    if not parts and getattr(result, "structured_content", None) is not None:
        parts.append(str(result.structured_content))
    out = "\n".join(parts).strip() or "(the tool returned no content)"
    return out if len(out) <= MAX_OUTPUT else out[:MAX_OUTPUT] + "\n… (output cut)"


async def call_tool(
    url: str, name: str, args: dict[str, Any], token: str | None = None, *, _server: Any = None
) -> str:
    from mcp import Client

    try:
        async with Client(_server) if _server is not None else _client(url, token) as client:
            result = await client.call_tool(name, args)
    except BaseException as exc:  # noqa: BLE001
        real = _unwrap(exc)
        if isinstance(real, (KeyboardInterrupt, SystemExit)):
            raise
        raise McpError(f"Calling {name} on {url} failed: {type(real).__name__}: {real}") from real
    text = _text_of(result)
    if getattr(result, "is_error", False):
        raise McpError(f"The tool {name} reported an error: {text}")
    return text


__all__ = ["McpError", "RemoteTool", "call_tool", "list_tools"]
