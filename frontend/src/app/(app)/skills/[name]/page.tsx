import { Wrench } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "Skill details · K8s Hub" };

export default function SkillDetailPage() {
  return (
    <ComingSoon
      icon={Wrench}
      title="Skill details"
      description="A skill's description, input parameters, risk level and run history."
      feature={[
        "Description and risk level (safe / caution / dangerous)",
        "Trial-run form generated from the input schema",
        "Step-by-step run progress, updated live",
        "Recent run history",
      ]}
    />
  );
}
