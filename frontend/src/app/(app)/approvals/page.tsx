import { ClipboardCheck } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "Approvals · K8s Hub" };

export default function ApprovalsPage() {
  return (
    <ComingSoon
      icon={ClipboardCheck}
      title="Approvals"
      description="The queue of cluster changes proposed by the assistant that need human review before they run."
      feature={[
        "Pending actions, sorted by risk level",
        "Manifest diff before and after the change",
        "Server-side dry-run results",
        "Approve or reject with a reason",
        "Post-change verification: rollout, pod readiness",
        "Audit log of who approved what, and when",
      ]}
    />
  );
}
