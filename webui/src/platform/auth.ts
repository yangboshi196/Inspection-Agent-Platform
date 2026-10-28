import { apiBase, apiFetch, clearAuthSession, readApiError } from "../api";
import { clearCachedRegions, normalizeRegionRows, setCachedRegions, type RegionRow } from "./regionCache";

const TOKEN_KEY = "SIA_auth_token";
const USER_KEY = "SIA_auth_user";
const AUTH_COOKIE = "SIA_auth_token";

/** 供 iframe / 流媒体子请求使用（与 localStorage 同步） */
export function syncAuthCookie(token: string | null) {
  if (typeof document === "undefined") return;
  if (!token) {
    document.cookie = `${AUTH_COOKIE}=; path=/; Max-Age=0; SameSite=Lax`;
    return;
  }
  document.cookie = `${AUTH_COOKIE}=${encodeURIComponent(token)}; path=/; SameSite=Lax`;
}

export type AuthUser = {
  user_id: string;
  account: string;
  name: string;
  status: "active" | "disabled";
  permissions: string[];
};

export type LoginResult = {
  token: string;
  user: AuthUser;
  regions?: RegionRow[];
};

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** 拥有看板权限的用户默认可访问「智能助手」（兼容旧会话未含新权限 id） */
export function normalizePortalPermissions(permissions: string[]): string[] {
  const set = new Set(permissions);
  if (set.has("p-dash")) set.add("p-trigger-task");
  return [...set];
}

export function withNormalizedPermissions(user: AuthUser): AuthUser {
  return { ...user, permissions: normalizePortalPermissions(user.permissions ?? []) };
}

export function getAuthUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    return withNormalizedPermissions(JSON.parse(raw) as AuthUser);
  } catch {
    return null;
  }
}

export function isLoggedIn(): boolean {
  return Boolean(getAuthToken() && getAuthUser());
}

export function hasPermission(user: AuthUser | null | undefined, perm: string): boolean {
  return Boolean(user?.permissions?.includes(perm));
}

export function hasAnyPermission(user: AuthUser | null | undefined, perms: string[]): boolean {
  return perms.some((perm) => hasPermission(user, perm));
}

export const USER_PORTAL_PERMISSIONS = ["p-dash", "p-trigger-task", "p-reports", "p-events", "p-inspection-view"] as const;
export const ADMIN_PORTAL_PERMISSIONS = [
  "p-inspection",
  "p-device",
  "p-knowledge",
  "p-algo",
  "p-perm",
  "p-logs",
  "p-docs",
  "p-workflow",
] as const;

export function canAccessUserPortal(user: AuthUser | null | undefined): boolean {
  return hasAnyPermission(user, [...USER_PORTAL_PERMISSIONS]);
}

export function canAccessAdminPortal(user: AuthUser | null | undefined): boolean {
  return hasAnyPermission(user, [...ADMIN_PORTAL_PERMISSIONS]);
}

function persistAuth(result: LoginResult) {
  localStorage.setItem(TOKEN_KEY, result.token);
  localStorage.setItem(USER_KEY, JSON.stringify(withNormalizedPermissions(result.user)));
  syncAuthCookie(result.token);
}

export function clearAuth() {
  clearAuthSession();
  clearCachedRegions();
  syncAuthCookie(null);
}

export async function loginWithApi(account: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${apiBase()}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account: account.trim(), password }),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  const result = (await res.json()) as LoginResult;
  persistAuth(result);
  if (result.regions?.length) {
    setCachedRegions(normalizeRegionRows(result.regions));
  }
  return result;
}

export async function logoutWithApi(): Promise<void> {
  const token = getAuthToken();
  if (token) {
    try {
      await apiFetch(`${apiBase()}/api/auth/logout`, { method: "POST" });
    } catch {
      /* ignore */
    }
  }
  clearAuth();
}

let currentUserInflight: Promise<AuthUser> | null = null;

export async function fetchCurrentUser(): Promise<AuthUser> {
  if (currentUserInflight) {
    return currentUserInflight;
  }
  currentUserInflight = (async () => {
    const res = await apiFetch(`${apiBase()}/api/auth/me`);
    if (!res.ok) {
      throw new Error(await readApiError(res));
    }
    const user = withNormalizedPermissions((await res.json()) as AuthUser);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  })();
  try {
    return await currentUserInflight;
  } finally {
    currentUserInflight = null;
  }
}
