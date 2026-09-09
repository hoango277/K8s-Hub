"""Audit log append-only cho moi mutation len cluster.

La VE THU HAI cua observability: Langfuse ghi "LLM nghi gi",
bang nay ghi "cluster that su doi gi". Noi nhau bang trace_id.

Moi ban ghi: actor, thread_id, trace_id, action, cluster, namespace,
resource_ref, diff, approved_by, result, timestamp.

TODO: write(), khong cho update/delete, query theo trace_id / resource.
"""
