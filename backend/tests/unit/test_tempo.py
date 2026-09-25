"""Tests for the Tempo client and the trace tools. No network."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.integrations.tempo import client as tempo
from app.modules.nl_command import tools

# --------------------------------------------------------------------------
# TraceQL is assembled from checked fields, never from raw model text
# --------------------------------------------------------------------------


def test_query_from_fields():
    q = tempo.build_query(
        service="checkout", namespaces=["shop"], only_errors=True, min_duration_ms=500
    )
    assert q == (
        '{ resource.service.name = "checkout" && resource.k8s.namespace.name = "shop" '
        "&& status = error && duration > 500ms }"
    )


def test_several_namespaces_become_an_alternation():
    q = tempo.build_query(namespaces=["shop", "payments"])
    assert q == '{ resource.k8s.namespace.name =~ "shop|payments" }'


def test_empty_query_matches_everything():
    assert tempo.build_query() == "{ }"


@pytest.mark.parametrize(
    "service",
    ['x" || true || "', "a b", "svc}", 'checkout" && status = ok'],
)
def test_injection_in_service_is_rejected(service):
    with pytest.raises(ValueError):
        tempo.build_query(service=service)


@pytest.mark.parametrize("namespace", ["Shop", "a.b", "a|b", "-bad", 'x"'])
def test_invalid_namespace_is_rejected(namespace):
    with pytest.raises(ValueError):
        tempo.build_query(namespaces=[namespace])


# --------------------------------------------------------------------------
# Summarising a trace
# --------------------------------------------------------------------------

MS = 1_000_000


def _span(span_id, parent, name, start_ms, end_ms, *, error=None, kind="SPAN_KIND_SERVER"):
    s = {
        "spanId": span_id,
        "parentSpanId": parent,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start_ms * MS),
        "endTimeUnixNano": str(end_ms * MS),
    }
    if error:
        s["status"] = {"code": "STATUS_CODE_ERROR", "message": error}
    return s


def _batch(service, namespace, spans):
    return {
        "resource": {
            "attributes": [
                {"key": "service.name", "value": {"stringValue": service}},
                {"key": "k8s.namespace.name", "value": {"stringValue": namespace}},
            ]
        },
        "scopeSpans": [{"spans": spans}],
    }


# frontend (0-1000) -> checkout (50-950) -> payment (100-900, FAILED) -> db (120-880)
#                   -> checkout also calls cart (60-90)
TRACE = {
    "trace": {
        "resourceSpans": [
            _batch("frontend", "shop", [_span("a", "", "GET /checkout", 0, 1000, error="HTTP 500")]),
            _batch(
                "checkout",
                "shop",
                [
                    _span("b", "a", "POST /pay", 50, 950, error="upstream failed"),
                    _span("c", "b", "GET /cart", 60, 90),
                ],
            ),
            _batch(
                "payment",
                "payments",
                [
                    _span("d", "b", "charge", 100, 900, error="timeout calling db"),
                    _span("e", "d", "SELECT balance", 120, 880, kind="SPAN_KIND_CLIENT"),
                ],
            ),
        ]
    }
}


def test_summary_names_the_slow_path_and_the_innermost_error():
    spans = tempo.parse_spans(TRACE)
    text = tempo.summarize_trace("abc", spans)

    assert "1000.0 ms total, 5 spans across 3 services" in text
    assert "3 span(s) FAILED" in text
    # Slowest path follows the child that ends last, down to the DB call.
    path = text.split("Slowest path")[1].split("Failed spans")[0]
    assert path.index("frontend") < path.index("checkout") < path.index("payment")
    assert "SELECT balance" in path
    # The deepest failure is listed first — it is usually the cause.
    failed = text.split("Failed spans:")[1].splitlines()[1]
    assert "payment: charge — timeout calling db" in failed
    # The DB call is where the time actually went.
    per_service = text.split("Time spent per service")[1]
    assert per_service.splitlines()[1].strip().startswith("- payment")


def test_exception_event_becomes_the_error_message():
    span = _span("x", "", "work", 0, 10)
    span["status"] = {"code": 2}
    span["events"] = [
        {
            "name": "exception",
            "attributes": [
                {"key": "exception.type", "value": {"stringValue": "ValueError"}},
                {"key": "exception.message", "value": {"stringValue": "bad input"}},
            ],
        }
    ]
    [s] = tempo.parse_spans({"batches": [_batch("svc", "ns", [span])]})
    assert s.error and s.error_message == "ValueError bad input"


# --------------------------------------------------------------------------
# The tools respect K8S_ALLOWED_NAMESPACES
# --------------------------------------------------------------------------


@pytest.fixture
def allowed_shop(monkeypatch):
    monkeypatch.setattr(
        tools, "get_settings", lambda: Settings(_env_file=None, K8S_ALLOWED_NAMESPACES=["shop"])
    )


async def test_get_trace_hides_spans_outside_allowed_namespaces(monkeypatch, allowed_shop):
    async def fake_get_trace(_id):
        return tempo.parse_spans(TRACE)

    monkeypatch.setattr(tempo, "get_trace", fake_get_trace)
    text = await tools.get_trace.ainvoke({"trace_id": "abc"})
    assert "payment" not in text.split("(")[0]  # payments namespace left out
    assert "2 span(s) outside the allowed namespaces were left out" in text


async def test_search_refuses_a_namespace_that_is_not_allowed(allowed_shop):
    text = await tools.search_traces.ainvoke({"namespace": "kube-system"})
    assert "not in the allowed list" in text


async def test_search_is_limited_to_allowed_namespaces(monkeypatch, allowed_shop):
    seen = {}

    async def fake_search(query, **_):
        seen["query"] = query
        return []

    monkeypatch.setattr(tempo, "search_traces", fake_search)
    await tools.search_traces.ainvoke({})
    assert 'resource.k8s.namespace.name = "shop"' in seen["query"]
