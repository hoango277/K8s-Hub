"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type { User, UserCreateByAdmin, UserUpdateByAdmin } from "@/types/auth";

/** Account list — admin only (the backend returns 403 for other roles). */
export function useUsers() {
  return useQuery({
    queryKey: qk.users.all,
    queryFn: () => api.get<User[]>("/users"),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserCreateByAdmin) => api.post<User>("/users", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.users.all }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: UserUpdateByAdmin }) =>
      api.patch<User>(`/users/${id}`, patch),
    // The server returns the updated record — replace just that one row in
    // the cache instead of reloading the whole list, so the table doesn't
    // flicker after every change.
    onSuccess: (updated) => {
      qc.setQueryData<User[]>(qk.users.all, (prev) =>
        prev?.map((u) => (u.id === updated.id ? updated : u)),
      );
      // An admin renaming THEMSELVES: the header reads /auth/me, not this list.
      qc.setQueryData<User>(qk.auth.me, (me) => (me && me.id === updated.id ? updated : me));
    },
  });
}

/** An admin resets someone else's password. All of their sessions are logged out. */
export function useResetPassword() {
  return useMutation({
    mutationFn: ({ id, new_password }: { id: string; new_password: string }) =>
      api.post<null>(`/users/${id}/reset-password`, { new_password }),
  });
}
