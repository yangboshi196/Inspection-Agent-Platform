import { readApiError, apiFetch } from "../../api";
import type { ReportTemplateApiRow } from "../dataCenter/reportApi";
import { apiRowToReportTemplate } from "../dataCenter/reportApi";
import type { ReportTemplate } from "../dataCenter/reportPlanMock";

export type { ReportTemplate };

export type WorkReportTemplateBinding = {
  work_id: string;
  enabled: boolean;
  template_id: string;
  template: ReportTemplate | null;
  template_name: string;
  filename: string;
  storage_relpath: string;
  storage_dir: string;
  content: string;
  created_at: string;
  updated_at: string;
};

function apiBase() {
  return import.meta.env.DEV ? "" : ".";
}

function mapBinding(row: Record<string, unknown>): WorkReportTemplateBinding {
  const tplRaw = row.template;
  const template =
    tplRaw && typeof tplRaw === "object"
      ? apiRowToReportTemplate(tplRaw as ReportTemplateApiRow)
      : null;
  return {
    work_id: String(row.work_id ?? ""),
    enabled: Boolean(row.enabled),
    template_id: String(row.template_id ?? ""),
    template,
    template_name: String(row.template_name ?? template?.name ?? ""),
    filename: String(row.filename ?? template?.filename ?? ""),
    storage_relpath: String(row.storage_relpath ?? template?.storageRelpath ?? ""),
    storage_dir: String(row.storage_dir ?? ""),
    content: String(row.content ?? template?.content ?? ""),
    created_at: String(row.created_at ?? ""),
    updated_at: String(row.updated_at ?? ""),
  };
}

export async function listWorkReportTemplateBindings(): Promise<WorkReportTemplateBinding[]> {
  const res = await apiFetch(`${apiBase()}/api/work-report-template-bindings/`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: Record<string, unknown>[] };
  return (data.items ?? []).map(mapBinding);
}

export async function getWorkReportTemplateBinding(
  workId: string,
): Promise<WorkReportTemplateBinding | null> {
  const res = await apiFetch(
    `${apiBase()}/api/work-report-template-bindings/${encodeURIComponent(workId)}`,
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await readApiError(res));
  const row = (await res.json()) as Record<string, unknown>;
  return mapBinding(row);
}

/** 保存单条业务绑定；templateId 为空则清除绑定。返回落库后的绑定，清除时返回 null。 */
export async function saveWorkReportTemplateBinding(
  workId: string,
  templateId: string | null,
): Promise<WorkReportTemplateBinding | null> {
  const res = await apiFetch(
    `${apiBase()}/api/work-report-template-bindings/${encodeURIComponent(workId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: templateId?.trim() || null }),
    },
  );
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as Record<string, unknown>;
  if (data.cleared === true) return null;
  return mapBinding(data);
}

export async function uploadWorkReportTemplateBinding(
  file: File,
  workIds: string[],
  options?: { name?: string; description?: string },
): Promise<WorkReportTemplateBinding[]> {
  const form = new FormData();
  form.append("file", file);
  form.append("work_ids", JSON.stringify(workIds));
  if (options?.name?.trim()) form.append("name", options.name.trim());
  if (options?.description?.trim()) form.append("description", options.description.trim());
  const res = await apiFetch(`${apiBase()}/api/work-report-template-bindings/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: Record<string, unknown>[] };
  return (data.items ?? []).map(mapBinding);
}

export async function bindWorkReportTemplate(
  workIds: string[],
  templateId: string,
  enabled = true,
): Promise<WorkReportTemplateBinding[]> {
  const res = await apiFetch(`${apiBase()}/api/work-report-template-bindings/bind`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ work_ids: workIds, template_id: templateId, enabled }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: Record<string, unknown>[] };
  return (data.items ?? []).map(mapBinding);
}

export async function setWorkReportTemplateBindingEnabled(
  workIds: string[],
  enabled: boolean,
): Promise<WorkReportTemplateBinding[]> {
  const res = await apiFetch(`${apiBase()}/api/work-report-template-bindings/enabled`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ work_ids: workIds, enabled }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: Record<string, unknown>[] };
  return (data.items ?? []).map(mapBinding);
}
