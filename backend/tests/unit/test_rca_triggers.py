"""RCA phase 5: Alertmanager webhook and the periodic scan, without a cluster or database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.modules.rca import scanner, triggers


def alert(name: str, status: str = "firing", fp: str = "f1", **labels: str) -> dict:
    return {"status": status, "labels": {"alertname": name, **labels}, "fingerprint": fp}


def test_parse_alerts_picks_target_and_skips_what_it_cannot_diagnose():
    payload = {
        "alerts": [
            alert("KubePodCrashLooping", fp="a", namespace="shop", pod="api-7d9f-x"),
            alert("KubeDeploymentReplicasMismatch", fp="b", namespace="shop", deployment="api"),
            alert("Watchdog", fp="c"),  # no namespace
            alert("KubePodCrashLooping", status="resolved", fp="d", namespace="shop", pod="x"),
            alert("Weird", fp="e", namespace="Not_Valid"),
        ]
    }
    targets, skipped = triggers.parse_alerts(payload)
    assert [(t.kind, t.name, t.fingerprint) for t in targets] == [
        ("Pod", "api-7d9f-x", "a"),
        ("Workload", "api", "b"),
    ]
    assert any("Watchdog" in s for s in skipped)
    assert any("Weird" in s for s in skipped)
    assert len(skipped) == 2  # the resolved one is ignored silently


def test_handle_alerts_dedups_by_fingerprint_and_by_target(monkeypatch):
    created: list[dict] = []

    async def create_run(**kw):
        created.append(kw)
        return SimpleNamespace(id=f"run{len(created)}")

    async def recent(fps):
        return {"old"}

    monkeypatch.setattr(triggers.pipeline, "create_run", create_run)
    monkeypatch.setattr(triggers.pipeline, "spawn", lambda coro: coro.close())
    monkeypatch.setattr(triggers, "_recent_fingerprints", recent)

    async def no_subjects():
        return set()

    monkeypatch.setattr(triggers, "_recent_subjects", no_subjects)
    payload = {
        "alerts": [
            alert("A", fp="old", namespace="shop", deployment="api"),  # diagnosed recently
            alert("B", fp="new1", namespace="shop", deployment="web"),
            alert("C", fp="new2", namespace="shop", deployment="web"),  # same target as B
        ]
    }
    out = asyncio.run(triggers.handle_alerts(payload))
    assert out["started"] == ["run1"]
    assert created[0]["trigger"] == "alert" and created[0]["requested_by"] is None
    assert created[0]["target_name"] == "web" and created[0]["alert_fingerprint"] == "new1"
    assert any("already diagnosed" in s for s in out["skipped"])


def test_pod_alerts_count_as_their_workload():
    # Two alerts of one failing rollout: on the pod, then on the Deployment.
    assert triggers.subject("shop", "Pod", "web-7887c7b74c-vc56k") == ("shop", "web")
    assert triggers.subject("shop", "Workload", "web") == ("shop", "web")
    assert triggers.subject("shop", "Pod", "single") == ("shop", "single")


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI

    from app.api.v1 import rca as rca_api

    # Only the RCA router: importing app.main would register the HTTP metrics in
    # the global Prometheus registry and break test_telemetry's own setup.
    app = FastAPI()
    app.include_router(rca_api.router, prefix="/api/v1/rca")

    calls: list[dict] = []

    async def handle(payload):
        calls.append(payload)
        return {"started": [], "skipped": []}

    monkeypatch.setattr(rca_api.triggers, "handle_alerts", handle)
    token = {"value": "s3cret"}
    monkeypatch.setattr(
        rca_api, "get_settings", lambda: SimpleNamespace(ALERTMANAGER_WEBHOOK_TOKEN=token["value"])
    )
    transport = httpx.ASGITransport(app=app)
    return transport, calls, token


def _post(transport, headers):
    async def go():
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.post("/api/v1/rca/alerts", json={"alerts": []}, headers=headers)

    return asyncio.run(go())


def test_webhook_requires_the_token(client):
    transport, calls, token = client
    assert _post(transport, {}).status_code == 401
    assert _post(transport, {"Authorization": "Bearer wrong"}).status_code == 401
    assert _post(transport, {"Authorization": "Bearer s3cret"}).status_code == 200
    assert len(calls) == 1
    token["value"] = ""
    assert _post(transport, {"Authorization": "Bearer "}).status_code == 503


def test_scanner_reports_a_symptom_once_until_it_goes_away(monkeypatch):
    monkeypatch.setattr(scanner, "_seen", {})
    t0 = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    assert scanner.new_symptoms({"CrashLoop:Pod/shop/a"}, t0) == {"CrashLoop:Pod/shop/a"}
    # Still crash-looping on the next scans: not new.
    assert scanner.new_symptoms({"CrashLoop:Pod/shop/a"}, t0 + timedelta(minutes=10)) == set()
    # Gone for longer than FORGET_MINUTES, then back: new again.
    later = t0 + timedelta(minutes=10 + scanner.FORGET_MINUTES + 1)
    assert scanner.new_symptoms(set(), later) == set()
    assert scanner.new_symptoms({"CrashLoop:Pod/shop/a"}, later) == {"CrashLoop:Pod/shop/a"}
