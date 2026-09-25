"""AI operations rates Langfuse can't compute: approval, rejection, failed dry-run.

These come from the approval flow and the audit log, which live in Postgres.
Token, cost and latency figures are NOT computed here — they are in Langfuse.
TODO.
"""
