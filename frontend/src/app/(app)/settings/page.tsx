import { RoleGate } from "@/components/layout/role-gate";
import { SettingsPage as SettingsView } from "@/components/settings/settings-page";

export const metadata = { title: "Settings · K8s Hub" };

export default function SettingsPage() {
  return (
    <RoleGate allow={["admin"]}>
      <SettingsView />
    </RoleGate>
  );
}
