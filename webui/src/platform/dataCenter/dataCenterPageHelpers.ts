import { MOCK_INSPECTION_WORKS } from "../mockData";
import { scheduleModeLabel } from "../inspectionWorkUtils";
import type { InspectionScheduleMode, InspectionWorkEntity } from "../types";
import {
  DC_RECENT_EVENTS,
  DC_WORK_RUNTIME,
  type WorkRuntimeStatus,
} from "./dataCenterMock";
import {
  frequencyLabel,
  inspectionReportStats,
  reportStatusLabel,
  reportStatusTone,
  type InspectionReport,
} from "./reportPlanMock";

/** @deprecated 使用 frequencyLabel */
export function reportTypeLabel(t: InspectionReport["frequency"]) {
  return frequencyLabel(t);
}

export { reportStatusLabel, reportStatusTone };

export function reportStats(reports: InspectionReport[]) {
  return inspectionReportStats(reports);
}

export function eventStatusLabel(status: string) {
  if (status === "resolved") return "已关闭";
  if (status === "processing") return "处理中";
  return "待处理";
}

export function eventBadgeTone(status: string): "success" | "info" | "warning" {
  if (status === "resolved") return "success";
  if (status === "processing") return "info";
  return "warning";
}

export function eventStats(events: typeof DC_RECENT_EVENTS) {
  return {
    total: events.length,
    pending: events.filter((e) => e.status === "pending").length,
    processing: events.filter((e) => e.status === "processing").length,
    resolved: events.filter((e) => e.status === "resolved").length,
    video: events.filter((e) => e.type === "video").length,
    sensor: events.filter((e) => e.type === "sensor").length,
  };
}

export function workCompleteness(w: InspectionWorkEntity) {
  let s = 0;
  if (w.rule_set.length) s += 34;
  if (w.algorithm_set.length) s += 33;
  if (w.equipment_set.length) s += 33;
  return s;
}

export function workDisplayStats(works: InspectionWorkEntity[]) {
  const modes: InspectionScheduleMode[] = ["periodic", "scheduled", "continuous", "manual"];
  return {
    total: works.length,
    periodic: works.filter((w) => w.schedule_mode === "periodic").length,
    scheduled: works.filter((w) => w.schedule_mode === "scheduled").length,
    continuous: works.filter((w) => w.schedule_mode === "continuous").length,
    manual: works.filter((w) => w.schedule_mode === "manual").length,
    ai: works.filter((w) => w.source === "ai").length,
  };
}

export function scheduleTone(mode: InspectionScheduleMode): "info" | "success" | "warning" | "default" {
  if (mode === "periodic") return "info";
  if (mode === "scheduled") return "success";
  if (mode === "continuous") return "warning";
  return "default";
}

export function healthLabel(h: WorkRuntimeStatus["health"]) {
  if (h === "healthy") return "正常";
  if (h === "warning") return "关注";
  if (h === "critical") return "异常";
  return "空闲";
}

export function healthTone(h: WorkRuntimeStatus["health"]): "success" | "warning" | "error" | "default" {
  if (h === "healthy") return "success";
  if (h === "warning") return "warning";
  if (h === "critical") return "error";
  return "default";
}

export function statusPageStats(items: WorkRuntimeStatus[]) {
  const avgCompliance = items.length
    ? Math.round(items.reduce((a, w) => a + w.compliance, 0) / items.length)
    : 0;
  return {
    total: items.length,
    healthy: items.filter((w) => w.health === "healthy").length,
    warning: items.filter((w) => w.health === "warning" || w.health === "critical").length,
    idle: items.filter((w) => w.health === "idle").length,
    avgCompliance,
  };
}

export { scheduleModeLabel, MOCK_INSPECTION_WORKS, DC_RECENT_EVENTS, DC_WORK_RUNTIME };
