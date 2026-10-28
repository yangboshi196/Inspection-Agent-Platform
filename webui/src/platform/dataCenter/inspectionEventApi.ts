import { readApiError, apiFetch } from "../../api";
import { GO2RTC_LIVE_DEFAULTS, equipmentLiveSnapshotUrl, equipmentMediaUrl } from "../equipmentApi";
import {
  buildEventResolution,
  type DataCenterEvent,
  type WorkRuntimeStatus,
} from "./dataCenterMock";
import { parseEventDetection } from "./eventDetection";

export type InspectionEventApiRow = {
  event_id: string;
  kind: "video" | "sensor" | string;
  title: string;
  source_name: string;
  work_id: string;
  work_name: string;
  region_id: string;
  region_name: string;
  equipment_id: string;
  algorithm_name: string;
  rule_name: string;
  status: string;
  value_num: number | null;
  threshold_text: string;
  snapshot_gradient: string;
  media_video_url?: string;
  media_snapshot_url?: string;
  media_live_flv_url?: string;
  media_live_snapshot_url?: string;
  media_has_rtsp?: boolean;
  equipment_online?: boolean;
  occurred_at: string;
  reported_at: string;
  handler: string;
  handled_at: string;
  resolution_outcome: string;
  resolution_detail: string;
  detection_json?: string;
};

export type DashboardStatsResponse = {
  kpi: {
    inspections_today: number;
    inspections_delta: number;
    pending_events: number;
    alert_delta: number;
    alerts_week: number;
    resolved_week: number;
    camera_count: number;
    sensor_count: number;
    device_total: number;
    active_works: number;
    event_total: number;
  };
  weekly_trend: Array<{
    label: string;
    date: string;
    alerts: number;
    resolved: number;
    inspections: number;
  }>;
  event_trend_by_type: Record<string, number[]>;
  event_trend_by_region: Record<string, number[]>;
  event_trend_by_work?: Record<string, number[]>;
  event_trend?: Record<string, number[]>;
  trend_labels?: string[];
  trend_meta?: {
    days: number;
    granularity?: "day" | "hour";
    group_by: string;
    status: string;
    kind: string;
    region_id: string | null;
    anchor_date?: string;
    trend_date?: string | null;
  };
  day_events?: DashboardDayEvent[];
  available_dates?: string[];
  risk_type_options?: string[];
  weekly_meta?: {
    days: number;
    week_start: string;
    week_end: string;
    work_id: string | null;
    risk_type: string | null;
  };
};

export type DashboardDayEvent = {
  event_id: string;
  title: string;
  occurred_at: string;
  occurred_time: string;
  reported_at?: string;
  status: string;
  kind: string;
  region_name: string;
  work_name: string;
  source_name?: string;
};

export type DashboardTrendParams = {
  trend_days?: number;
  trend_group_by?: string;
  trend_status?: string;
  trend_kind?: string;
  trend_region_id?: string;
  trend_date?: string;
  weekly_work_id?: string;
  weekly_risk_type?: string;
};

export type WorkRuntimeApiRow = {
  work_id: string;
  name: string;
  region_id: string;
  region_name: string;
  schedule_mode: string;
  health: WorkRuntimeStatus["health"];
  last_run: string;
  next_run: string;
  compliance: number;
  alerts_7d: number;
  alert_resolution_rate: number;
  pending_events: number;
};

function apiBase() {
  return import.meta.env.DEV ? "" : ".";
}

function parseApiDate(raw: string): Date | null {
  const s = (raw || "").trim();
  if (!s) return null;
  if (s.includes("T") || s.endsWith("Z")) {
    const normalized = s.endsWith("Z") ? s : s;
    const d = new Date(normalized);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/.test(s)) {
    const iso = s.length === 16 ? `${s}:00` : s;
    const d = new Date(`${iso.replace(" ", "T")}Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatDisplayTime(raw: string): string {
  const d = parseApiDate(raw);
  if (!d) {
    const s = (raw || "").trim();
    return s ? (s.length >= 19 ? s.slice(0, 19) : s) : "—";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}:${pad(d.getSeconds())}`;
}

function isInspectionCompleteEvent(title: string, status: DataCenterEvent["status"]): boolean {
  return status === "resolved" && title.includes("巡检完成");
}

function normalizeConfidence(value: number | null): number | undefined {
  if (value == null || Number.isNaN(value)) {
    return undefined;
  }
  if (value > 1 && value <= 100) return value / 100;
  if (value > 0 && value <= 1) return value;
  return undefined;
}

export function apiRowToDataCenterEvent(row: InspectionEventApiRow): DataCenterEvent {
  const type: "video" | "sensor" = row.kind === "sensor" ? "sensor" : "video";
  const time = formatDisplayTime(row.occurred_at);
  const reportedAt = row.reported_at ? formatDisplayTime(row.reported_at) : time;
  const status = (["pending", "processing", "resolved", "ignored"].includes(row.status)
    ? row.status
    : "pending") as DataCenterEvent["status"];
  const gradient =
    row.snapshot_gradient || "linear-gradient(135deg, #33415544, #64748b66)";
  const detection = parseEventDetection(row.detection_json);
  const hasRtsp = row.media_has_rtsp ?? Boolean(row.media_live_flv_url);
  const snapshotImageUrl =
    type === "video" && row.media_snapshot_url
      ? equipmentMediaUrl(row.media_snapshot_url)
      : detection?.snapshotUrl
        ? equipmentMediaUrl(detection.snapshotUrl)
        : undefined;
  const rtspSnapshotUrl =
    type === "video" && hasRtsp && row.equipment_id && !snapshotImageUrl
      ? equipmentLiveSnapshotUrl(row.equipment_id, GO2RTC_LIVE_DEFAULTS)
      : undefined;
  const snapshotDisplayUrl = snapshotImageUrl ?? rtspSnapshotUrl;
  const equipmentOnline = row.equipment_online ?? status !== "resolved";
  const inspectionComplete = isInspectionCompleteEvent(row.title, status);
  const snapshotMismatch = Boolean(detection?.snapshotMismatch);
  const confidence = inspectionComplete
    ? undefined
    : snapshotMismatch
      ? undefined
      : detection?.displayConfidence != null
        ? normalizeConfidence(detection.displayConfidence)
        : normalizeConfidence(row.value_num);

  const resolution = row.resolution_detail?.trim()
    ? {
        outcome: row.resolution_outcome || "已更新",
        handler: row.handler || undefined,
        handledAt: row.handled_at ? formatDisplayTime(row.handled_at) : undefined,
        detail: row.resolution_detail,
      }
    : buildEventResolution(status, type, row.title, time);

  return {
    id: row.event_id,
    type,
    title: row.title,
    source: row.source_name,
    work: row.work_name,
    time,
    reportedAt,
    status,
    algorithmName: row.algorithm_name || undefined,
    cameraId: type === "video" ? row.equipment_id || undefined : undefined,
    sensorId: type === "sensor" ? row.equipment_id || undefined : undefined,
    value: row.value_num ?? undefined,
    threshold: row.threshold_text || undefined,
    snapshot: {
      capturedAt: reportedAt,
      gradient,
      imageUrl: snapshotDisplayUrl,
      aiLabel: inspectionComplete
        ? row.algorithm_name
          ? `${row.algorithm_name} · 未检出`
          : "巡检完成 · 未检出"
        : row.title,
      confidence,
      detection,
    },
    recording: null,
    live:
      type === "video"
        ? {
            cameraName: row.source_name,
            cameraId: row.equipment_id || "—",
            online: equipmentOnline,
            gradient: "linear-gradient(145deg, #0f172a, #1e3a5f)",
            latencyMs: equipmentOnline ? 680 : 0,
          }
        : null,
    resolution,
    hasRtsp,
  };
}

export function apiRowToWorkRuntime(row: WorkRuntimeApiRow): WorkRuntimeStatus {
  return {
    workId: row.work_id,
    name: row.name,
    regionName: row.region_name,
    scheduleMode: row.schedule_mode as WorkRuntimeStatus["scheduleMode"],
    health: row.health,
    lastRun: formatDisplayTime(row.last_run).slice(0, 16),
    nextRun: row.next_run,
    compliance: row.compliance,
    alerts7d: row.alerts_7d,
    alertResolutionRate: row.alert_resolution_rate,
  };
}

async function ensureSeeded(): Promise<void> {
  /* 事件仅由算法/大模型阳性入库，不再自动导入演示数据 */
}

export async function syncInspectionDetectionBoxes(params?: { limit?: number }): Promise<{
  updated: number;
  skipped: number;
  failed: number;
  scanned: number;
}> {
  const q = new URLSearchParams();
  if (params?.limit != null) q.set("limit", String(params.limit));
  const res = await apiFetch(
    `${apiBase()}/api/inspection-events/sync-detection-boxes${q.size ? `?${q}` : ""}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as {
    updated: number;
    skipped: number;
    failed: number;
    scanned: number;
  };
}

export async function syncInspectionEventMedia(params?: { limit?: number }): Promise<{
  updated: number;
  skipped: number;
  failed: number;
  scanned: number;
}> {
  const q = new URLSearchParams();
  if (params?.limit != null) q.set("limit", String(params.limit));
  const res = await apiFetch(
    `${apiBase()}/api/inspection-events/sync-media${q.size ? `?${q}` : ""}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as {
    updated: number;
    skipped: number;
    failed: number;
    scanned: number;
  };
}

export async function fetchInspectionEvent(eventId: string): Promise<DataCenterEvent> {
  const res = await apiFetch(
    `${apiBase()}/api/inspection-events/${encodeURIComponent(eventId)}`,
  );
  if (!res.ok) throw new Error(await readApiError(res));
  const row = (await res.json()) as InspectionEventApiRow;
  return apiRowToDataCenterEvent(row);
}

export type InspectionEventsPage = {
  items: DataCenterEvent[];
  total: number;
  limit: number;
  offset: number;
};

export async function loadInspectionEventsPage(params?: {
  kind?: string;
  status?: string;
  work_id?: string;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<InspectionEventsPage> {
  await ensureSeeded();
  const limit = params?.limit ?? 200;
  const offset = params?.offset ?? 0;
  const q = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.work_id) q.set("work_id", params.work_id);
  if (params?.q) q.set("q", params.q);
  const res = await apiFetch(`${apiBase()}/api/inspection-events/?${q}`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as {
    items: InspectionEventApiRow[];
    total: number;
    limit: number;
    offset: number;
  };
  return {
    items: data.items.map(apiRowToDataCenterEvent),
    total: data.total,
    limit: data.limit,
    offset: data.offset,
  };
}

export async function loadInspectionEvents(params?: {
  kind?: string;
  status?: string;
  work_id?: string;
  limit?: number;
}): Promise<DataCenterEvent[]> {
  const page = await loadInspectionEventsPage(params);
  return page.items;
}

export async function loadDashboardStats(
  params?: DashboardTrendParams,
): Promise<DashboardStatsResponse> {
  await ensureSeeded();
  const q = new URLSearchParams();
  if (params?.trend_days != null) q.set("trend_days", String(params.trend_days));
  if (params?.trend_group_by) q.set("trend_group_by", params.trend_group_by);
  if (params?.trend_status && params.trend_status !== "all") {
    q.set("trend_status", params.trend_status);
  }
  if (params?.trend_kind && params.trend_kind !== "all") {
    q.set("trend_kind", params.trend_kind);
  }
  if (params?.trend_region_id && params.trend_region_id !== "all") {
    q.set("trend_region_id", params.trend_region_id);
  }
  if (params?.trend_date) {
    q.set("trend_date", params.trend_date);
  }
  if (params?.weekly_work_id) q.set("weekly_work_id", params.weekly_work_id);
  if (params?.weekly_risk_type) q.set("weekly_risk_type", params.weekly_risk_type);
  const qs = q.toString();
  const res = await apiFetch(
    `${apiBase()}/api/inspection-events/stats${qs ? `?${qs}` : ""}`,
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as DashboardStatsResponse;
}

export async function loadWorkRuntimeRows(): Promise<WorkRuntimeApiRow[]> {
  await ensureSeeded();
  const res = await apiFetch(`${apiBase()}/api/inspection-events/runtime/works`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: WorkRuntimeApiRow[] };
  return data.items;
}

export async function patchInspectionEventStatus(
  eventId: string,
  status: DataCenterEvent["status"],
  resolution?: {
    handler?: string;
    handled_at?: string;
    resolution_outcome?: string;
    resolution_detail?: string;
  },
): Promise<DataCenterEvent> {
  const res = await apiFetch(`${apiBase()}/api/inspection-events/${encodeURIComponent(eventId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, ...resolution }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  const row = (await res.json()) as InspectionEventApiRow;
  return apiRowToDataCenterEvent(row);
}
