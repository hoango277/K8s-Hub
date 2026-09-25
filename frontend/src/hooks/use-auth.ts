"use client";

import { useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import {
  clearTokens,
  getRawRefreshToken,
  hasSession,
  saveTokenPair,
  subscribeSession,
} from "@/lib/auth-tokens";
import { qk } from "@/lib/query-keys";
import type { ChangePasswordRequest, LoginRequest, RegisterRequest, TokenPair, User } from "@/types/auth";

/** Whether a stored session exists, RE-READ whenever login/logout happens
 * anywhere in the app (including `api.ts` logging out on its own after a 401).
 *
 * Not `useState` + effect like `use-local-storage.ts`: there, `subscribe` was
 * once left empty so nothing ever called back — exactly the trap
 * `useSyncExternalStore` warns about. Here `subscribeSession` is a REAL
 * subscribe that calls the listener every time `saveTokenPair`/`clearTokens`
 * runs, so this hook is the right tool. The server snapshot returns `false` —
 * reasonable, since the server has no localStorage to know from. */
function useHasSession(): boolean {
  return useSyncExternalStore(subscribeSession, hasSession, () => false);
}

/**
 * The profile of the currently signed-in user.
 *
 * `enabled` is off when the user has clearly never signed in (nothing in
 * localStorage). Without this condition EVERY signed-out page load would fire
 * a request that is sure to get a 401, only to be redirected to /login by
 * `AuthGate` — a wasted round-trip.
 */
export function useCurrentUser() {
  const sessionExists = useHasSession();
  return useQuery({
    queryKey: qk.auth.me,
    queryFn: () => api.get<User>("/auth/me"),
    enabled: sessionExists,
    retry: false,
    staleTime: 60_000,
  });
}

function applySession(qc: ReturnType<typeof useQueryClient>, pair: TokenPair) {
  saveTokenPair(pair);
  qc.setQueryData(qk.auth.me, pair.user);
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: LoginRequest) => api.post<TokenPair>("/auth/login", payload),
    onSuccess: (pair) => applySession(qc, pair),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RegisterRequest) => api.post<TokenPair>("/auth/register", payload),
    onSuccess: (pair) => applySession(qc, pair),
  });
}

/**
 * Change your own password. The backend revokes EVERY session (including this
 * one) and returns a new token pair — save it right away, otherwise the next
 * call would use the just-revoked refresh token and get logged out.
 */
export function useChangePassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ChangePasswordRequest) =>
      api.post<TokenPair>("/auth/change-password", payload),
    onSuccess: (pair) => applySession(qc, pair),
  });
}

/** Change your own display name (any role). */
export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { display_name: string }) => api.patch<User>("/auth/me", payload),
    onSuccess: (updated) => {
      qc.setQueryData(qk.auth.me, updated);
      // The admin user list shows this name too; refresh it if it's cached.
      void qc.invalidateQueries({ queryKey: qk.users.all });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const refresh_token = getRawRefreshToken();
      if (refresh_token) {
        // Fine if the server refuses (session already expired) — we can still
        // log out on the browser side, there's just nothing to revoke.
        await api.post("/auth/logout", { refresh_token }).catch(() => undefined);
      }
    },
    onSettled: () => {
      clearTokens();
      qc.clear(); // the signed-out user's threads, settings... must not leak
      // to the next person who signs in on the same machine.
    },
  });
}

/** `true` when the error means not signed in or the session expired — used to
 * show the right message instead of "unknown error". */
export function isUnauthorizedError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

export { useHasSession };
