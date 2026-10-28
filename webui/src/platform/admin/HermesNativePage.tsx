import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { exposePluginSDK } from "@hermes/plugins";
import type { HermesTabSlug } from "../hermesAgent";
import { hermesDashboardPathFromSlug } from "../hermesAgent";

const HermesNativeShell = lazy(() =>
  import("./HermesNativeShell").then((m) => ({ default: m.HermesNativeShell })),
);

const TOKEN_RE = /window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"/;
const AUTH_RE = /window\.__HERMES_AUTH_REQUIRED__\s*=\s*(true|false)/;

function hermesPathToSlug(pathname: string): HermesTabSlug {
  const p = pathname.replace(/\/+$/, "") || "/";
  if (p === "/chat") return "chat";
  if (p === "/sessions") return "sessions";
  if (p === "/analytics") return "analytics";
  if (p === "/models") return "models";
  if (p === "/logs") return "logs";
  if (p === "/cron") return "cron";
  if (p === "/skills") return "skills";
  if (p === "/plugins") return "plugins";
  if (p === "/profiles") return "profiles";
  if (p === "/config") return "config";
  if (p === "/env") return "env";
  if (p === "/docs") return "docs";
  return "sessions";
}

async function bootstrapHermesGlobals() {
  const win = window as typeof window & {
    __HERMES_BASE_PATH__?: string;
    __HERMES_SESSION_TOKEN__?: string;
    __HERMES_AUTH_REQUIRED__?: boolean;
  };
  // 开发态统一走 webui 自己的代理前缀，避免把 /hermes-agent/* 路由抢走。
  const basePath = import.meta.env.DEV ? "/api/hermes" : "/hermes-agent";
  win.__HERMES_BASE_PATH__ = basePath;
  if (win.__HERMES_SESSION_TOKEN__) return;

  const res = await fetch(`${basePath}/`, { credentials: "include" });
  if (!res.ok) throw new Error(`Hermes bootstrap failed: HTTP ${res.status}`);
  const html = await res.text();
  const tm = html.match(TOKEN_RE);
  if (tm?.[1]) win.__HERMES_SESSION_TOKEN__ = tm[1];
  const am = html.match(AUTH_RE);
  if (am?.[1]) win.__HERMES_AUTH_REQUIRED__ = am[1] === "true";
}

export function HermesNativePage({ tab }: { tab: string | undefined }) {
  const dashboardPath = useMemo(() => hermesDashboardPathFromSlug(tab), [tab]);
  const routeKey = useMemo(() => hermesPathToSlug(dashboardPath), [dashboardPath]);
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    exposePluginSDK();
  }, []);

  useEffect(() => {
    let disposed = false;
    setReady(false);
    setErr(null);
    bootstrapHermesGlobals()
      .then(() => {
        if (!disposed) setReady(true);
      })
      .catch((e: unknown) => {
        if (!disposed) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      disposed = true;
    };
  }, [routeKey]);

  if (err) {
    return <div className="pf-hermes-status pf-hermes-status-error">{err}</div>;
  }
  if (!ready) {
    return <div className="pf-hermes-status">正在加载 Hermes 原生页面…</div>;
  }

  return (
    <Suspense fallback={<div className="pf-hermes-status">正在装载 Hermes 内核…</div>}>
      <HermesNativeShell dashboardPath={dashboardPath} routeKey={routeKey} />
    </Suspense>
  );
}
