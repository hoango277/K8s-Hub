"""Append-only audit log for every mutation applied to the cluster.

This is the SECOND HALF of observability: Langfuse records "what the LLM
thought", this table records "what actually changed in the cluster". The two
are joined by trace_id.

Each record: actor, thread_id, trace_id, action, cluster, namespace,
resource_ref, diff, approved_by, result, timestamp.

TODO: write(), disallow update/delete, query by trace_id / resource.
"""
