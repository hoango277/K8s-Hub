import { RoleGate } from "@/components/layout/role-gate";
import { SettingsForm } from "@/components/settings/settings-form";

export const metadata = { title: "Settings · K8s Hub" };

export default function SettingsPage() {
  return (
    <RoleGate allow={["admin"]}>
      <SettingsForm />
    </RoleGate>
  );
}
