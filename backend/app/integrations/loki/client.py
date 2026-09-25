"""Loki HTTP API client - READS logs from the target K8s cluster.

Role: evidence source for RCA (app/modules/rca/collectors/logs.py).
NOT where this app writes its own logs - that lives in app/core/telemetry.py.

TODO: query_range() with LogQL, tail, label discovery.
"""
