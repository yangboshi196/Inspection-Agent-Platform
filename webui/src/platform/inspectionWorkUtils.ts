import type { CameraDevice, InspectionScheduleMode, InspectionWorkEntity, SensorDevice } from "./types";

export const SCHEDULE_MODE_OPTIONS: Array<{
  id: InspectionScheduleMode;
  label: string;
  hint: string;
}> = [
  { id: "periodic", label: "周期检查", hint: "按固定间隔重复执行，如每 4 小时、每日" },
  { id: "scheduled", label: "定时检查", hint: "在指定时刻触发，如每日 08:00、14:00" },
  { id: "continuous", label: "持续监控", hint: "内置每 10 秒分析前 10 秒画面，异常即告警" },
  { id: "manual", label: "手动触发", hint: "由用户按需启动，无自动调度" },
];

export const PERIODIC_INTERVAL_OPTIONS = ["每1小时", "每4小时", "每12小时", "每日", "每周", "每月"];

/** 持续监控内置检查间隔（与后端 CONTINUOUS_CHECK_INTERVAL_SEC 一致） */
export const CONTINUOUS_CHECK_INTERVAL_LABEL = "每10秒";
export const CONTINUOUS_ANALYSIS_WINDOW_SEC = 10;

export function scheduleModeLabel(mode: InspectionScheduleMode): string {
  return SCHEDULE_MODE_OPTIONS.find((o) => o.id === mode)?.label ?? mode;
}

/** 展示/编辑用的有效区域 id 列表（兼容 region_ids 为空但 region_id 有值） */
export function effectiveRegionIds(
  work: Pick<InspectionWorkEntity, "region_ids" | "region_id">,
): string[] {
  const ids = (work.region_ids ?? []).map((x) => x.trim()).filter(Boolean);
  if (ids.length > 0) return ids;
  const primary = (work.region_id ?? "").trim();
  return primary ? [primary] : [];
}

/** 由 region_ids 与名称表生成展示文案 */
export function formatWorkRegionLabel(
  regionIds: string[],
  nameById: Map<string, string> | Record<string, string>,
): { region_id: string; region_name: string; region_ids: string[] } {
  const ids = regionIds.map((x) => x.trim()).filter(Boolean);
  const lookup = (id: string) =>
    nameById instanceof Map ? nameById.get(id) ?? id : nameById[id] ?? id;
  if (ids.length === 0) {
    return { region_id: "", region_name: "未选择区域", region_ids: [] };
  }
  if (ids.length === 1) {
    return { region_id: ids[0], region_name: lookup(ids[0]), region_ids: ids };
  }
  return {
    region_id: ids[0],
    region_name: `${lookup(ids[0])} 等 ${ids.length} 个区域`,
    region_ids: ids,
  };
}

/** 从已选设备推导巡检业务所属区域（支持多区域） */
export function deriveWorkRegion(
  equipIds: string[],
  cameras: CameraDevice[],
  sensors: SensorDevice[],
): { region_id: string; region_name: string; region_ids: string[] } {
  const map = new Map<string, string>();
  for (const id of equipIds) {
    const cam = cameras.find((c) => c.id === id);
    if (cam) map.set(cam.regionId, cam.regionName);
    const sen = sensors.find((s) => s.id === id);
    if (sen) map.set(sen.regionId, sen.regionName);
  }
  if (map.size === 0) {
    return { region_id: "", region_name: "未绑定设备", region_ids: [] };
  }
  const entries = [...map.entries()];
  const region_ids = entries.map(([id]) => id);
  if (entries.length === 1) {
    return { region_id: entries[0][0], region_name: entries[0][1], region_ids };
  }
  return {
    region_id: entries[0][0],
    region_name: `${entries[0][1]} 等 ${entries.length} 个区域`,
    region_ids,
  };
}

export function applyEquipmentWithRegion(
  work: InspectionWorkEntity,
  equipment_set: InspectionWorkEntity["equipment_set"],
  cameras: CameraDevice[],
  sensors: SensorDevice[],
  nameById?: Map<string, string> | Record<string, string>,
): Pick<InspectionWorkEntity, "equipment_set" | "region_id" | "region_name" | "region_ids"> {
  const ids = equipment_set.map((e) => e.equipment_id);
  const hasManualRegions = (work.region_ids?.length ?? 0) > 0;
  if (hasManualRegions && nameById) {
    const region = formatWorkRegionLabel(work.region_ids!, nameById);
    return { equipment_set, ...region };
  }
  const region = deriveWorkRegion(ids, cameras, sensors);
  return {
    equipment_set,
    region_id: region.region_id,
    region_name: region.region_name,
    region_ids: region.region_ids,
  };
}
