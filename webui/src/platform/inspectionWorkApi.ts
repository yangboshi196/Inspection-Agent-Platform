import type { InspectionScheduleMode, InspectionWorkEntity } from "./types";
import { listInspectionWorksByEquipment } from "../api";
import { loadRegions, regionNameMap } from "./regionApi";

const SCHEDULE_MODES: InspectionScheduleMode[] = ["periodic", "scheduled", "continuous", "manual"];

function formatUpdatedAt(raw: unknown): string {
  if (typeof raw !== "string" || !raw.trim()) {
    return new Date().toISOString().slice(0, 16).replace("T", " ");
  }
  const s = raw.trim();
  if (s.includes("T")) return s.slice(0, 16).replace("T", " ");
  return s.slice(0, 16);
}

export function regionNameFor(regionId: string): string {
  if (!regionId) return "未绑定设备";
  return regionId;
}

export function apiRowToInspectionWork(row: Record<string, unknown>): InspectionWorkEntity {
  const scheduleRaw = String(row.schedule_mode ?? "manual");
  const schedule_mode = SCHEDULE_MODES.includes(scheduleRaw as InspectionScheduleMode)
    ? (scheduleRaw as InspectionScheduleMode)
    : "manual";
  const sourceRaw = String(row.source ?? "manual");
  const region_id = String(row.region_id ?? "");
  const regionIdsRaw = row.region_ids;
  const region_ids = Array.isArray(regionIdsRaw)
    ? regionIdsRaw.map((x) => String(x)).filter(Boolean)
    : region_id
      ? [region_id]
      : [];
  const workStatusRaw = String(row.work_status ?? "online");

  return {
    work_id: String(row.work_id ?? ""),
    name: String(row.name ?? ""),
    region_id,
    region_name: regionNameFor(region_id),
    region_ids,
    work_status: workStatusRaw === "offline" ? "offline" : "online",
    desc: String(row.desc ?? ""),
    rule_set: Array.isArray(row.rule_set) ? (row.rule_set as InspectionWorkEntity["rule_set"]) : [],
    algorithm_set: Array.isArray(row.algorithm_set)
      ? (row.algorithm_set as InspectionWorkEntity["algorithm_set"])
      : [],
    equipment_set: Array.isArray(row.equipment_set)
      ? (row.equipment_set as InspectionWorkEntity["equipment_set"])
      : [],
    equipment_algo_params:
      row.equipment_algo_params && typeof row.equipment_algo_params === "object"
        ? (row.equipment_algo_params as InspectionWorkEntity["equipment_algo_params"])
        : undefined,
    source: sourceRaw === "ai" ? "ai" : "manual",
    schedule_mode,
    schedule_interval:
      row.schedule_interval != null && String(row.schedule_interval).trim()
        ? String(row.schedule_interval)
        : undefined,
    schedule_times:
      row.schedule_times != null && String(row.schedule_times).trim()
        ? String(row.schedule_times)
        : undefined,
    updated_at: formatUpdatedAt(row.updated_at),
  };
}

export function inspectionWorkToCreateBody(work: InspectionWorkEntity): Record<string, unknown> {
  return {
    work_id: work.work_id,
    region_id: work.region_id,
    region_ids: work.region_ids ?? (work.region_id ? [work.region_id] : []),
    name: work.name.trim() || "未命名巡检业务",
    desc: work.desc,
    rule_set: work.rule_set,
    algorithm_set: work.algorithm_set,
    equipment_set: work.equipment_set,
    equipment_algo_params: work.equipment_algo_params ?? {},
    schedule_mode: work.schedule_mode,
    schedule_interval: work.schedule_interval ?? null,
    schedule_times: work.schedule_times ?? null,
    source: work.source,
    work_status: work.work_status ?? "online",
  };
}

export function inspectionWorkToPatchBody(work: InspectionWorkEntity): Record<string, unknown> {
  return {
    region_id: work.region_id,
    region_ids: work.region_ids ?? (work.region_id ? [work.region_id] : []),
    name: work.name.trim() || "未命名巡检业务",
    desc: work.desc,
    rule_set: work.rule_set,
    algorithm_set: work.algorithm_set,
    equipment_set: work.equipment_set,
    equipment_algo_params: work.equipment_algo_params ?? {},
    schedule_mode: work.schedule_mode,
    schedule_interval: work.schedule_interval ?? null,
    schedule_times: work.schedule_times ?? null,
    source: work.source,
    work_status: work.work_status ?? "online",
  };
}

export async function loadLinkedInspectionWorks(equipmentId: string): Promise<InspectionWorkEntity[]> {
  const [regions, worksRes] = await Promise.all([
    loadRegions(),
    listInspectionWorksByEquipment(equipmentId, 50),
  ]);
  if (!worksRes.ok) {
    const text = await worksRes.text();
    throw new Error(text || "加载关联巡检业务失败");
  }
  const names = regionNameMap(regions);
  const data = (await worksRes.json()) as { items: Record<string, unknown>[] };
  return (data.items ?? []).map((row) => {
    const w = apiRowToInspectionWork(row);
    if (!w.region_name && w.region_id) {
      w.region_name = names[w.region_id] || w.region_id;
    }
    return w;
  });
}
