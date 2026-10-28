import { apiBase, apiFetch, readApiError } from "../api";
import { PERMISSIONS, permissionsByModule } from "./admin/permissionMock";

export type AuthUserRow = {
  user_id: string;
  account: string;
  name: string;
  status: "active" | "disabled";
  permissions: string[];
  role_id?: string | null;
  role_name?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type AuthRoleRow = {
  role_id: string;
  name: string;
  description: string;
  permissions: string[];
  created_at?: string;
  updated_at?: string;
};

export type CreateAuthUserInput = {
  account: string;
  name: string;
  password: string;
  status?: "active" | "disabled";
  role_id?: string;
  permissions?: string[];
};

export type PatchAuthUserInput = {
  name?: string;
  status?: "active" | "disabled";
  password?: string;
  permissions?: string[];
  role_id?: string | null;
};

export type CreateAuthRoleInput = {
  role_id?: string;
  name: string;
  description?: string;
  permissions?: string[];
};

export type PatchAuthRoleInput = {
  name?: string;
  description?: string;
  permissions?: string[];
};

export { permissionsByModule };

export async function loadAuthUsers(): Promise<AuthUserRow[]> {
  const res = await apiFetch(`${apiBase()}/api/auth/users/`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: AuthUserRow[] };
  return data.items;
}

export async function createAuthUser(input: CreateAuthUserInput): Promise<AuthUserRow> {
  const res = await apiFetch(`${apiBase()}/api/auth/users/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account: input.account.trim().toLowerCase(),
      name: input.name.trim(),
      password: input.password,
      status: input.status ?? "active",
      permissions: input.permissions ?? [],
      ...(input.role_id ? { role_id: input.role_id } : {}),
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as AuthUserRow;
}

export async function patchAuthUser(userId: string, input: PatchAuthUserInput): Promise<AuthUserRow> {
  const res = await apiFetch(`${apiBase()}/api/auth/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as AuthUserRow;
}

export async function deleteAuthUser(userId: string): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/auth/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readApiError(res));
}

export async function loadAuthRoles(): Promise<AuthRoleRow[]> {
  const res = await apiFetch(`${apiBase()}/api/auth/roles/`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: AuthRoleRow[] };
  return data.items;
}

export async function createAuthRole(input: CreateAuthRoleInput): Promise<AuthRoleRow> {
  const res = await apiFetch(`${apiBase()}/api/auth/roles/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name.trim(),
      description: (input.description ?? "").trim(),
      permissions: input.permissions ?? [],
      ...(input.role_id ? { role_id: input.role_id } : {}),
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as AuthRoleRow;
}

export async function patchAuthRole(roleId: string, input: PatchAuthRoleInput): Promise<AuthRoleRow> {
  const res = await apiFetch(`${apiBase()}/api/auth/roles/${encodeURIComponent(roleId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as AuthRoleRow;
}

export async function deleteAuthRole(roleId: string): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/auth/roles/${encodeURIComponent(roleId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readApiError(res));
}
