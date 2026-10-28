/** Hermes Agent 仪表盘地址（默认经同源代理到本机 9119）。 */
export function hermesAgentBase(): string {
  const configured = import.meta.env.VITE_HERMES_AGENT_URL as string | undefined;
  if (configured?.trim()) return configured.trim().replace(/\/+$/, "");
  // 开发态统一走 vite 代理，避免 /hermes-agent/* 被前端路由接管后回退到平台首页。
  if (import.meta.env.DEV) return "/api/hermes";
  return "/hermes-agent";
}

export const HERMES_TABS = [
  { slug: "chat", label: "聊天", icon: "⌨", dashboardPath: "/chat" },
  { slug: "sessions", label: "会话记录", icon: "◍", dashboardPath: "/sessions" },
  { slug: "analytics", label: "分析", icon: "▦", dashboardPath: "/analytics" },
  { slug: "models", label: "模型", icon: "◈", dashboardPath: "/models" },
  { slug: "logs", label: "日志", icon: "≣", dashboardPath: "/logs" },
  { slug: "cron", label: "定时任务", icon: "⏱", dashboardPath: "/cron" },
  { slug: "skills", label: "技能", icon: "◬", dashboardPath: "/skills" },
  { slug: "plugins", label: "插件管理", icon: "⊞", dashboardPath: "/plugins" },
  { slug: "profiles", label: "多智能体配置", icon: "◉", dashboardPath: "/profiles" },
  { slug: "config", label: "配置", icon: "⚙", dashboardPath: "/config" },
  { slug: "env", label: "密钥", icon: "⛨", dashboardPath: "/env" },
  { slug: "docs", label: "文档", icon: "⊟", dashboardPath: "/docs" },
] as const;

export type HermesTabSlug = (typeof HERMES_TABS)[number]["slug"];

export function hermesDashboardPathFromSlug(slug: string | undefined): string {
  const tab = HERMES_TABS.find((x) => x.slug === slug);
  return tab?.dashboardPath ?? "/sessions";
}

export function hermesAgentUrlForTab(slug: string | undefined): string {
  const path = hermesDashboardPathFromSlug(slug);
  return `${hermesAgentBase()}${path}`;
}
