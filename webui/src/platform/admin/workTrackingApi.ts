import { readApiError, apiFetch } from "../../api";

export type WorkTrackingQueueStatus = "waiting" | "running" | "completed";

export type WorkTrackingItem = {
  work_id: string;
  work_name: string;
  schedule_mode: string;
  published: boolean;
  queue_status: WorkTrackingQueueStatus;
  published_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  estimated_start_at: string | null;
  estimated_end_at: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkTrackingSummary = {
  waiting: number;
  running: number;
  completed: number;
  total: number;
};

function apiBase() {
  return import.meta.env.DEV ? "" : ".";
}

export async function getWorkTrackingSummary(): Promise<WorkTrackingSummary> {
  const res = await apiFetch(`${apiBase()}/api/inspection-work/tracking/summary`);
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as WorkTrackingSummary;
}

export async function listWorkTracking(
  status?: WorkTrackingQueueStatus,
): Promise<WorkTrackingItem[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await apiFetch(`${apiBase()}/api/inspection-work/tracking${qs}`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: WorkTrackingItem[] };
  return data.items ?? [];
}

export async function getWorkTracking(workId: string): Promise<WorkTrackingItem> {
  const res = await apiFetch(
    `${apiBase()}/api/inspection-work/tracking/${encodeURIComponent(workId)}`,
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as WorkTrackingItem;
}

export async function publishWorkTracking(workId: string): Promise<WorkTrackingItem> {
  const res = await apiFetch(
    `${apiBase()}/api/inspection-work/tracking/${encodeURIComponent(workId)}/publish`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as WorkTrackingItem;
}

export async function unpublishWorkTracking(workId: string): Promise<WorkTrackingItem> {
  const res = await apiFetch(
    `${apiBase()}/api/inspection-work/tracking/${encodeURIComponent(workId)}/unpublish`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as WorkTrackingItem;
}
