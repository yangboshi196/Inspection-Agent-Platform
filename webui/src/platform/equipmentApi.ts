import { readApiError, apiFetch } from "../api";
import type { CameraDevice, SensorDevice } from "./types";

export type SensorReadingRow = {
  time: string;
  value: number;
  status: string;
};

export type EquipmentApiRow = {
  id: string;
  kind: "camera" | "sensor";
  name: string;
  region_id: string;
  description: string;
  platform_name: string;
  platform_address: string;
  thumbnail: string;
  data_type: string;
  unit: string;
  online: boolean;
  simulate_video_relpath?: string;
  simulate_video_url?: string;
};

function apiBase() {
  return import.meta.env.DEV ? "" : ".";
}

export function equipmentMediaUrl(path: string): string {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  const base = apiBase();
  if (path.startsWith("/")) {
    return base ? `${base}${path}` : path;
  }
  return base ? `${base}/${path}` : `/${path}`;
}

export function apiRowToCamera(row: EquipmentApiRow, regionName: string): CameraDevice {
  return {
    id: row.id,
    name: row.name,
    description: row.description,
    regionId: row.region_id,
    regionName,
    platformName: row.platform_name,
    platformAddress: row.platform_address,
    thumbnail: row.thumbnail || "linear-gradient(135deg, #434343, #757575)",
    online: row.online,
    simulateVideoUrl: row.simulate_video_url
      ? equipmentMediaUrl(row.simulate_video_url)
      : undefined,
  };
}

export function apiRowToSensor(row: EquipmentApiRow, regionName: string): SensorDevice {
  return {
    id: row.id,
    name: row.name,
    description: row.description,
    regionId: row.region_id,
    regionName,
    dataType: row.data_type,
    unit: row.unit,
    platformName: row.platform_name,
    platformAddress: row.platform_address,
    online: row.online,
  };
}

export async function listEquipment(params?: {
  kind?: "camera" | "sensor";
  region_id?: string;
  region_ids?: string[];
}): Promise<{ items: EquipmentApiRow[]; total: number }> {
  const q = new URLSearchParams({ limit: "500" });
  if (params?.kind) q.set("kind", params.kind);
  if (params?.region_ids && params.region_ids.length > 0) {
    q.set("region_ids", params.region_ids.join(","));
  } else if (params?.region_id) {
    q.set("region_id", params.region_id);
  }
  const res = await apiFetch(`${apiBase()}/api/equipment/?${q}`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: EquipmentApiRow[]; total: number };
  return data;
}

export type EquipmentBatchImportResult = {
  inserted: number;
  skipped: number;
  errors: Array<{ row: number; error: string }>;
};

export async function batchImportEquipment(
  items: Array<{
    id?: string;
    name: string;
    kind: string;
    description?: string;
    region_id: string;
  }>,
  skipExisting = true,
): Promise<EquipmentBatchImportResult> {
  const res = await apiFetch(`${apiBase()}/api/equipment/import/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, skip_existing: skipExisting }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as EquipmentBatchImportResult;
}

export async function seedBuiltinEquipment(replaceAll = false): Promise<number> {
  const q = replaceAll ? "?replace_all=true" : "";
  const res = await apiFetch(`${apiBase()}/api/equipment/seed/builtin${q}`, { method: "POST" });
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { inserted: number };
  return data.inserted ?? 0;
}

export async function importBuiltinEquipment(replaceAll = false): Promise<number> {
  return seedBuiltinEquipment(replaceAll);
}

export async function createEquipment(body: Record<string, unknown>): Promise<EquipmentApiRow> {
  const res = await apiFetch(`${apiBase()}/api/equipment/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as EquipmentApiRow;
}

export async function patchEquipment(
  id: string,
  body: Record<string, unknown>,
): Promise<EquipmentApiRow> {
  const res = await apiFetch(`${apiBase()}/api/equipment/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as EquipmentApiRow;
}

export async function deleteEquipment(id: string): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/equipment/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readApiError(res));
}

export async function uploadEquipmentSimulateVideo(
  equipmentId: string,
  file: File,
): Promise<EquipmentApiRow> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiFetch(
    `${apiBase()}/api/equipment/${encodeURIComponent(equipmentId)}/simulate-video`,
    { method: "POST", body: fd },
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as EquipmentApiRow;
}

/** 全平台统一主码流 1080p 查询参数 */
export function mainHdLiveQueryParams(
  extra?: URLSearchParams,
): URLSearchParams {
  const params = extra ?? new URLSearchParams();
  params.set("stream", "main");
  params.set("quality", "hd");
  return params;
}

/** RTSP 单帧快照 URL（img src；需 access_token） */
export function equipmentLiveSnapshotUrl(
  equipmentId: string,
  options?: EquipmentLiveStreamOptions,
): string {
  const params = mainHdLiveQueryParams(new URLSearchParams({ t: String(Date.now()) }));
  if (options?.previewRtsp?.trim()) params.set("preview_rtsp", options.previewRtsp.trim());
  appendEquipmentLiveAuth(params);
  return `${apiBase()}/api/equipment/${encodeURIComponent(equipmentId)}/live/snapshot?${params}`;
}

export async function fetchEquipmentLiveSnapshot(equipmentId: string): Promise<Blob> {
  const res = await apiFetch(equipmentLiveSnapshotUrl(equipmentId));
  if (!res.ok) throw new Error(await readApiError(res));
  return res.blob();
}

/** HTTP-FLV 直播 URL（XGPlayer / flv.js；需 access_token 查询参数） */
export type EquipmentLiveStreamOptions = {
  stream?: "auto" | "main" | "sub";
  quality?: "preview" | "hd";
  /** 区域配置未保存时，用表单中的 RTSP 预览 */
  previewRtsp?: string;
};

/** 全平台摄像头统一：go2rtc 主码流 H.265 1080p */
export const GO2RTC_LIVE_DEFAULTS: EquipmentLiveStreamOptions = {
  stream: "main",
  quality: "hd",
};

function appendEquipmentLiveAuth(params: URLSearchParams) {
  try {
    const token = localStorage.getItem("SIA_auth_token");
    if (token) params.set("access_token", token);
  } catch {
    /* ignore */
  }
}

export function equipmentLiveFlvUrl(
  equipmentId: string,
  options?: EquipmentLiveStreamOptions,
): string {
  const params = mainHdLiveQueryParams(new URLSearchParams({ t: String(Date.now()) }));
  if (options?.previewRtsp?.trim()) params.set("preview_rtsp", options.previewRtsp.trim());
  appendEquipmentLiveAuth(params);
  return `${apiBase()}/api/equipment/${encodeURIComponent(equipmentId)}/live/flv?${params}`;
}

/** MJPEG 实时预览 URL（img src；需 access_token 查询参数供浏览器直连） */
export function equipmentLiveMjpegUrl(
  equipmentId: string,
  fps = 15,
  options?: Pick<EquipmentLiveStreamOptions, "previewRtsp">,
): string {
  const params = new URLSearchParams({ fps: String(fps), stream: "main", quality: "hd" });
  if (options?.previewRtsp?.trim()) params.set("preview_rtsp", options.previewRtsp.trim());
  appendEquipmentLiveAuth(params);
  return `${apiBase()}/api/equipment/${encodeURIComponent(equipmentId)}/live/mjpeg?${params}`;
}

export async function loadSensorReadings(equipmentId: string): Promise<SensorReadingRow[]> {
  const res = await apiFetch(`${apiBase()}/api/equipment/${encodeURIComponent(equipmentId)}/readings?limit=100`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: SensorReadingRow[] };
  return data.items ?? [];
}

export async function importDemoEquipment(replaceAll = false): Promise<number> {
  return importBuiltinEquipment(replaceAll);
}

export async function loadCamerasAndSensors(
  regionNameOf: (id: string) => string,
): Promise<{ cameras: CameraDevice[]; sensors: SensorDevice[] }> {
  const { items } = await listEquipment();
  const cameras: CameraDevice[] = [];
  const sensors: SensorDevice[] = [];
  for (const row of items) {
    const rn = regionNameOf(row.region_id);
    if (row.kind === "camera") cameras.push(apiRowToCamera(row, rn));
    else sensors.push(apiRowToSensor(row, rn));
  }
  return { cameras, sensors };
}
