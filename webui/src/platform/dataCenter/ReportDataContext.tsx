import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { InspectionWorkEntity } from "../types";
import {
  createReportPlanApi,
  uploadReportTemplateApi,
  deleteInspectionReportApi,
  deleteReportPlanApi,
  deleteReportTemplateApi,
  generateAdhocReportApi,
  generateReportFromPlanApi,
  loadReportBundle,
  patchInspectionReportApi,
  patchReportPlanApi,
  patchReportTemplateApi,
  publishInspectionReportApi,
  toggleReportPlanApi,
} from "./reportApi";
import {
  DEMO_DOCX_TEMPLATE_OUTLINE,
  emptyPlanDraft,
  formatTemplateFileSize,
  newPlanId,
  newTemplateId,
  nowStamp,
  type InspectionReport,
  type ReportGenerationPlan,
  type ReportStatus,
  type ReportTemplate,
} from "./reportPlanMock";

type PlanDraft = Omit<ReportGenerationPlan, "id" | "createdAt" | "updatedAt">;

type ReportDataContextValue = {
  loading: boolean;
  error: string | null;
  hasSubscription: boolean | null;
  worksCatalog: InspectionWorkEntity[];
  plans: ReportGenerationPlan[];
  reports: InspectionReport[];
  templates: ReportTemplate[];
  refresh: () => Promise<void>;
  createPlan: (draft: PlanDraft) => Promise<ReportGenerationPlan>;
  updatePlan: (id: string, draft: PlanDraft) => Promise<void>;
  deletePlan: (id: string) => Promise<void>;
  togglePlanEnabled: (id: string) => Promise<void>;
  generateFromPlan: (planId: string) => Promise<InspectionReport | null>;
  generateAdHoc: (input: {
    name: string;
    workIds: string[];
    contentPrompt: string;
    templateId?: string | null;
  }) => Promise<InspectionReport>;
  uploadTemplate: (file: File) => Promise<ReportTemplate>;
  updateTemplate: (
    id: string,
    patch: Partial<Pick<ReportTemplate, "name" | "filename" | "content" | "sizeLabel">>,
  ) => Promise<ReportTemplate>;
  deleteTemplate: (id: string) => Promise<void>;
  updateReport: (
    id: string,
    patch: Partial<Pick<InspectionReport, "title" | "summary" | "sections" | "fullText">>,
  ) => Promise<void>;
  publishReport: (id: string) => Promise<void>;
  deleteReport: (id: string) => Promise<void>;
};

const ReportDataContext = createContext<ReportDataContextValue | null>(null);

async function readTemplateOutline(file: File): Promise<string> {
  const ext = file.name.split(".").pop()?.toLowerCase();
  if (ext === "txt" || ext === "md") return file.text();
  if (ext === "docx" || ext === "doc") {
    return DEMO_DOCX_TEMPLATE_OUTLINE;
  }
  try {
    const text = await file.text();
    return text.trim() || DEMO_DOCX_TEMPLATE_OUTLINE;
  } catch {
    return DEMO_DOCX_TEMPLATE_OUTLINE;
  }
}

export function ReportDataProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasSubscription, setHasSubscription] = useState<boolean | null>(null);
  const [worksCatalog, setWorksCatalog] = useState<InspectionWorkEntity[]>([]);
  const [plans, setPlans] = useState<ReportGenerationPlan[]>([]);
  const [reports, setReports] = useState<InspectionReport[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const bundle = await loadReportBundle();
      setTemplates(bundle.templates);
      setPlans(bundle.plans);
      setReports(bundle.reports);
      setWorksCatalog(bundle.worksCatalog);
      setHasSubscription(bundle.hasSubscription);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载报告数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const createPlan = useCallback(async (draft: PlanDraft) => {
    const stamp = nowStamp();
    const local: ReportGenerationPlan = {
      id: newPlanId(),
      ...draft,
      workIds: [...draft.workIds],
      templateId: draft.templateId ?? null,
      createdAt: stamp,
      updatedAt: stamp,
    };
    const saved = await createReportPlanApi(local);
    setPlans((list) => [saved, ...list]);
    return saved;
  }, []);

  const updatePlan = useCallback(async (id: string, draft: PlanDraft) => {
    const existing = plans.find((p) => p.id === id);
    if (!existing) return;
    const next: ReportGenerationPlan = {
      ...existing,
      ...draft,
      workIds: [...draft.workIds],
      templateId: draft.templateId ?? null,
      updatedAt: nowStamp(),
    };
    const saved = await patchReportPlanApi(next);
    setPlans((list) => list.map((p) => (p.id === id ? saved : p)));
  }, [plans]);

  const deletePlan = useCallback(async (id: string) => {
    await deleteReportPlanApi(id);
    setPlans((list) => list.filter((p) => p.id !== id));
  }, []);

  const togglePlanEnabled = useCallback(async (id: string) => {
    const saved = await toggleReportPlanApi(id);
    setPlans((list) => list.map((p) => (p.id === id ? saved : p)));
  }, []);

  const generateFromPlan = useCallback(
    async (planId: string) => {
      const plan = plans.find((p) => p.id === planId);
      if (!plan) return null;
      const saved = await generateReportFromPlanApi(planId, "manual");
      setReports((list) => [saved, ...list]);
      return saved;
    },
    [plans],
  );

  const generateAdHoc = useCallback(
    async (input: {
      name: string;
      workIds: string[];
      contentPrompt: string;
      templateId?: string | null;
    }) => {
      const saved = await generateAdhocReportApi(input);
      setReports((list) => [saved, ...list]);
      return saved;
    },
    [],
  );

  const uploadTemplate = useCallback(async (file: File) => {
    const template = await uploadReportTemplateApi(file, {
      name: file.name.replace(/\.[^.]+$/, "") || file.name,
    });
    setTemplates((list) => [template, ...list]);
    return template;
  }, []);

  const updateTemplate = useCallback(
    async (
      id: string,
      patch: Partial<Pick<ReportTemplate, "name" | "filename" | "content" | "sizeLabel">>,
    ) => {
      const saved = await patchReportTemplateApi(id, patch);
      setTemplates((list) => list.map((t) => (t.id === id ? saved : t)));
      return saved;
    },
    [],
  );

  const deleteTemplate = useCallback(async (id: string) => {
    await deleteReportTemplateApi(id);
    setTemplates((list) => list.filter((t) => t.id !== id));
    setPlans((list) =>
      list.map((p) => (p.templateId === id ? { ...p, templateId: null, updatedAt: nowStamp() } : p)),
    );
  }, []);

  const updateReport = useCallback(
    async (id: string, patch: Partial<Pick<InspectionReport, "title" | "summary" | "sections" | "fullText">>) => {
      const saved = await patchInspectionReportApi(id, patch);
      setReports((list) => list.map((r) => (r.id === id ? saved : r)));
    },
    [],
  );

  const publishReport = useCallback(async (id: string) => {
    const saved = await publishInspectionReportApi(id);
    setReports((list) =>
      list.map((r) => (r.id === id ? saved : { ...r, status: "published" as ReportStatus, updatedAt: nowStamp() })),
    );
  }, []);

  const deleteReport = useCallback(async (id: string) => {
    await deleteInspectionReportApi(id);
    setReports((list) => list.filter((r) => r.id !== id));
  }, []);

  const value = useMemo(
    () => ({
      loading,
      error,
      hasSubscription,
      worksCatalog,
      plans,
      reports,
      templates,
      refresh,
      createPlan,
      updatePlan,
      deletePlan,
      togglePlanEnabled,
      generateFromPlan,
      generateAdHoc,
      uploadTemplate,
      updateTemplate,
      deleteTemplate,
      updateReport,
      publishReport,
      deleteReport,
    }),
    [
      loading,
      error,
      hasSubscription,
      worksCatalog,
      plans,
      reports,
      templates,
      refresh,
      createPlan,
      updatePlan,
      deletePlan,
      togglePlanEnabled,
      generateFromPlan,
      generateAdHoc,
      uploadTemplate,
      updateTemplate,
      deleteTemplate,
      updateReport,
      publishReport,
      deleteReport,
    ],
  );

  return <ReportDataContext.Provider value={value}>{children}</ReportDataContext.Provider>;
}

export function useReportData() {
  const ctx = useContext(ReportDataContext);
  if (!ctx) throw new Error("useReportData must be used within ReportDataProvider");
  return ctx;
}

export { emptyPlanDraft };
