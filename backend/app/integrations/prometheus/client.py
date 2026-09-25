"""Prometheus HTTP API client - READS the target K8s cluster.

Role: evidence source for RCA (app/modules/rca/collectors/metrics.py).
NOT for monitoring this app itself - that lives in app/core/telemetry.py.

TODO: query(), query_range(), health check, auth (bearer/basic).
"""
