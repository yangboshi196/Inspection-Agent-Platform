import { MOCK_INSPECTION_WORKS } from "../mockData";
import { scheduleModeLabel } from "../inspectionWorkUtils";
import type { InspectionWorkEntity } from "../types";

export type ReportFrequency = "daily" | "weekly" | "monthly";
export type ReportStatus = "draft" | "published";
export type ReportSource = "scheduled" | "manual";

export const REPORT_CORE_SECTION_TITLES = ["规范", "巡检业务", "区域", "巡检结果"] as const;
export type ReportCoreSectionTitle = (typeof REPORT_CORE_SECTION_TITLES)[number];

export type ReportContentSection = {
  id: string;
  title: string;
  body: string;
  detail?: string;
};

export type ReportTemplate = {
  id: string;
  name: string;
  description: string;
  filename: string;
  content: string;
  storageRelpath: string;
  uploadedAt: string;
  sizeLabel: string;
  boundWorkCount: number;
};

export type ReportGenerationPlan = {
  id: string;
  name: string;
  enabled: boolean;
  frequency: ReportFrequency;
  workIds: string[];
  contentPrompt: string;
  templateId: string | null;
  weekday?: number;
  monthDay?: number;
  generateTime: string;
  createdAt: string;
  updatedAt: string;
};

export type InspectionReport = {
  id: string;
  planId: string | null;
  planName: string | null;
  title: string;
  period: string;
  frequency: ReportFrequency | "adhoc";
  workIds: string[];
  status: ReportStatus;
  source: ReportSource;
  contentPrompt: string;
  templateId: string | null;
  templateName: string | null;
  summary: string;
  sections: ReportContentSection[];
  fullText: string;
  createdAt: string;
  updatedAt: string;
};

export const DEFAULT_REPORT_NAMING_TEMPLATE = "{name}-{date}";

export const DEFAULT_CONTENT_PROMPT =
  "汇总报告周期内各巡检业务的规范对照、执行情况与巡检结果，按规范、巡检业务、区域、巡检结果四段输出，语言简洁，适合物业项目晨会汇报。";

export const REPORT_INTENT_EXAMPLES = [
  {
    id: "daily-hse",
    title: "日常物业服务汇总",
    text: "按规范、巡检业务、区域、巡检结果汇总各区域日常巡检，突出 PPE 与通道秩序告警及在办事项。",
  },
  {
    id: "weekly-meeting",
    title: "周例会材料",
    text: "列明本周对照规范与关联巡检业务，分区域说明执行结果与告警闭环，便于安全例会通报。",
  },
  {
    id: "compliance",
    title: "合规趋势分析",
    text: "对比各巡检业务合规率变化，在巡检结果中说明主要影响因素与已采取的整改措施。",
  },
  {
    id: "special",
    title: "专项排查结论",
    text: "针对专项排查巡检业务，说明对照规范、覆盖区域与最终巡检结果，给出后续保障建议。",
  },
] as const;

const DEMO_NOW = "2026-05-19";

function resolveWorks(workIds: string[], catalog?: InspectionWorkEntity[]): InspectionWorkEntity[] {
  const source = catalog ?? MOCK_INSPECTION_WORKS;
  return workIds
    .map((id) => source.find((w) => w.work_id === id))
    .filter((w): w is InspectionWorkEntity => w != null);
}

function uniqueRuleNames(works: InspectionWorkEntity[]) {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const work of works) {
    for (const rule of work.rule_set) {
      if (!seen.has(rule.rule_id)) {
        seen.add(rule.rule_id);
        names.push(rule.name);
      }
    }
  }
  return names;
}

function uniqueRegionNames(works: InspectionWorkEntity[]) {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const work of works) {
    if (!seen.has(work.region_id)) {
      seen.add(work.region_id);
      names.push(work.region_name);
    }
  }
  return names;
}

function demoExecutionCount(workCount: number, frequency: ReportFrequency | "adhoc") {
  if (frequency === "daily") return Math.max(workCount * 6, 6);
  if (frequency === "weekly") return Math.max(workCount * 16, 16);
  if (frequency === "monthly") return Math.max(workCount * 60, 60);
  return Math.max(workCount * 2, 2);
}

function coreSectionBody(
  title: ReportCoreSectionTitle,
  works: InspectionWorkEntity[],
  frequency: ReportFrequency | "adhoc",
  prompt: string,
) {
  const freq = frequencyLabel(frequency);
  const ruleNames = uniqueRuleNames(works);
  const regionNames = uniqueRegionNames(works);

  if (title === "规范") {
    if (!ruleNames.length) return "本报告未关联知识库规范条款。";
    return `共对照 ${ruleNames.length} 条规范：${ruleNames.join("、")}。`;
  }
  if (title === "巡检业务") {
    if (!works.length) return "未关联巡检业务。";
    return `${works.length} 条巡检业务：${works.map((w) => w.name).join("、")}。`;
  }
  if (title === "区域") {
    if (!regionNames.length) return "未覆盖现场区域。";
    return `覆盖 ${regionNames.length} 个区域：${regionNames.join("、")}。`;
  }

  const exec = demoExecutionCount(works.length, frequency);
  const promptHint = prompt.trim() ? ` ${prompt.trim().slice(0, 48)}${prompt.length > 48 ? "…" : ""}` : "";
  return `${freq}内 ${works.length || 0} 条巡检业务共执行巡检 ${exec} 次，综合合规率 89.2%；视频告警 3 起、传感异常 2 起，已关闭 2 起。${promptHint}`;
}

function coreSectionDetail(title: ReportCoreSectionTitle, works: InspectionWorkEntity[]) {
  if (!works.length) return undefined;

  if (title === "规范") {
    return works
      .map((w) => `· ${w.name}：${w.rule_set.map((r) => r.name).join("、") || "未绑定规范"}`)
      .join("\n");
  }
  if (title === "巡检业务") {
    return works
      .map((w) => {
        const schedule =
          w.schedule_mode === "periodic"
            ? w.schedule_interval ?? scheduleModeLabel(w.schedule_mode)
            : w.schedule_mode === "scheduled"
              ? w.schedule_times ?? scheduleModeLabel(w.schedule_mode)
              : scheduleModeLabel(w.schedule_mode);
        return `· ${w.name}（${schedule}）· ${w.algorithm_set.length} 个算法 · ${w.equipment_set.length} 个设备`;
      })
      .join("\n");
  }
  if (title === "区域") {
    return works.map((w) => `· ${w.region_name} ← ${w.name}`).join("\n");
  }
  return works
    .map((w) => {
      const algoHealth = w.algorithm_set.some((a) => a.health === "degraded") ? "部分算法降级" : "算法运行正常";
      return `· ${w.name}：合规率 91%，告警 1 起待跟进，${algoHealth}`;
    })
    .join("\n");
}

export function buildCoreReportSections(
  workIds: string[],
  frequency: ReportFrequency | "adhoc",
  prompt: string,
  worksCatalog?: InspectionWorkEntity[],
): ReportContentSection[] {
  const works = resolveWorks(workIds, worksCatalog);
  return REPORT_CORE_SECTION_TITLES.map((title) => ({
    id: sectionId(),
    title,
    body: coreSectionBody(title, works, frequency, prompt),
    detail: coreSectionDetail(title, works),
  }));
}

export function findReportSection(report: InspectionReport, title: ReportCoreSectionTitle) {
  return report.sections.find((section) => section.title === title) ?? null;
}

export function frequencyLabel(f: ReportFrequency | "adhoc") {
  if (f === "daily") return "日报";
  if (f === "weekly") return "周报";
  if (f === "monthly") return "月报";
  return "临时";
}

export function reportStatusLabel(s: ReportStatus) {
  return s === "published" ? "已发布" : "草稿";
}

export function reportStatusTone(s: ReportStatus): "success" | "draft" {
  return s === "published" ? "success" : "draft";
}

export function weekdayLabel(day: number) {
  return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day - 1] ?? `周${day}`;
}

export function periodForFrequency(frequency: ReportFrequency, refDate = DEMO_NOW) {
  const d = new Date(`${refDate}T12:00:00`);
  if (frequency === "daily") return refDate;
  if (frequency === "weekly") {
    const day = d.getDay() || 7;
    const mon = new Date(d);
    mon.setDate(d.getDate() - day + 1);
    const sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    const fmt = (x: Date) => x.toISOString().slice(0, 10);
    return `${fmt(mon)} — ${fmt(sun)}`;
  }
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const last = new Date(y, m, 0).getDate();
  return `${y}-${String(m).padStart(2, "0")}-01 — ${y}-${String(m).padStart(2, "0")}-${last}`;
}

export function applyNamingTemplate(
  template: string,
  ctx: { name: string; date: string; period: string; work: string },
) {
  return template
    .replace(/\{name\}/g, ctx.name)
    .replace(/\{date\}/g, ctx.date)
    .replace(/\{period\}/g, ctx.period)
    .replace(/\{work\}/g, ctx.work);
}

export function defaultReportTitle(name: string, refDate = DEMO_NOW) {
  return applyNamingTemplate(DEFAULT_REPORT_NAMING_TEMPLATE, {
    name,
    date: refDate,
    period: refDate,
    work: name,
  });
}

function sectionId() {
  return `sec-${Math.random().toString(36).slice(2, 9)}`;
}

export const DEMO_DOCX_TEMPLATE_OUTLINE = `# 报告摘要
# 排查范围与对象
# 检测方法与依据
# 发现问题
# 处置建议
# 结论与签署`;

export const INITIAL_REPORT_TEMPLATES: ReportTemplate[] = [
  {
    id: "tpl-pm-weekly",
    name: "物业运营周报模版",
    description: "",
    filename: "hse-weekly-template.md",
    content: `# 规范
## 对照条款清单

# 巡检业务
## 关联巡检业务

# 区域
## 覆盖区域范围

# 巡检结果
## 执行与告警汇总
## 合规结论`,
    storageRelpath: "",
    uploadedAt: "2026-05-01 10:00",
    sizeLabel: "2.1 KB",
    boundWorkCount: 0,
  },
];

export function newTemplateId() {
  return `tpl-${Date.now().toString(36)}`;
}

export function formatTemplateFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function parseTemplateSectionTitles(text: string): string[] {
  const titles: string[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const heading = line.match(/^#{1,3}\s+(.+)/);
    if (heading) {
      titles.push(heading[1]!);
      continue;
    }
    const numbered = line.match(/^\d+[.、)\]]\s*(.+)/);
    if (numbered) {
      titles.push(numbered[1]!);
      continue;
    }
    const cnNumbered = line.match(/^[一二三四五六七八九十]+[、.]\s*(.+)/);
    if (cnNumbered) {
      titles.push(cnNumbered[1]!);
      continue;
    }
    if (/[：:]$/.test(line)) titles.push(line.replace(/[：:]$/, ""));
  }
  return titles;
}

export function templateEffectiveContent(
  template?: Pick<ReportTemplate, "content"> | null,
): string {
  return (template?.content || "").trim();
}

export function generateReportSections(
  prompt: string,
  workIds: string[],
  frequency: ReportFrequency | "adhoc",
  templateContent?: string | null,
  worksCatalog?: InspectionWorkEntity[],
) {
  const sections = buildCoreReportSections(workIds, frequency, prompt, worksCatalog);
  const templateText = (templateContent || "").trim();
  if (!templateText) return sections;

  return sections.map((section) => {
    if (section.title !== "巡检结果") return section;
    const hint = templateText.length > 4000 ? `${templateText.slice(0, 3999)}…` : templateText;
    return {
      ...section,
      body: `${section.body}\n\n（参照报告模版）\n${hint}`,
    };
  });
}

export function generateReportSummary(
  workIds: string[],
  frequency: ReportFrequency | "adhoc",
  worksCatalog?: InspectionWorkEntity[],
) {
  const works = resolveWorks(workIds, worksCatalog);
  const regionNames = uniqueRegionNames(works);
  const ruleNames = uniqueRuleNames(works);
  const freq = frequencyLabel(frequency);
  const exec = demoExecutionCount(works.length, frequency);
  return `${freq}汇总：对照 ${ruleNames.length} 条规范，${works.length} 条巡检业务覆盖 ${regionNames.join("、") || "—"}；共执行 ${exec} 次，综合合规率 89.2%，待跟进告警 2 起。`;
}

export function composeReportFullText(
  report: Pick<
    InspectionReport,
    "title" | "period" | "updatedAt" | "planName" | "templateName" | "summary" | "sections"
  >,
): string {
  const lines = [
    report.title,
    `报告周期：${report.period}`,
    `生成时间：${report.updatedAt}`,
    report.planName ? `来源计划：${report.planName}` : "来源：临时生成",
    report.templateName ? `参照模版：${report.templateName}` : null,
    "",
    "—— 摘要 ——",
    report.summary,
    "",
  ].filter((line) => line !== null) as string[];

  for (const section of report.sections) {
    lines.push(`—— ${section.title} ——`);
    lines.push(section.body);
    if (section.detail) {
      lines.push("");
      lines.push(section.detail);
    }
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}

export function reportFullText(report: InspectionReport): string {
  return report.fullText || composeReportFullText(report);
}

export function emptyPlanDraft(): Omit<ReportGenerationPlan, "id" | "createdAt" | "updatedAt"> {
  return {
    name: "",
    enabled: true,
    frequency: "daily",
    workIds: [],
    contentPrompt: DEFAULT_CONTENT_PROMPT,
    templateId: null,
    generateTime: "08:00",
  };
}

export function newPlanId() {
  return `plan-${Date.now().toString(36)}`;
}

export function newReportId() {
  return `rep-${Date.now().toString(36)}`;
}

export function nowStamp() {
  return `${DEMO_NOW} ${String(new Date().getHours()).padStart(2, "0")}:${String(new Date().getMinutes()).padStart(2, "0")}`;
}

export const INITIAL_REPORT_PLANS: ReportGenerationPlan[] = [
  {
    id: "plan-daily",
    name: "日常安全巡检日报",
    enabled: true,
    frequency: "daily",
    workIds: ["iw-1", "iw-2"],
    contentPrompt: DEFAULT_CONTENT_PROMPT,
    templateId: null,
    generateTime: "08:00",
    createdAt: "2026-05-10 09:00",
    updatedAt: "2026-05-18 14:00",
  },
  {
    id: "plan-weekly",
    name: "安全运行周报",
    enabled: true,
    frequency: "weekly",
    workIds: ["iw-1", "iw-2", "iw-3"],
    contentPrompt:
      "汇总本周各巡检业务对照规范、区域覆盖与执行结果，突出需物业经理关注的异常项，按规范、巡检业务、区域、巡检结果输出。",
    templateId: "tpl-pm-weekly",
    weekday: 1,
    generateTime: "16:30",
    createdAt: "2026-05-01 10:00",
    updatedAt: "2026-05-18 16:30",
  },
  {
    id: "plan-monthly",
    name: "月度合规报告",
    enabled: false,
    frequency: "monthly",
    workIds: ["iw-1", "iw-2", "iw-3", "iw-4"],
    contentPrompt:
      "生成月度合规汇总，包含各巡检业务合规率变化、重大事件回顾、整改闭环与下月工作重点，语言正式适合归档。",
    templateId: null,
    monthDay: 1,
    generateTime: "09:00",
    createdAt: "2026-05-01 10:00",
    updatedAt: "2026-05-15 11:00",
  },
];

function seedInspectionReport(
  seed: Omit<InspectionReport, "fullText" | "sections" | "summary"> & { summary?: string },
): InspectionReport {
  const summary = seed.summary ?? generateReportSummary(seed.workIds, seed.frequency);
  const templateContent =
    seed.templateId != null
      ? (INITIAL_REPORT_TEMPLATES.find((t) => t.id === seed.templateId)?.content || null)
      : null;
  const sections = generateReportSections(seed.contentPrompt, seed.workIds, seed.frequency, templateContent);
  const base = { ...seed, summary, sections };
  return { ...base, fullText: composeReportFullText(base) };
}

export const INITIAL_INSPECTION_REPORTS: InspectionReport[] = [
  seedInspectionReport({
    id: "rep-w20",
    planId: "plan-weekly",
    planName: "安全运行周报",
    title: "安全运行周报-2026-05-19",
    period: "2026-05-12 — 2026-05-18",
    frequency: "weekly",
    workIds: ["iw-1", "iw-2", "iw-3"],
    status: "published",
    source: "scheduled",
    contentPrompt: INITIAL_REPORT_PLANS[1].contentPrompt,
    templateId: "tpl-pm-weekly",
    templateName: "物业运营周报模版",
    createdAt: "2026-05-18 16:30",
    updatedAt: "2026-05-18 16:30",
  }),
  seedInspectionReport({
    id: "rep-m05",
    planId: "plan-monthly",
    planName: "月度合规报告",
    title: "月度合规报告-2026-05-19",
    period: "2026-05-01 — 2026-05-31",
    frequency: "monthly",
    workIds: ["iw-1", "iw-2", "iw-3", "iw-4"],
    status: "draft",
    source: "scheduled",
    contentPrompt: INITIAL_REPORT_PLANS[2].contentPrompt,
    templateId: null,
    templateName: null,
    summary: "月度汇总编制中，当前已归集 19 日前的规范对照、巡检业务执行与区域覆盖数据。",
    createdAt: "2026-05-19 09:00",
    updatedAt: "2026-05-19 09:00",
  }),
  seedInspectionReport({
    id: "rep-adhoc-1",
    planId: null,
    planName: null,
    title: "重大活动前专项排查-2026-05-19",
    period: "2026-05-15 专项",
    frequency: "adhoc",
    workIds: ["iw-4"],
    status: "published",
    source: "manual",
    contentPrompt: "针对配电间开展活动前专项排查，输出规范对照、区域覆盖与排查结论。",
    templateId: null,
    templateName: null,
    summary: "配电间专项排查完成，对照规范与检测链路验证通过，巡检结果符合活动保障要求。",
    createdAt: "2026-05-15 18:00",
    updatedAt: "2026-05-15 18:00",
  }),
];

export function planStats(plans: ReportGenerationPlan[]) {
  return {
    total: plans.length,
    enabled: plans.filter((p) => p.enabled).length,
    daily: plans.filter((p) => p.frequency === "daily").length,
    weekly: plans.filter((p) => p.frequency === "weekly").length,
    monthly: plans.filter((p) => p.frequency === "monthly").length,
  };
}

export function inspectionReportStats(reports: InspectionReport[]) {
  return {
    total: reports.length,
    published: reports.filter((r) => r.status === "published").length,
    draft: reports.filter((r) => r.status === "draft").length,
  };
}

export function buildReportFromPlan(
  plan: ReportGenerationPlan,
  source: ReportSource = "scheduled",
  template?: ReportTemplate | null,
  worksCatalog?: InspectionWorkEntity[],
): InspectionReport {
  const period = periodForFrequency(plan.frequency);
  const title = defaultReportTitle(plan.name);

  const stamp = nowStamp();
  const templateContent = templateEffectiveContent(template);
  const templateId = template?.id ?? plan.templateId ?? null;
  const templateName = template?.name ?? null;
  const sections = generateReportSections(
    plan.contentPrompt,
    plan.workIds,
    plan.frequency,
    templateContent,
    worksCatalog,
  );
  const summary = generateReportSummary(plan.workIds, plan.frequency, worksCatalog);
  const base = {
    id: newReportId(),
    planId: plan.id,
    planName: plan.name,
    title,
    period,
    frequency: plan.frequency,
    workIds: [...plan.workIds],
    status: "draft" as ReportStatus,
    source,
    contentPrompt: plan.contentPrompt,
    templateId,
    templateName,
    summary,
    sections,
    createdAt: stamp,
    updatedAt: stamp,
  };
  return {
    ...base,
    fullText: composeReportFullText(base),
  };
}

export function buildAdHocReport(input: {
  name: string;
  workIds: string[];
  contentPrompt: string;
  templateId?: string | null;
  template?: ReportTemplate | null;
  worksCatalog?: InspectionWorkEntity[];
}): InspectionReport {
  const period = `${DEMO_NOW} 专项`;
  const title = defaultReportTitle(input.name);
  const stamp = nowStamp();
  const templateId = input.template?.id ?? input.templateId ?? null;
  const templateName = input.template?.name ?? null;
  const templateContent = templateEffectiveContent(input.template);
  const sections = generateReportSections(
    input.contentPrompt,
    input.workIds,
    "adhoc",
    templateContent,
    input.worksCatalog,
  );
  const summary = generateReportSummary(input.workIds, "adhoc", input.worksCatalog);
  const base = {
    id: newReportId(),
    planId: null,
    planName: null,
    title,
    period,
    frequency: "adhoc" as const,
    workIds: [...input.workIds],
    status: "draft" as ReportStatus,
    source: "manual" as ReportSource,
    contentPrompt: input.contentPrompt,
    templateId,
    templateName,
    summary,
    sections,
    createdAt: stamp,
    updatedAt: stamp,
  };
  return {
    ...base,
    fullText: composeReportFullText(base),
  };
}

export { MOCK_INSPECTION_WORKS };
