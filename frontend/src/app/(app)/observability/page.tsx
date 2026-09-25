import { Telescope } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "AI observability · K8s Hub" };

// This page is NOT a K8s cluster monitoring dashboard (that belongs to
// Diagnosis / Grafana). It answers: what did the assistant do, what did it
// cost, and what did it change in the cluster.
export default function ObservabilityPage() {
  return (
    <ComingSoon
      icon={Telescope}
      title="AI observability"
      description="What the assistant did, what it cost, and what it changed in the cluster."
      feature={[
        "Traces from Langfuse: question, tools called, results",
        "Tokens, cost and latency over time and per user",
        "Which resources and namespaces were changed — linking traces to the audit log",
        "Approval, rejection and failed dry-run rates",
        "Open a trace directly in Langfuse",
        "Score answer quality against a fixed dataset",
      ]}
    />
  );
}
