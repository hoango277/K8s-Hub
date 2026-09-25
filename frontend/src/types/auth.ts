/**
 * Login, registration, user profile.
 *
 * Matches `backend/app/schemas/auth.py`. Change one side, change the other.
 */

export type Role = "admin" | "engineer" | "user";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: User;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

/** An admin creates an account for someone else — role IS chosen, unlike RegisterRequest. */
export interface UserCreateByAdmin {
  email: string;
  password: string;
  display_name: string;
  role: Role;
}

export interface UserUpdateByAdmin {
  role?: Role;
  is_active?: boolean;
  display_name?: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}
