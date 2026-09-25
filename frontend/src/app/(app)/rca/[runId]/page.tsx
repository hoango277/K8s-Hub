import { Stethoscope } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "Diagnosis details · K8s Hub" };

export default function RcaDetailPage() {
  return (
    <ComingSoon
      icon={Stethoscope}
      title="Diagnosis run details"
      description="The full report of one diagnosis run: evidence, timeline and hypotheses."
      feature={[
        "Live analysis progress",
        "Evidence grouped by source: events, logs, metrics, rollout history",
        "Timeline of events around when the incident happened",
        "Ranked hypotheses, with reasoning",
        "Suggested fixes and a link to the Langfuse trace",
        "Export the report to share with your team",
      ]}
    />
  );
}
