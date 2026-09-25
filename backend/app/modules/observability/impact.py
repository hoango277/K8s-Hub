"""Join Langfuse trace <-> audit log: what the LLM actually DID to the cluster.

Langfuse only knows what the LLM intended to do. This file answers:
  - which actions were actually executed (not rejected/blocked)
  - which resources / namespaces were touched  (blast radius)
  - who approved, and when
  - whether a rollback was needed afterwards

TODO: impact_of_trace(trace_id), blast_radius(thread_id),
      timeline_of_changes(namespace, since).
"""
