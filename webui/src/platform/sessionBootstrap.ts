import { apiBase, apiFetch, readApiError } from "../api";
import { getAuthToken, withNormalizedPermissions, type AuthUser } from "./auth";
import { normalizeRegionRows, setCachedRegions, type RegionRow } from "./regionCache";

export type SessionBootstrap = {
  user: AuthUser;
  regions: RegionRow[];
};

let bootstrapInflight: Promise<SessionBootstrap> | null = null;

/** 登录后或刷新时一次拉取 user + regions，替代 /auth/me 与 /region/ 双请求。 */
export async function fetchSessionBootstrap(): Promise<SessionBootstrap> {
  if (!getAuthToken()) {
    throw new Error("未登录");
  }
  if (bootstrapInflight) {
    return bootstrapInflight;
  }
  bootstrapInflight = (async () => {
    const res = await apiFetch(`${apiBase()}/api/auth/bootstrap`);
    if (!res.ok) {
      throw new Error(await readApiError(res));
    }
    const raw = (await res.json()) as SessionBootstrap;
    const user = withNormalizedPermissions(raw.user);
    const regions = normalizeRegionRows(raw.regions ?? []);
    localStorage.setItem("SIA_auth_user", JSON.stringify(user));
    setCachedRegions(regions);
    return { user, regions };
  })();
  try {
    return await bootstrapInflight;
  } finally {
    bootstrapInflight = null;
  }
}

export function clearSessionBootstrapInflight(): void {
  bootstrapInflight = null;
}
