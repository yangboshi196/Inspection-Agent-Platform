import type { WorkTrackingItem, WorkTrackingQueueStatus } from "./workTrackingApi";

/** 业务追踪列表时间展示：26年7月8日18时00分00秒 */
export function formatTrackingTime(
  raw: string | null | undefined,
  variant: "full" | "short" = "full",
): string {
  if (!raw?.trim()) return "—";
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return raw;
  const y = d.getFullYear() % 100;
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const hour = d.getHours();
  const minute = String(d.getMinutes()).padStart(2, "0");
  const second = String(d.getSeconds()).padStart(2, "0");
  if (variant === "short") {
    return `${y}年${month}月${day}日${hour}：${minute}：${second}`;
  }
  return `${y}年${month}月${day}日${hour}时${minute}分${second}秒`;
}

export const TRACKING_STATUS_LABEL: Record<WorkTrackingQueueStatus, string> = {
  waiting: "等待中",
  running: "进行中",
  completed: "已完成",
};

/** 手动触发等待态、持续监控进行中等固定文案（与 schedule_mode 语义一致） */
const DISPLAY_LITERAL = {
  manualWaitStart: "等待手动触发",
  noEstimate: "/",
  continuousRunEnd: "持续监控中，手动关闭",
} as const;

/**
 * 按运行周期 + 队列状态解析列表时间展示。
 * 不改 API 字段，仅在前端将 DB 时间戳映射为语义化文案。
 */
export function formatTrackingTimeDisplay(
  item: WorkTrackingItem,
  role: "start" | "end",
): string {
  const mode = item.schedule_mode;
  const status = item.queue_status;

  if (status === "waiting" && mode === "manual") {
    return role === "start" ? DISPLAY_LITERAL.manualWaitStart : DISPLAY_LITERAL.noEstimate;
  }
  if (status === "waiting" && mode === "continuous" && role === "end") {
    return DISPLAY_LITERAL.noEstimate;
  }
  if (status === "running" && mode === "continuous" && role === "end") {
    return DISPLAY_LITERAL.continuousRunEnd;
  }

  const raw =
    status === "waiting"
      ? role === "start"
        ? item.estimated_start_at
        : item.estimated_end_at
      : status === "running"
        ? role === "start"
          ? item.started_at ?? item.estimated_start_at
          : item.estimated_end_at
        : role === "start"
          ? item.started_at
          : item.ended_at;

  if (!raw?.trim()) {
    return DISPLAY_LITERAL.noEstimate;
  }
  return formatTrackingTime(raw, status === "completed" && role === "start" ? "short" : "full");
}
