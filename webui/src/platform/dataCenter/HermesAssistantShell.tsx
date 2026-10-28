import { useEffect, useState } from "react";
import { exposePluginSDK } from "@hermes/plugins";

const TOKEN_RE = /window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"/;
const AUTH_RE = /window\.__HERMES_AUTH_REQUIRED__\s*=\s*(true|false)/;

export async function bootstrapHermesGlobals() {
  const win = window as typeof window & {
    __HERMES_BASE_PATH__?: string;
    __HERMES_SESSION_TOKEN__?: string;
    __HERMES_AUTH_REQUIRED__?: boolean;
  };
  const basePath = import.meta.env.DEV ? "/api/hermes" : "/hermes-agent";
  win.__HERMES_BASE_PATH__ = basePath;
  if (win.__HERMES_SESSION_TOKEN__) return;

  const res = await fetch(`${basePath}/`, { credentials: "include" });
  if (!res.ok) throw new Error(`助手服务初始化失败: HTTP ${res.status}`);
  const html = await res.text();
  const tm = html.match(TOKEN_RE);
  if (tm?.[1]) win.__HERMES_SESSION_TOKEN__ = tm[1];
  const am = html.match(AUTH_RE);
  if (am?.[1]) win.__HERMES_AUTH_REQUIRED__ = am[1] === "true";
}

export function useHermesBootstrap() {
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
  }, []);

  return { ready, err };
}
