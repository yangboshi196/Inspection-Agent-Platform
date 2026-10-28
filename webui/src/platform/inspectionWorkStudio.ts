import type { InspectionWorkEntity } from "./types";

export function emptyInspectionWork(): InspectionWorkEntity {
  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  return {
    work_id: `iw-man-${Date.now()}`,
    name: "新建巡检业务",
    region_id: "",
    region_name: "未绑定设备",
    region_ids: [],
    work_status: "online",
    desc: "",
    rule_set: [],
    algorithm_set: [],
    equipment_set: [],
    equipment_algo_params: {},
    source: "manual",
    schedule_mode: "manual",
    updated_at: now,
  };
}

export function toggleId<T extends string>(list: T[], id: T): T[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}
