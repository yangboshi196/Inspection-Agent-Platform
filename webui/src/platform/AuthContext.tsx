import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  clearAuth,
  getAuthToken,
  getAuthUser,
  hasPermission,
  loginWithApi,
  logoutWithApi,
  syncAuthCookie,
  type AuthUser,
} from "./auth";
import { getCachedRegions } from "./regionCache";
import { fetchSessionBootstrap } from "./sessionBootstrap";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: (account: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  hasPermission: (perm: string) => boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => getAuthUser());
  const [loading, setLoading] = useState(() => {
    const token = getAuthToken();
    if (!token) return false;
    return !getAuthUser() || !getCachedRegions()?.length;
  });

  const refreshUser = useCallback(async () => {
    if (!getAuthToken()) {
      setUser(null);
      return;
    }
    const boot = await fetchSessionBootstrap();
    setUser(boot.user);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = getAuthToken();
      syncAuthCookie(token);
      if (!token) {
        if (!cancelled) {
          setUser(null);
          setLoading(false);
        }
        return;
      }
      const cached = getAuthUser();
      const cachedRegions = getCachedRegions();
      if (cached && cachedRegions?.length && !cancelled) {
        setUser(cached);
        setLoading(false);
      }
      try {
        const boot = await fetchSessionBootstrap();
        if (!cancelled) setUser(boot.user);
      } catch {
        clearAuth();
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (account: string, password: string) => {
    const result = await loginWithApi(account, password);
    setUser(result.user);
  }, []);

  const logout = useCallback(async () => {
    await logoutWithApi();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      isAuthenticated: Boolean(user && getAuthToken()),
      login,
      logout,
      refreshUser,
      hasPermission: (perm: string) => hasPermission(user, perm),
    }),
    [user, loading, login, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
