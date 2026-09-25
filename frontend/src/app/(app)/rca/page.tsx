import { Stethoscope } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "Diagnosis · K8s Hub" };

export default function RcaPage() {
  return (
    <ComingSoon
      icon={Stethoscope}
      title="Incident diagnosis"
      description="Find the root cause when a workload has problems, by gathering and correlating evidence from many sources."
      feature={[
        "Start a diagnosis for a namespace, a workload, or from an Alertmanager alert",
        "Collect Kubernetes events, pod status, logs from Loki and metrics from Prometheus",
        "Built-in detection of CrashLoopBackOff, OOMKilled, ImagePullBackOff, probe failures, Pending",
        "A timeline correlating events with the latest deploy",
        "Ranked root-cause hypotheses with confidence",
        "Suggested fixes, handed straight to the approval flow",
      ]}
    />
  );
}
