/**
 * Cluster changes proposed by the assistant — matches backend/app/api/v1/approvals.py.
 * Change one side, change the other.
 */

export type ApprovalStatus = "pending" | "executing" | "executed" | "failed" | "rejected" | "expired";
export type ApprovalDanger = "caution" | "dangerous";

export interface Approval {
  id: string;
  /** scale | restart | set_image | delete_pod | apply | command */
  kind: string;
  title: string;
  namespace: string | null;
  target: string | null;
  danger: ApprovalDanger;
  /** The tool that proposed it. */
  source: string;
  /** Custom-tool changes: the exact argv that will run. */
  command: string[] | null;
  diff: string | null;
  dry_run_output: string | null;
  status: ApprovalStatus;
  /** Why it was rejected. */
  reason: string | null;
  result: string | null;
  verify_ok: boolean | null;
  verify_message: string | null;
  requested_by_email: string;
  decided_by_email: string | null;
  decided_at: string | null;
  executed_at: string | null;
  thread_id: string | null;
  created_at: string;
  expires_at: string;
}

export interface ApprovalPage {
  items: Approval[];
  total: number;
}
