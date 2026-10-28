import { apiFetch, readApiError } from "../api";

export type LogSource = {
  id: string;
  label: string;
  available: boolean;
  size_bytes: number;
  updated_at: string;
  path: string;
};

export type LogEntry = {
  id: string;
  line_no: number;
  timestamp: string | null;
  level: string;
  logger: string;
  category: string;
  message: string;
  raw: string;
  source: string;
  count?: number;
  detail_lines?: string[];
  root_cause?: string;
  grouped?: boolean;
};

export type LogStatsResponse = {
  hours: number;
  by_level: Record<string, number>;
  by_category: Record<string, number>;
  by_source: Record<string, number>;
  recent_errors: LogEntry[];
  sources: LogSource[];
};

export type LogQueryParams = {
  source?: string;
  level?: string;
  category?: string;
  logger_prefix?: string;
  q?: string;
  limit?: number;
  group?: boolean;
};

function qs(params: Record<string, string | number | boolean | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    if (typeof v === "boolean") {
      if (v) q.set(k, "true");
      continue;
    }
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function loadLogSources(): Promise<LogSource[]> {
  const res = await apiFetch(`/api/logs/sources`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: LogSource[] };
  return data.items ?? [];
}

export async function loadLogStats(hours = 24): Promise<LogStatsResponse> {
  const res = await apiFetch(`/api/logs/stats${qs({ hours })}`);
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as LogStatsResponse;
}

export async function loadLogEntries(params: LogQueryParams): Promise<{
  items: LogEntry[];
  available: boolean;
  source: string;
}> {
  const res = await apiFetch(
    `/api/logs/entries${qs({
      source: params.source ?? "runtime",
      level: params.level && params.level !== "ALL" ? params.level : undefined,
      category: params.category && params.category !== "all" ? params.category : undefined,
      logger_prefix: params.logger_prefix,
      q: params.q,
      limit: params.limit ?? 200,
      group: params.group,
    })}`,
  );
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as {
    items: LogEntry[];
    available: boolean;
    source: string;
    total_matched?: number;
    grouped?: boolean;
  };
  return data;
}

export async function loadLogCategories(): Promise<Array<{ id: string; label: string }>> {
  const res = await apiFetch(`/api/logs/categories`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: Array<{ id: string; label: string }> };
  return data.items ?? [];
}
