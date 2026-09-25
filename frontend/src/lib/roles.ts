/**
 * Display info for the three roles — shared by the header, sidebar and user
 * admin page, so one role never carries two different names in two places.
 *
 * REAL permissions live in the backend (`require_role` in app/api/deps.py).
 * This file only decides what to show; hiding a button here does not replace
 * blocking it there.
 */

import type { Role } from "@/types/auth";

export interface RoleInfo {
  label: string;
  description: string;
  tone: "violet" | "info" | "neutral";
}

export const ROLES: Record<Role, RoleInfo> = {
  admin: {
    label: "Admin",
    description: "Full access: everything an Engineer can do, plus system settings and accounts",
    tone: "violet",
  },
  engineer: {
    label: "Engineer",
    description: "Add, edit and delete skills and runbooks",
    tone: "info",
  },
  user: {
    label: "User",
    description: "Ask questions and run existing skills",
    tone: "neutral",
  },
};

export const ROLE_ORDER: Role[] = ["admin", "engineer", "user"];

/**
 * Whether `role` may see something reserved for `allowed`. Admin ALWAYS
 * passes — mirrors `has_role` in backend/app/api/deps.py, so a page marked
 * `["engineer"]` never hides itself from the admin.
 */
export function hasRole(role: Role, allowed: readonly Role[]): boolean {
  return role === "admin" || allowed.includes(role);
}

/** Two initials for the avatar: "Ada Byron Lovelace" -> "AL". */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
