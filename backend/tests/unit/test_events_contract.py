"""Tests for the event contract: backend and frontend must match.

This test catches someone changing `app/schemas/events.py` and forgetting to
change `frontend/src/types/events.ts` (or vice versa).

Run: pytest tests/unit/test_events_contract.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.schemas import events as ev

TS_FILE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "types" / "events.ts"

# Fields that exist only on the backend and needn't appear on the frontend.
BACKEND_ONLY_FIELDS: dict[str, set[str]] = {}


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _parse_ts_interfaces(src: str) -> dict[str, set[str]]:
    """Return {interface name: {field names}} from the .ts file."""
    src = _strip_comments(src)
    out: dict[str, set[str]] = {}
    for m in re.finditer(
        r"export\s+interface\s+(\w+)(?:\s+extends\s+[\w,\s]+)?\s*\{(.*?)\n\}",
        src,
        flags=re.S,
    ):
        name, body = m.group(1), m.group(2)
        out[name] = set(re.findall(r"^\s*(\w+)\??\s*:", body, flags=re.M))
    return out


def _parse_ts_union(src: str) -> set[str]:
    """Return the set of values in the AGENT_EVENT_TYPES array."""
    src = _strip_comments(src)
    m = re.search(r"AGENT_EVENT_TYPES\s*=\s*\[(.*?)\]", src, flags=re.S)
    assert m, "AGENT_EVENT_TYPES not found in events.ts"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _event_models() -> dict[str, type[BaseModel]]:
    """Every backend event model, keyed by its `type` value."""
    out: dict[str, type[BaseModel]] = {}
    for name in ev.__all__:
        obj = getattr(ev, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, ev.BaseEvent)
            and obj is not ev.BaseEvent
        ):
            out[obj.model_fields["type"].default] = obj
    return out


@pytest.fixture(scope="module")
def ts_src() -> str:
    assert TS_FILE.exists(), f"{TS_FILE} not found"
    return TS_FILE.read_text(encoding="utf-8")


def test_frontend_file_exists(ts_src: str) -> None:
    assert "AgentEvent" in ts_src


def test_same_set_of_event_types(ts_src: str) -> None:
    """Backend and frontend must declare exactly the same set of `type` values."""
    backend_types = set(_event_models())
    ts_types = _parse_ts_union(ts_src)

    assert backend_types == ts_types, (
        f"Event type sets differ.\n"
        f"  Backend only : {sorted(backend_types - ts_types)}\n"
        f"  Frontend only: {sorted(ts_types - backend_types)}"
    )


def test_same_field_names(ts_src: str) -> None:
    """Each event type must have the same field list on both sides."""
    ts_ifaces = _parse_ts_interfaces(ts_src)
    base_fields = ts_ifaces.get("BaseEvent", set())

    errors: list[str] = []
    for type_value, model in sorted(_event_models().items()):
        iface = model.__name__
        if iface not in ts_ifaces:
            errors.append(f"  {type_value}: frontend is missing interface {iface}")
            continue

        py_fields = set(model.model_fields) - BACKEND_ONLY_FIELDS.get(type_value, set())
        ts_fields = ts_ifaces[iface] | base_fields

        if py_fields != ts_fields:
            errors.append(
                f"  {type_value} ({iface}):\n"
                f"      backend only : {sorted(py_fields - ts_fields)}\n"
                f"      frontend only: {sorted(ts_fields - py_fields)}"
            )

    assert not errors, "Field names differ between the two files:\n" + "\n".join(errors)


def test_auxiliary_models_match(ts_src: str) -> None:
    """Non-event models (PlanStep) must match too."""
    ts_ifaces = _parse_ts_interfaces(ts_src)
    assert set(ev.PlanStep.model_fields) == ts_ifaces.get("PlanStep", set())


def test_seq_numbered_from_1() -> None:
    stream = ev.EventStream()
    frames = [stream.emit(ev.TokenEvent(content=str(i))) for i in range(3)]
    assert [f["id"] for f in frames] == ["1", "2", "3"]


def test_sse_event_name_matches_type() -> None:
    frame = ev.to_sse(ev.DoneEvent(trace_id="x"))
    assert frame["event"] == "done"


def test_none_fields_are_not_sent() -> None:
    """exclude_none so the frontend receives optional fields correctly."""
    frame = ev.to_sse(ev.DoneEvent())
    assert "trace_id" not in frame["data"]


def test_rejects_unknown_type() -> None:
    with pytest.raises(Exception):
        ev.AgentEventAdapter.validate_python({"type": "does_not_exist", "seq": 1})


def test_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        ev.TokenEvent(content="x", unknown_field=1)
