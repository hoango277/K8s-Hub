import { RoleGate } from "@/components/layout/role-gate";
import { UserAdmin } from "@/components/users/user-admin";

export const metadata = { title: "Users · K8s Hub" };

export default function UsersPage() {
  return (
    <RoleGate allow={["admin"]}>
      <UserAdmin />
    </RoleGate>
  );
}
