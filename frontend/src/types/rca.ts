/**
 * Root-cause analysis (Groot-style event graph). Mirrors backend/app/schemas/rca.py —
 * change both together. The graph/report JSON shapes come from
 * app/modules/rca/{model,pipeline,report,remediation}.py.
 */

export type RcaTrigger = "manual" | "chat" | "alert" | "scan";
export type RcaStatus = "pending" | "running" | "completed" | "failed";
export type ReportStatus = "none" | "running" | "done" | "failed";
export type TargetKind = "Workload" | "Pod" | "Service";
export type EventCategory = "symptom" | "state" | "resource" | "change" | "dependency";
export type Verdict = "confirmed" | "refuted" | "unclear";

export interface RcaStep {
  key: string;
  label: string;
  status: "running" | "done" | "error";
}

export interface RcaEntity {
  kind: string;
  namespace: string | null;
  name: string;
  /** Real workload kind (Deployment…) when kind is "Workload". */
  sub: string;
  key: string;
}

export interface RcaEvidence {
  id: string;
  source: string;
  text: string;
  at: string | null;
}

export interface RcaEvent {
  id: string;
  type: string;
  title: string;
  category: EventCategory;
  entity: RcaEntity;
  start: string;
  end: string | null;
  summary: string;
  severity: "info" | "warning" | "critical";
  attrs: Record<string, unknown>;
  evidence: RcaEvidence[];
  /** Part of the causal graph (reached from a symptom), not only detected. */
  in_graph: boolean;
}

export interface RcaEdge {
  cause: string;
  effect: string;
  rule: string;
  weight: number;
  why: string;
}

export type DependencySource = "config" | "metric" | "trace" | "log" | "annotation";

export interface RcaDependency {
  /** Entity keys: "Workload/langfuse/langfuse-worker" → "Service/database/pg-rw". */
  caller: string;
  callee: string;
  sources: DependencySource[];
}

export interface RcaGraph {
  events: RcaEvent[];
  edges: RcaEdge[];
  seeds: string[];
  /** Namespaces analysed (focus + dependencies); ["*"] = the whole cluster. Older runs lack it. */
  namespaces?: string[];
  dependencies?: RcaDependency[];
}

/** A skill suggested for a cause: its SKILL.md lists one of the chain's event types. */
export interface RcaSkillRef {
  name: string;
  description: string;
}

export interface RcaHypothesis {
  rank: number;
  event_id: string;
  score: number;
  /** Event ids from this cause down to a symptom. */
  chain: string[];
  rules: string[];
  verdict: Verdict | null;
  feedback?: "correct" | "wrong" | null;
  feedback_by_email?: string | null;
  /** Enabled skills for this cause (metadata.rca-events), best first; at most two. */
  skills?: RcaSkillRef[];
}

export interface RcaFix {
  id: string;
  event_id: string;
  action: "set_image" | "scale" | "advice";
  title: string;
  params: Record<string, unknown>;
  proposable: boolean;
}

export interface RcaReport {
  summary?: string;
  explanation?: string;
  root_cause_rank?: number | null;
  /** next_steps per cause since 11/2026; older reports only have the top-level list. */
  verdicts?: { rank: number; status: Verdict; reason: string; evidence_ids: string[]; next_steps?: string[] }[];
  fix?: RcaFix | null;
  fix_candidates?: RcaFix[];
  next_steps?: string[];
  tool_evidence?: { id: string; tool: string; args: Record<string, unknown>; text: string }[];
  validation?: string[];
  tool_calls_used?: number;
  provider?: string | null;
  model?: string | null;
  /** Set instead of the rest when the AI step failed. */
  error?: string;
}

export interface RcaRunSummary {
  id: string;
  trigger: RcaTrigger;
  requested_by_email: string;
  namespace: string;
  target_kind: TargetKind | null;
  target_name: string | null;
  window_start: string;
  window_end: string;
  status: RcaStatus;
  error: string | null;
  report_status: ReportStatus;
  created_at: string;
  finished_at: string | null;
  top_cause: string | null;
  top_cause_type: string | null;
  /** Readable name and category of top_cause_type (backend model.EVENT_TYPES). */
  top_cause_title?: string | null;
  top_cause_category?: EventCategory | null;
}

export interface RcaRun extends RcaRunSummary {
  steps: RcaStep[];
  warnings: string[];
  graph: RcaGraph | null;
  hypotheses: RcaHypothesis[];
  report: RcaReport | null;
  llm_trace_id: string | null;
  approval_id: string | null;
}

export interface RcaRunPage {
  items: RcaRunSummary[];
  total: number;
}

export interface RcaRunCreate {
  /** Empty = the whole cluster. */
  namespace?: string | null;
  target_kind?: TargetKind | null;
  target_name?: string | null;
  lookback_minutes?: number | null;
  with_report?: boolean;
  provider?: string | null;
  model?: string | null;
}

export interface RcaTargets {
  namespaces: string[];
  error: string | null;
}

export interface RcaWeight {
  key: string;
  positive: number;
  negative: number;
  factor: number;
  updated_at: string;
}

export interface WorkloadRef {
  kind: string;
  name: string;
}
