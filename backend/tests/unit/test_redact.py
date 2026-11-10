"""Credentials are hidden before cluster data reaches the model (tools/redact.py)."""

from __future__ import annotations

import yaml

from app.modules.tools.redact import PLACEHOLDER, redact_object, redact_text


def test_deployment_env_and_configmap_by_structure() -> None:
    deploy = {
        "kind": "Deployment",
        "spec": {"template": {"spec": {"containers": [{
            "name": "app",
            "env": [
                {"name": "DB_PASSWORD", "value": "SuperSecret123"},
                {"name": "API_KEY", "value": "abc123def"},
                {"name": "DB_HOST", "value": "pg-rw.database.svc"},
                {"name": "CACHE_KEY_PREFIX", "value": "orders"},
                {"name": "DATABASE_URL", "value": "postgres://admin:p4ss@db:5432/orders"},
                {"name": "TOKEN", "valueFrom": {"secretKeyRef": {"name": "s", "key": "token"}}},
            ],
        }]}}},
    }  # fmt: skip
    env = redact_object(deploy)["spec"]["template"]["spec"]["containers"][0]["env"]
    values = {e["name"]: e.get("value") for e in env}
    assert values["DB_PASSWORD"] == PLACEHOLDER
    assert values["API_KEY"] == PLACEHOLDER
    # What a diagnosis needs stays: hosts, harmless names, where a value comes from.
    assert values["DB_HOST"] == "pg-rw.database.svc"
    assert values["CACHE_KEY_PREFIX"] == "orders"
    assert values["DATABASE_URL"] == f"postgres://admin:{PLACEHOLDER}@db:5432/orders"
    assert env[5]["valueFrom"] == {"secretKeyRef": {"name": "s", "key": "token"}}
    assert deploy["spec"]["template"]["spec"]["containers"][0]["env"][0]["value"] == (
        "SuperSecret123"
    )  # the original is not modified

    cm = redact_object(
        {"kind": "ConfigMap", "data": {"smtp_password": "x9y8", "LOG_LEVEL": "info"}}
    )
    assert cm["data"] == {"smtp_password": PLACEHOLDER, "LOG_LEVEL": "info"}


def test_secrets_in_log_lines_by_pattern() -> None:
    log = "\n".join([
        "GET /api 200 Authorization: Bearer abcdefghijklmnop0123",
        "login ok jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlX2hlcmU",
        "connecting to redis://default:hunter2@redis:6379/0",
        "config loaded password=hunter2 user=bob",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
        "aws key AKIAIOSFODNN7EXAMPLE",
        "ERROR payment gateway timeout after 30s (order 8812)",
    ])  # fmt: skip
    out = redact_text(log)
    for secret in ("abcdefghijklmnop0123", "eyJhbGci", "hunter2", "MIIEow", "AKIAIOSFODNN7EXAMPLE"):
        assert secret not in out
    assert "redis://default:[REDACTED]@redis:6379/0" in out
    assert "user=bob" in out
    assert "ERROR payment gateway timeout after 30s (order 8812)" in out  # untouched


def test_yaml_text_is_not_mangled() -> None:
    """The text net also runs over YAML (custom tools): `secretKeyRef:` at the
    end of a line must not swallow the next line as its value."""
    text = yaml.safe_dump({"valueFrom": {"secretKeyRef": {"name": "db", "key": "password"}}})
    assert redact_text(text) == text
