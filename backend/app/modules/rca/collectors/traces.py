"""Collector: request traces (Grafana Tempo). TODO.

Reuse app/integrations/tempo/client.py — do not call Tempo directly:
  - `build_query(service=..., namespaces=..., only_errors=True)` around the
    incident window to find failing/slow requests of the affected workload;
  - `get_trace()` + `summarize_trace()` for the top few, attached as evidence.

Only helps when the workload's apps are instrumented (Beyla/OpenTelemetry).
An empty result must be recorded as "no trace data", not as "no errors".
"""
