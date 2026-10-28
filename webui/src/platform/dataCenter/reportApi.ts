import { readApiError, apiFetch, listInspectionWorks } from "../../api";
import { apiRowToInspectionWork } from "../inspectionWorkApi";
import { loadRegions, regionNameMap } from "../regionApi";
import type { InspectionWorkEntity } from "../types";
import type {
  InspectionReport,
  ReportContentSection,
  ReportGenerationPlan,
  ReportTemplate,
} from "./reportPlanMock";

export type ReportTemplateApiRow = {
  template_id: string;
  name: string;
  description: string;
  filename: string;
  content: string;
  storage_relpath: string;
  uploaded_at: string;
  size_label: string;
  created_at: string;
  updated_at: string;
  bound_work_count?: number;
};

export type ReportPlanApiRow = {
  plan_id: string;
  name: string;
  enabled: boolean;
  frequency: string;
  work_ids: string[];
  content_prompt: string;
  template_id: string | null;
  weekday: number | null;
  month_day: number | null;
  generate_time: string;
  created_at: string;
  updated_at: string;
};

export type InspectionReportApiRow = {
  report_id: string;
  plan_id: string | null;
  plan_name: string | null;
  title: string;
  period: string;
  frequency: string;
  work_ids: string[];
  status: string;
  source: string;
  content_prompt: string;
  template_id: string | null;
  template_name: string | null;
  summary: string;
  sections: ReportContentSection[];
  full_text: string;
  created_at: string;
  updated_at: string;
};

function apiBase() {
  return import.meta.env.DEV ? "" : ".";
}

function formatStamp(raw: string): string {
  const s = (raw || "").trim();
  if (!s) return new Date().toISOString().slice(0, 16).replace("T", " ");
  if (s.includes("T")) return s.slice(0, 16).replace("T", " ");
  return s.slice(0, 16);
}

export function apiRowToReportTemplate(row: ReportTemplateApiRow): ReportTemplate {
  return {
    id: row.template_id,
    name: row.name,
    description: row.description || "",
    filename: row.filename,
    content: row.content || "",
    storageRelpath: row.storage_relpath || "",
    uploadedAt: formatStamp(row.uploaded_at),
    sizeLabel: row.size_label,
    boundWorkCount: row.bound_work_count ?? 0,
  };
}

export function apiRowToReportPlan(row: ReportPlanApiRow): ReportGenerationPlan {
  const freq = row.frequency;
  const frequency =
    freq === "daily" || freq === "weekly" || freq === "monthly" ? freq : "daily";
  return {
    id: row.plan_id,
    name: row.name,
    enabled: row.enabled,
    frequency,
    workIds: [...row.work_ids],
    contentPrompt: row.content_prompt,
    templateId: row.template_id,
    weekday: row.weekday ?? undefined,
    monthDay: row.month_day ?? undefined,
    generateTime: row.generate_time || "08:00",
    createdAt: formatStamp(row.created_at),
    updatedAt: formatStamp(row.updated_at),
  };
}

export function apiRowToInspectionReport(row: InspectionReportApiRow): InspectionReport {
  const freq = row.frequency;
  const frequency =
    freq === "daily" || freq === "weekly" || freq === "monthly" || freq === "adhoc"
      ? freq
      : "weekly";
  const status = row.status === "published" ? "published" : "draft";
  const source = row.source === "scheduled" ? "scheduled" : "manual";
  return {
    id: row.report_id,
    planId: row.plan_id,
    planName: row.plan_name,
    title: row.title,
    period: row.period,
    frequency,
    workIds: [...row.work_ids],
    status,
    source,
    contentPrompt: row.content_prompt,
    templateId: row.template_id,
    templateName: row.template_name,
    summary: row.summary,
    sections: row.sections.map((s) => ({ ...s })),
    fullText: row.full_text,
    createdAt: formatStamp(row.created_at),
    updatedAt: formatStamp(row.updated_at),
  };
}

export function reportPlanToCreateBody(plan: ReportGenerationPlan): Record<string, unknown> {
  return {
    plan_id: plan.id,
    name: plan.name,
    enabled: plan.enabled,
    frequency: plan.frequency,
    work_ids: plan.workIds,
    content_prompt: plan.contentPrompt,
    template_id: plan.templateId,
    weekday: plan.weekday ?? null,
    month_day: plan.monthDay ?? null,
    generate_time: plan.generateTime,
  };
}

export function reportPlanToPatchBody(plan: ReportGenerationPlan): Record<string, unknown> {
  return reportPlanToCreateBody(plan);
}

export function inspectionReportToCreateBody(report: InspectionReport): Record<string, unknown> {
  return {
    report_id: report.id,
    title: report.title,
    period: report.period,
    frequency: report.frequency,
    work_ids: report.workIds,
    status: report.status,
    source: report.source,
    content_prompt: report.contentPrompt,
    plan_id: report.planId,
    plan_name: report.planName,
    template_id: report.templateId,
    template_name: report.templateName,
    summary: report.summary,
    sections: report.sections,
    full_text: report.fullText,
  };
}

async function trySeedBuiltinReports(): Promise<void> {
  try {
    const res = await apiFetch(`${apiBase()}/api/inspection-reports/?limit=1`);
    if (!res.ok) return;
    const body = (await res.json()) as { total: number };
    if (body.total > 0) return;
    const seed = await apiFetch(`${apiBase()}/api/inspection-reports/seed/builtin`, { method: "POST" });
    if (!seed.ok) return;
  } catch {
    // 演示数据导入失败不应阻断模版/报告列表加载
  }
}

export async function loadReportTemplates(): Promise<ReportTemplate[]> {
  const res = await apiFetch(`${apiBase()}/api/report-templates/?limit=200`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: ReportTemplateApiRow[] };
  return data.items.map(apiRowToReportTemplate);
}

export async function loadReportPlans(): Promise<ReportGenerationPlan[]> {
  await trySeedBuiltinReports();
  const res = await apiFetch(`${apiBase()}/api/report-plans/?limit=200`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as { items: ReportPlanApiRow[] };
  return data.items.map(apiRowToReportPlan);
}

export async function loadInspectionReports(opts?: {
  subscribedOnly?: boolean;
}): Promise<{ reports: InspectionReport[]; hasSubscription: boolean | null }> {
  await trySeedBuiltinReports();
  const q = opts?.subscribedOnly ? "?limit=200&subscribed_only=1" : "?limit=200";
  const res = await apiFetch(`${apiBase()}/api/inspection-reports/${q}`);
  if (!res.ok) throw new Error(await readApiError(res));
  const data = (await res.json()) as {
    items: InspectionReportApiRow[];
    has_subscription?: boolean;
  };
  return {
    reports: data.items.map(apiRowToInspectionReport),
    hasSubscription:
      typeof data.has_subscription === "boolean" ? data.has_subscription : null,
  };
}

export async function loadInspectionWorksCatalog(): Promise<InspectionWorkEntity[]> {
  const regions = await loadRegions();
  const names = regionNameMap(regions);
  const worksRes = await listInspectionWorks(undefined, 200);
  if (!worksRes.ok) throw new Error(await readApiError(worksRes));
  const worksBody = (await worksRes.json()) as { items: Record<string, unknown>[] };
  return worksBody.items.map((row) => {
    const w = apiRowToInspectionWork(row);
    if (!w.region_name && w.region_id) {
      w.region_name = names[w.region_id] || w.region_id;
    }
    return w;
  });
}

export async function loadReportBundle(): Promise<{
  templates: ReportTemplate[];
  plans: ReportGenerationPlan[];
  reports: InspectionReport[];
  worksCatalog: InspectionWorkEntity[];
  hasSubscription: boolean | null;
}> {
  await trySeedBuiltinReports();
  const [templates, plans, reportLoad, worksCatalog] = await Promise.all([
    loadReportTemplates(),
    loadReportPlans(),
    loadInspectionReports({ subscribedOnly: true }),
    loadInspectionWorksCatalog(),
  ]);
  return {
    templates,
    plans,
    reports: reportLoad.reports,
    worksCatalog,
    hasSubscription: reportLoad.hasSubscription,
  };
}

export async function createReportPlanApi(plan: ReportGenerationPlan): Promise<ReportGenerationPlan> {
  const res = await apiFetch(`${apiBase()}/api/report-plans/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reportPlanToCreateBody(plan)),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToReportPlan((await res.json()) as ReportPlanApiRow);
}

export async function patchReportPlanApi(plan: ReportGenerationPlan): Promise<ReportGenerationPlan> {
  const res = await apiFetch(`${apiBase()}/api/report-plans/${encodeURIComponent(plan.id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reportPlanToPatchBody(plan)),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToReportPlan((await res.json()) as ReportPlanApiRow);
}

export async function toggleReportPlanApi(planId: string): Promise<ReportGenerationPlan> {
  const res = await apiFetch(`${apiBase()}/api/report-plans/${encodeURIComponent(planId)}/toggle`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToReportPlan((await res.json()) as ReportPlanApiRow);
}

export async function deleteReportPlanApi(planId: string): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/report-plans/${encodeURIComponent(planId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readApiError(res));
}

export async function createReportTemplateApi(input: {
  template_id?: string;
  name: string;
  description?: string;
  filename: string;
  content: string;
  size_label: string;
}): Promise<ReportTemplate> {
  const res = await apiFetch(`${apiBase()}/api/report-templates/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToReportTemplate((await res.json()) as ReportTemplateApiRow);
}

export async function uploadReportTemplateApi(
  file: File,
  options?: { name?: string; description?: string },
): Promise<ReportTemplate> {
  const form = new FormData();
  form.append("file", file);
  const params = new URLSearchParams();
  if (options?.name?.trim()) params.set("name", options.name.trim());
  if (options?.description?.trim()) params.set("description", options.description.trim());
  const q = params.toString();
  const res = await apiFetch(`${apiBase()}/api/report-templates/upload${q ? `?${q}` : ""}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToReportTemplate((await res.json()) as ReportTemplateApiRow);
}

export async function patchReportTemplateApi(
  templateId: string,
  patch: Partial<
    Pick<ReportTemplate, "name" | "description" | "filename" | "content" | "sizeLabel">
  >,
): Promise<ReportTemplate> {
  const body: Record<string, unknown> = {};
  if (patch.name != null) body.name = patch.name;
  if (patch.description != null) body.description = patch.description;
  if (patch.filename != null) body.filename = patch.filename;
  if (patch.content != null) body.content = patch.content;
  if (patch.sizeLabel != null) body.size_label = patch.sizeLabel;
  const res = await apiFetch(`${apiBase()}/api/report-templates/${encodeURIComponent(templateId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToReportTemplate((await res.json()) as ReportTemplateApiRow);
}

export async function deleteReportTemplateApi(templateId: string): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/report-templates/${encodeURIComponent(templateId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readApiError(res));
}

export async function generateReportFromPlanApi(planId: string, source: "manual" | "scheduled" = "manual"): Promise<InspectionReport> {
  const q = source === "scheduled" ? "?source=scheduled" : "";
  const res = await apiFetch(`${apiBase()}/api/report-plans/${encodeURIComponent(planId)}/generate${q}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToInspectionReport((await res.json()) as InspectionReportApiRow);
}

export async function generateAdhocReportApi(input: {
  name: string;
  workIds: string[];
  contentPrompt: string;
  templateId?: string | null;
}): Promise<InspectionReport> {
  const res = await apiFetch(`${apiBase()}/api/inspection-reports/generate-adhoc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      work_ids: input.workIds,
      content_prompt: input.contentPrompt,
      template_id: input.templateId ?? null,
    }),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToInspectionReport((await res.json()) as InspectionReportApiRow);
}

export async function createInspectionReportApi(report: InspectionReport): Promise<InspectionReport> {
  const res = await apiFetch(`${apiBase()}/api/inspection-reports/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inspectionReportToCreateBody(report)),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToInspectionReport((await res.json()) as InspectionReportApiRow);
}

export async function patchInspectionReportApi(
  reportId: string,
  patch: Partial<
    Pick<
      InspectionReport,
      "title" | "period" | "summary" | "sections" | "fullText" | "status"
    >
  >,
): Promise<InspectionReport> {
  const body: Record<string, unknown> = {};
  if (patch.title != null) body.title = patch.title;
  if (patch.period != null) body.period = patch.period;
  if (patch.summary != null) body.summary = patch.summary;
  if (patch.sections != null) body.sections = patch.sections;
  if (patch.fullText != null) body.full_text = patch.fullText;
  if (patch.status != null) body.status = patch.status;
  const res = await apiFetch(`${apiBase()}/api/inspection-reports/${encodeURIComponent(reportId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToInspectionReport((await res.json()) as InspectionReportApiRow);
}

export async function publishInspectionReportApi(reportId: string): Promise<InspectionReport> {
  const res = await apiFetch(`${apiBase()}/api/inspection-reports/${encodeURIComponent(reportId)}/publish`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return apiRowToInspectionReport((await res.json()) as InspectionReportApiRow);
}

/** 下架：改回 draft，用户端不再展示 */
export async function unpublishInspectionReportApi(reportId: string): Promise<InspectionReport> {
  return patchInspectionReportApi(reportId, { status: "draft" });
}

export async function deleteInspectionReportApi(reportId: string): Promise<void> {
  const res = await apiFetch(`${apiBase()}/api/inspection-reports/${encodeURIComponent(reportId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readApiError(res));
}
