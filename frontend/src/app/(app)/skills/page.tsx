import { Wrench } from "lucide-react";

import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata = { title: "Skills · K8s Hub" };

export default function SkillsPage() {
  return (
    <ComingSoon
      icon={Wrench}
      title="Skills and runbooks"
      description="The library of capabilities the assistant can call — single actions or multi-step runbooks."
      feature={[
        "Built-in skill catalog: look up resources, view logs, run PromQL/LogQL queries",
        "Load more skills from external MCP servers",
        "Multi-step runbooks with retries, rollback and checkpoints",
        "Try a skill with a form generated from its input schema",
        "Engineers and admins add, edit and delete skills",
        "Run history with per-step results",
      ]}
    />
  );
}
