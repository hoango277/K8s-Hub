import { Telescope } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "AI observability · K8s Hub" };

// This page is NOT a K8s cluster monitoring dashboard (that belongs to
// Diagnosis / Grafana). Traces, tokens and cost are NOT rebuilt here — the
// Langfuse UI already shows them, and each chat answer links to its trace.
// This page covers what Langfuse can't know: changes made to the cluster and
// how operators respond to the assistant's plans.
export default function ObservabilityPage() {
  return (
    <ComingSoon
      icon={Telescope}
      title="AI observability"
      description="What the assistant changed in the cluster, and how its plans are reviewed. Traces, tokens and cost are in Langfuse."
      feature={[
        "Which resources and namespaces were changed — linking traces to the audit log",
        "Approval, rejection and failed dry-run rates",
        "Score answer quality against a fixed dataset",
      ]}
    />
  );
}
