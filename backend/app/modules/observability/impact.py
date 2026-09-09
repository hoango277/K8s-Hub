"""Join Langfuse trace <-> audit log: LLM da TAC DONG gi len cluster.

Langfuse chi biet LLM dinh lam gi. File nay tra loi:
  - action nao that su duoc thuc thi (khong bi reject/chan)
  - resource / namespace nao bi cham vao  (blast radius)
  - ai duyet, duyet luc nao
  - co phai rollback sau do khong

TODO: impact_of_trace(trace_id), blast_radius(thread_id),
      timeline_of_changes(namespace, since).
"""
