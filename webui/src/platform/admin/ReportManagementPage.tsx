import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Badge } from "../components/Badge";
import {
  deleteInspectionReportApi,
  deleteReportTemplateApi,
  loadInspectionReports,
  loadReportTemplates,
  patchInspectionReportApi,
  patchReportTemplateApi,
  publishInspectionReportApi,
  unpublishInspectionReportApi,
  uploadReportTemplateApi,
} from "../dataCenter/reportApi";
import {
  frequencyLabel,
  parseTemplateSectionTitles,
  reportFullText,
  type InspectionReport,
  type ReportTemplate,
} from "../dataCenter/reportPlanMock";
import { exportReportPdf } from "../dataCenter/reportPdfExport";
import { MarkdownBody } from "../../MarkdownBody";

type AdminTab = "templates" | "reports";
type ContentViewMode = "edit" | "preview";
type ReportFreqFilter = "all" | InspectionReport["frequency"];
type ReportStatusFilter = "all" | InspectionReport["status"];

const FREQ_FILTERS: { id: ReportFreqFilter; label: string }[] = [
  { id: "all", label: "全部" },
  { id: "daily", label: "日报" },
  { id: "weekly", label: "周报" },
  { id: "monthly", label: "月报" },
  { id: "adhoc", label: "临时" },
];

const STATUS_FILTERS: { id: ReportStatusFilter; label: string }[] = [
  { id: "all", label: "全部" },
  { id: "published", label: "已发布" },
  { id: "draft", label: "草稿" },
];

export function ReportManagementPage() {
  const templateInputRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState<AdminTab>("templates");
  const [loading, setLoading] = useState(true);
  const [hint, setHint] = useState("");

  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [reports, setReports] = useState<InspectionReport[]>([]);

  const [templateKw, setTemplateKw] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [templateNameDraft, setTemplateNameDraft] = useState("");
  const [templateDescDraft, setTemplateDescDraft] = useState("");
  const [templateContentDraft, setTemplateContentDraft] = useState("");
  const [templateContentMode, setTemplateContentMode] = useState<ContentViewMode>("preview");
  const [savingTemplate, setSavingTemplate] = useState(false);

  const [reportKw, setReportKw] = useState("");
  const [reportFreq, setReportFreq] = useState<ReportFreqFilter>("all");
  const [reportStatus, setReportStatus] = useState<ReportStatusFilter>("all");
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [reportTitleDraft, setReportTitleDraft] = useState("");
  const [reportSummaryDraft, setReportSummaryDraft] = useState("");
  const [reportFullTextDraft, setReportFullTextDraft] = useState("");
  const [reportContentMode, setReportContentMode] = useState<ContentViewMode>("preview");
  const [savingReport, setSavingReport] = useState(false);
  const [publishingReport, setPublishingReport] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [tpl, rpt] = await Promise.all([
        loadReportTemplates(),
        loadInspectionReports().then((r) => r.reports),
      ]);
      setTemplates(tpl);
      setReports(rpt);
      setHint("");
    } catch (e) {
      setHint(e instanceof Error ? e.message : "加载报告数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const publishedCount = useMemo(
    () => reports.filter((r) => r.status === "published").length,
    [reports],
  );

  const filteredTemplates = useMemo(() => {
    const q = templateKw.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter((t) =>
      [t.name, t.filename, t.content, t.description].join(" ").toLowerCase().includes(q),
    );
  }, [templates, templateKw]);

  const selectedTemplate =
    filteredTemplates.find((t) => t.id === selectedTemplateId) ?? filteredTemplates[0] ?? null;

  useEffect(() => {
    if (tab !== "templates") return;
    if (selectedTemplateId && filteredTemplates.some((t) => t.id === selectedTemplateId)) return;
    setSelectedTemplateId(filteredTemplates[0]?.id ?? null);
  }, [tab, filteredTemplates, selectedTemplateId]);

  useEffect(() => {
    if (selectedTemplate) {
      setTemplateNameDraft(selectedTemplate.name);
      setTemplateDescDraft(selectedTemplate.description || "");
      setTemplateContentDraft(selectedTemplate.content || "");
      setTemplateContentMode("preview");
    } else {
      setTemplateNameDraft("");
      setTemplateDescDraft("");
      setTemplateContentDraft("");
      setTemplateContentMode("preview");
    }
  }, [selectedTemplate?.id, selectedTemplate?.name, selectedTemplate?.description, selectedTemplate?.content]);

  const filteredReports = useMemo(() => {
    let list = reports;
    if (reportFreq !== "all") list = list.filter((r) => r.frequency === reportFreq);
    if (reportStatus !== "all") list = list.filter((r) => r.status === reportStatus);
    const q = reportKw.trim().toLowerCase();
    if (q) {
      list = list.filter((r) =>
        [r.title, r.period, r.summary, r.planName ?? "", r.templateName ?? "", frequencyLabel(r.frequency)]
          .join(" ")
          .toLowerCase()
          .includes(q),
      );
    }
    return list;
  }, [reports, reportFreq, reportStatus, reportKw]);

  const selectedReport =
    filteredReports.find((r) => r.id === selectedReportId) ?? filteredReports[0] ?? null;

  const reportDirty =
    selectedReport != null &&
    (reportTitleDraft !== selectedReport.title ||
      reportSummaryDraft !== (selectedReport.summary || "") ||
      reportFullTextDraft !== reportFullText(selectedReport));

  useEffect(() => {
    if (tab !== "reports") return;
    if (selectedReportId && filteredReports.some((r) => r.id === selectedReportId)) return;
    setSelectedReportId(filteredReports[0]?.id ?? null);
  }, [tab, filteredReports, selectedReportId]);

  useEffect(() => {
    if (selectedReport) {
      setReportTitleDraft(selectedReport.title);
      setReportSummaryDraft(selectedReport.summary || "");
      setReportFullTextDraft(reportFullText(selectedReport));
      setReportContentMode("preview");
    } else {
      setReportTitleDraft("");
      setReportSummaryDraft("");
      setReportFullTextDraft("");
      setReportContentMode("preview");
    }
  }, [
    selectedReport?.id,
    selectedReport?.title,
    selectedReport?.summary,
    selectedReport?.fullText,
    selectedReport?.sections,
  ]);

  const handleTemplateUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const saved = await uploadReportTemplateApi(file, {
        name: file.name.replace(/\.[^.]+$/, "") || file.name,
      });
      setTemplates((list) => [saved, ...list]);
      setSelectedTemplateId(saved.id);
      setHint(`模版「${saved.name}」已上传`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "模版上传失败");
    }
  };

  const saveTemplate = async () => {
    if (!selectedTemplate) return;
    if (!templateNameDraft.trim()) {
      setHint("请填写模版名称");
      return;
    }
    setSavingTemplate(true);
    try {
      const saved = await patchReportTemplateApi(selectedTemplate.id, {
        name: templateNameDraft.trim(),
        description: templateDescDraft.trim(),
        content: templateContentDraft,
      });
      setTemplates((list) => list.map((t) => (t.id === saved.id ? saved : t)));
      setHint(`模版「${saved.name}」已保存`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "保存模版失败");
    } finally {
      setSavingTemplate(false);
    }
  };

  const removeTemplate = async (template: ReportTemplate) => {
    if (!window.confirm(`确定删除模版「${template.name}」？`)) return;
    try {
      await deleteReportTemplateApi(template.id);
      setTemplates((list) => list.filter((t) => t.id !== template.id));
      if (selectedTemplateId === template.id) {
        setSelectedTemplateId(templates.find((t) => t.id !== template.id)?.id ?? null);
      }
      setHint(`模版「${template.name}」已删除`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "删除模版失败");
    }
  };

  const removeReport = async (report: InspectionReport) => {
    if (!window.confirm(`确定删除报告「${report.title}」？`)) return;
    try {
      await deleteInspectionReportApi(report.id);
      setReports((list) => list.filter((r) => r.id !== report.id));
      if (selectedReportId === report.id) {
        setSelectedReportId(reports.find((r) => r.id !== report.id)?.id ?? null);
      }
      setHint(`报告「${report.title}」已删除`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "删除报告失败");
    }
  };

  const copyReportText = async () => {
    if (!selectedReport) return;
    try {
      await navigator.clipboard.writeText(reportFullTextDraft || reportFullText(selectedReport));
      setHint("报告全文已复制");
    } catch {
      setHint("复制失败");
    }
  };

  const saveReport = async () => {
    if (!selectedReport) return;
    if (!reportTitleDraft.trim()) {
      setHint("请填写报告标题");
      return;
    }
    setSavingReport(true);
    try {
      const saved = await patchInspectionReportApi(selectedReport.id, {
        title: reportTitleDraft.trim(),
        summary: reportSummaryDraft,
        fullText: reportFullTextDraft,
      });
      setReports((list) => list.map((r) => (r.id === saved.id ? saved : r)));
      setHint(`报告「${saved.title}」已保存`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "保存报告失败");
    } finally {
      setSavingReport(false);
    }
  };

  const publishReport = async () => {
    if (!selectedReport || publishingReport) return;
    if (reportDirty) {
      setHint("请先保存修改后再发布");
      return;
    }
    setPublishingReport(true);
    try {
      const saved = await publishInspectionReportApi(selectedReport.id);
      setReports((list) => list.map((r) => (r.id === saved.id ? saved : r)));
      setHint(`报告「${saved.title}」已发布`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "发布失败");
    } finally {
      setPublishingReport(false);
    }
  };

  const unpublishReport = async () => {
    if (!selectedReport || publishingReport) return;
    setPublishingReport(true);
    try {
      const saved = await unpublishInspectionReportApi(selectedReport.id);
      setReports((list) => list.map((r) => (r.id === saved.id ? saved : r)));
      setHint(`报告「${saved.title}」已下架`);
    } catch (e) {
      setHint(e instanceof Error ? e.message : "下架失败");
    } finally {
      setPublishingReport(false);
    }
  };

  const downloadReportPdf = async () => {
    if (!selectedReport || exportingPdf) return;
    setExportingPdf(true);
    try {
      const text = reportFullTextDraft || reportFullText(selectedReport);
      await exportReportPdf(selectedReport.title, text);
      setHint(`已导出「${selectedReport.title}.pdf」`);
    } catch {
      setHint("PDF 导出失败");
    } finally {
      setExportingPdf(false);
    }
  };

  const templateSectionTitles = selectedTemplate
    ? parseTemplateSectionTitles(templateContentDraft)
    : [];

  const templateDirty =
    selectedTemplate != null &&
    (templateNameDraft !== selectedTemplate.name ||
      templateDescDraft !== (selectedTemplate.description || "") ||
      templateContentDraft !== (selectedTemplate.content || ""));

  return (
    <div className="pf-scroll pf-algo-page pf-report-page">
      <header className="pf-report-top-bar">
        <div className="pf-report-title-block">
          <span className="pf-report-title-mark" aria-hidden>
            ▤
          </span>
          <div className="pf-report-title-text">
            <h1>报告管理</h1>
            <p className="pf-report-subtitle">维护报告模版与巡检报告；用户端仅展示已推送的报告</p>
          </div>
        </div>
        <nav className="pf-report-segments" aria-label="报告管理视图">
          <button
            type="button"
            className={`pf-report-segment${tab === "templates" ? " is-active" : ""}`}
            onClick={() => setTab("templates")}
          >
            报告模版
            <span>{templates.length}</span>
          </button>
          <button
            type="button"
            className={`pf-report-segment${tab === "reports" ? " is-active" : ""}`}
            onClick={() => setTab("reports")}
          >
            巡检报告
            <span>{reports.length}</span>
            {publishedCount > 0 ? (
              <em className="pf-report-segment-meta">{publishedCount} 已发布</em>
            ) : null}
          </button>
        </nav>
      </header>

      {hint ? <div className="pf-algo-status">{hint}</div> : null}

      <div className="pf-algo-layout pf-report-layout">
        <section className="pf-panel pf-algo-list-panel">
          {tab === "templates" ? (
            <>
              <div className="pf-algo-panel-head pf-algo-panel-head-stacked pf-report-template-list-head">
                <div className="pf-algo-panel-head pf-algo-panel-head-inline pf-report-template-list-toolbar">
                  <h2 className="pf-algo-section-title">模版库 ({filteredTemplates.length})</h2>
                  <div className="pf-algo-toolbar">
                    <input
                      ref={templateInputRef}
                      type="file"
                      accept=".txt,.md,.doc,.docx"
                      className="pf-hidden-file-input"
                      onChange={handleTemplateUpload}
                    />
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm pf-btn-primary"
                      onClick={() => templateInputRef.current?.click()}
                    >
                      上传模版
                    </button>
                  </div>
                </div>
                <input
                  type="search"
                  className="pf-cell-input pf-algo-search pf-algo-search-full"
                  placeholder="搜索名称、说明、文件名…"
                  value={templateKw}
                  onChange={(e) => setTemplateKw(e.target.value)}
                />
                <p className="pf-report-template-list-hint">模版定义报告结构；业务绑定在「巡检业务 → 报告模板绑定」中配置。</p>
              </div>
              <div className="pf-algo-list pf-report-template-list">
                {loading ? (
                  <p className="pf-algo-list-empty">加载中…</p>
                ) : filteredTemplates.length === 0 ? (
                  <div className="pf-report-template-empty">
                    <p>暂无报告模版</p>
                    <span>支持 .txt / .md / .doc / .docx，上传后可在右侧编辑正文</span>
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm pf-btn-primary"
                      onClick={() => templateInputRef.current?.click()}
                    >
                      上传第一份模版
                    </button>
                  </div>
                ) : (
                  filteredTemplates.map((t) => {
                    const sectionCount = parseTemplateSectionTitles(t.content).length;
                    return (
                      <button
                        key={t.id}
                        type="button"
                        className={`pf-algo-list-item pf-report-template-item${selectedTemplate?.id === t.id ? " is-active" : ""}`}
                        onClick={() => setSelectedTemplateId(t.id)}
                      >
                        <div className="pf-algo-list-item-top">
                          <strong>{t.name}</strong>
                          <span
                            className={`pf-report-template-bound${t.boundWorkCount > 0 ? " is-on" : ""}`}
                          >
                            {t.boundWorkCount > 0 ? `${t.boundWorkCount} 业务` : "未绑定"}
                          </span>
                        </div>
                        {t.description ? (
                          <p className="pf-report-template-list-desc">{t.description}</p>
                        ) : null}
                        <p className="pf-report-template-list-file">{t.filename || "手工模版"}</p>
                        <div className="pf-algo-list-item-meta">
                          <span>{sectionCount > 0 ? `${sectionCount} 个章节` : "无章节标题"}</span>
                          <span>{t.sizeLabel || "—"}</span>
                          <span>{t.uploadedAt}</span>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </>
          ) : (
            <>
              <div className="pf-algo-panel-head pf-algo-panel-head-stacked">
                <h2 className="pf-algo-section-title">报告列表 ({filteredReports.length})</h2>
                <input
                  type="search"
                  className="pf-cell-input pf-algo-search pf-algo-search-full"
                  placeholder="搜索标题、周期、摘要…"
                  value={reportKw}
                  onChange={(e) => setReportKw(e.target.value)}
                />
                <div className="pf-report-filter-block">
                  <span className="pf-algo-section-title-sm">报告类型</span>
                  <div className="pf-algo-filter-row">
                    {FREQ_FILTERS.map((f) => (
                      <button
                        key={f.id}
                        type="button"
                        className={`pf-algo-filter-chip${reportFreq === f.id ? " is-active" : ""}`}
                        onClick={() => {
                          setReportFreq(f.id);
                          setSelectedReportId(null);
                        }}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="pf-report-filter-block">
                  <span className="pf-algo-section-title-sm">发布状态</span>
                  <div className="pf-algo-filter-row">
                    {STATUS_FILTERS.map((f) => (
                      <button
                        key={f.id}
                        type="button"
                        className={`pf-algo-filter-chip${reportStatus === f.id ? " is-active" : ""}`}
                        onClick={() => {
                          setReportStatus(f.id);
                          setSelectedReportId(null);
                        }}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="pf-algo-list">
                {loading ? (
                  <p className="pf-algo-list-empty">加载中…</p>
                ) : filteredReports.length === 0 ? (
                  <p className="pf-algo-list-empty">当前筛选下暂无报告</p>
                ) : (
                  filteredReports.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      className={`pf-algo-list-item${selectedReport?.id === r.id ? " is-active" : ""}`}
                      onClick={() => setSelectedReportId(r.id)}
                    >
                      <div className="pf-algo-list-item-top">
                        <strong>{r.title}</strong>
                        <div className="pf-report-list-badges">
                          <Badge tone="info">{frequencyLabel(r.frequency)}</Badge>
                          <Badge tone={r.status === "published" ? "success" : "default"}>
                            {r.status === "published" ? "已发布" : "草稿"}
                          </Badge>
                        </div>
                      </div>
                      <p>{r.period}</p>
                      <div className="pf-algo-list-item-meta">
                        <span>{r.planName ?? "系统推送"}</span>
                        <span>{r.updatedAt}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </section>

        <section className="pf-panel pf-algo-detail-panel">
          {tab === "templates" ? (
            selectedTemplate ? (
              <div className="pf-algo-detail-body pf-report-detail-body pf-report-template-detail">
                <div className="pf-algo-detail-head pf-report-template-detail-head">
                  <div>
                    <div className="pf-report-template-chips">
                      <span className="pf-report-template-chip">
                        {templateSectionTitles.length} 章节
                      </span>
                      <span
                        className={`pf-report-template-chip${selectedTemplate.boundWorkCount > 0 ? " is-accent" : ""}`}
                      >
                        {selectedTemplate.boundWorkCount > 0
                          ? `${selectedTemplate.boundWorkCount} 业务已绑定`
                          : "暂无业务绑定"}
                      </span>
                      <span className="pf-report-template-chip">{selectedTemplate.sizeLabel || "—"}</span>
                    </div>
                    <h2>{selectedTemplate.name}</h2>
                    <p className="pf-algo-detail-id pf-report-template-id">
                      {selectedTemplate.filename || "—"} · 更新 {selectedTemplate.uploadedAt}
                    </p>
                  </div>
                  <div className="pf-algo-detail-actions">
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm pf-btn-primary"
                      disabled={savingTemplate || !templateDirty}
                      onClick={() => void saveTemplate()}
                    >
                      {savingTemplate ? "保存中…" : templateDirty ? "保存更改" : "已保存"}
                    </button>
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm pf-btn-danger"
                      onClick={() => void removeTemplate(selectedTemplate)}
                    >
                      删除
                    </button>
                  </div>
                </div>

                {templateDirty ? (
                  <div className="pf-report-template-dirty-bar">有未保存的修改</div>
                ) : null}

                <div className="pf-report-template-edit-grid">
                  <div className="pf-report-template-form">
                    <label className="pf-algo-field">
                      <span>模版名称</span>
                      <input
                        className="pf-cell-input"
                        value={templateNameDraft}
                        onChange={(e) => setTemplateNameDraft(e.target.value)}
                      />
                    </label>

                    <label className="pf-algo-field">
                      <span>说明（可选）</span>
                      <input
                        className="pf-cell-input"
                        value={templateDescDraft}
                        onChange={(e) => setTemplateDescDraft(e.target.value)}
                        placeholder="例如：周报汇总、单次执行报告"
                      />
                    </label>

                    <div className="pf-algo-field pf-report-template-editor-field">
                      <div className="pf-report-template-content-head">
                        <span>模版正文</span>
                        <div className="pf-report-template-content-tabs" role="tablist" aria-label="正文视图">
                          <button
                            type="button"
                            role="tab"
                            aria-selected={templateContentMode === "preview"}
                            className={`pf-report-template-content-tab${templateContentMode === "preview" ? " is-active" : ""}`}
                            onClick={() => setTemplateContentMode("preview")}
                          >
                            预览
                          </button>
                          <button
                            type="button"
                            role="tab"
                            aria-selected={templateContentMode === "edit"}
                            className={`pf-report-template-content-tab${templateContentMode === "edit" ? " is-active" : ""}`}
                            onClick={() => setTemplateContentMode("edit")}
                          >
                            编辑
                          </button>
                        </div>
                      </div>
                      {templateContentMode === "edit" ? (
                        <textarea
                          className="pf-cell-textarea pf-algo-textarea pf-report-textarea pf-report-template-editor"
                          rows={16}
                          value={templateContentDraft}
                          onChange={(e) => setTemplateContentDraft(e.target.value)}
                          placeholder={"使用 Markdown 标题组织章节，例如：\n# 报告摘要\n# 规范\n# 巡检结果\n\n生成报告时将全文传给大模型。"}
                        />
                      ) : (
                        <div className="pf-report-template-md-preview">
                          {templateContentDraft.trim() ? (
                            <MarkdownBody
                              source={templateContentDraft}
                              className="markdown-body pf-report-template-md-body"
                            />
                          ) : (
                            <p className="pf-report-template-md-empty">暂无正文，切换到「编辑」开始编写</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <aside className="pf-report-template-aside">
                    <section className="pf-report-template-aside-card">
                      <h3 className="pf-algo-section-title-sm">章节结构</h3>
                      {templateSectionTitles.length > 0 ? (
                        <ol className="pf-report-template-section-list">
                          {templateSectionTitles.map((title, index) => (
                            <li key={`${index}-${title}`}>
                              <span>{index + 1}</span>
                              {title}
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <p className="pf-report-template-aside-empty">
                          使用 <code># 标题</code> 或编号列表定义章节，便于预览与生成。
                        </p>
                      )}
                    </section>
                    <section className="pf-report-template-aside-card pf-report-template-aside-tip">
                      <h3 className="pf-algo-section-title-sm">使用说明</h3>
                      <ul>
                        <li>正文即生成依据，请保持结构清晰、用语简洁。</li>
                        <li>多个业务可共用同一模版，在巡检业务工作室绑定。</li>
                        <li>支持重新上传文件覆盖，或在此直接编辑保存。</li>
                      </ul>
                    </section>
                  </aside>
                </div>
              </div>
            ) : (
              <div className="pf-algo-detail-empty pf-report-template-detail-empty">
                <p>请选择左侧模版，或上传新模版</p>
                <button
                  type="button"
                  className="pf-btn pf-btn-sm pf-btn-primary"
                  onClick={() => templateInputRef.current?.click()}
                >
                  上传模版
                </button>
              </div>
            )
          ) : selectedReport ? (
            <div className="pf-algo-detail-body pf-report-detail-body pf-report-inspection-detail">
              <div className="pf-algo-detail-head pf-report-template-detail-head">
                <div>
                  <div className="pf-report-list-badges pf-report-detail-badges">
                    <Badge tone="info">{frequencyLabel(selectedReport.frequency)}</Badge>
                    <Badge tone={selectedReport.status === "published" ? "success" : "default"}>
                      {selectedReport.status === "published" ? "已发布" : "草稿"}
                    </Badge>
                  </div>
                  <p className="pf-algo-detail-id pf-report-template-id">
                    {selectedReport.period || "—"} · 更新 {selectedReport.updatedAt}
                  </p>
                </div>
                <div className="pf-algo-detail-actions">
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm pf-btn-primary"
                    disabled={savingReport || !reportDirty}
                    onClick={() => void saveReport()}
                  >
                    {savingReport ? "保存中…" : reportDirty ? "保存更改" : "已保存"}
                  </button>
                  {selectedReport.status === "published" ? (
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm"
                      disabled={publishingReport}
                      onClick={() => void unpublishReport()}
                    >
                      {publishingReport ? "处理中…" : "下架"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="pf-btn pf-btn-sm"
                      disabled={publishingReport || reportDirty}
                      onClick={() => void publishReport()}
                    >
                      {publishingReport ? "发布中…" : "发布"}
                    </button>
                  )}
                  <button type="button" className="pf-btn pf-btn-sm" onClick={() => void copyReportText()}>
                    复制全文
                  </button>
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm"
                    disabled={exportingPdf}
                    onClick={() => void downloadReportPdf()}
                  >
                    {exportingPdf ? "导出中…" : "导出 PDF"}
                  </button>
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm pf-btn-danger"
                    onClick={() => void removeReport(selectedReport)}
                  >
                    删除
                  </button>
                </div>
              </div>

              {reportDirty ? <div className="pf-report-template-dirty-bar">有未保存的修改</div> : null}

              <label className="pf-algo-field">
                <span>报告标题</span>
                <input
                  className="pf-cell-input"
                  value={reportTitleDraft}
                  onChange={(e) => setReportTitleDraft(e.target.value)}
                />
              </label>

              <label className="pf-algo-field">
                <span>摘要</span>
                <textarea
                  className="pf-cell-textarea pf-algo-textarea"
                  rows={3}
                  value={reportSummaryDraft}
                  onChange={(e) => setReportSummaryDraft(e.target.value)}
                  placeholder="报告摘要"
                />
              </label>

              <div className="pf-algo-field pf-report-template-editor-field">
                <div className="pf-report-template-content-head">
                  <span>报告全文</span>
                  <div className="pf-report-template-content-tabs" role="tablist" aria-label="正文视图">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={reportContentMode === "preview"}
                      className={`pf-report-template-content-tab${reportContentMode === "preview" ? " is-active" : ""}`}
                      onClick={() => setReportContentMode("preview")}
                    >
                      预览
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={reportContentMode === "edit"}
                      className={`pf-report-template-content-tab${reportContentMode === "edit" ? " is-active" : ""}`}
                      onClick={() => setReportContentMode("edit")}
                    >
                      编辑
                    </button>
                  </div>
                </div>
                {reportContentMode === "edit" ? (
                  <textarea
                    className="pf-cell-textarea pf-algo-textarea pf-report-textarea pf-report-template-editor"
                    rows={16}
                    value={reportFullTextDraft}
                    onChange={(e) => setReportFullTextDraft(e.target.value)}
                    placeholder="支持 Markdown 格式"
                  />
                ) : (
                  <div className="pf-report-template-md-preview">
                    {reportFullTextDraft.trim() ? (
                      <MarkdownBody
                        source={reportFullTextDraft}
                        className="markdown-body pf-report-template-md-body"
                      />
                    ) : (
                      <p className="pf-report-template-md-empty">暂无正文，切换到「编辑」开始编写</p>
                    )}
                  </div>
                )}
              </div>

              <section className="pf-report-entity-card">
                <h3 className="pf-algo-section-title-sm">实体字段</h3>
                <dl className="pf-report-entity-dl">
                  <div>
                    <dt>report_id</dt>
                    <dd>{selectedReport.id}</dd>
                  </div>
                  <div>
                    <dt>status</dt>
                    <dd>{selectedReport.status}</dd>
                  </div>
                  <div>
                    <dt>frequency</dt>
                    <dd>{selectedReport.frequency}</dd>
                  </div>
                  <div>
                    <dt>source</dt>
                    <dd>{selectedReport.source}</dd>
                  </div>
                  <div>
                    <dt>period</dt>
                    <dd>{selectedReport.period || "—"}</dd>
                  </div>
                  <div>
                    <dt>plan_id</dt>
                    <dd>{selectedReport.planId || "—"}</dd>
                  </div>
                  <div>
                    <dt>plan_name</dt>
                    <dd>{selectedReport.planName || "—"}</dd>
                  </div>
                  <div>
                    <dt>template_id</dt>
                    <dd>{selectedReport.templateId || "—"}</dd>
                  </div>
                  <div>
                    <dt>template_name</dt>
                    <dd>{selectedReport.templateName || "—"}</dd>
                  </div>
                  <div>
                    <dt>work_ids</dt>
                    <dd>{selectedReport.workIds.length ? selectedReport.workIds.join(", ") : "—"}</dd>
                  </div>
                  <div>
                    <dt>sections</dt>
                    <dd>{selectedReport.sections.length} 段</dd>
                  </div>
                  <div>
                    <dt>content_prompt</dt>
                    <dd>{selectedReport.contentPrompt || "—"}</dd>
                  </div>
                  <div>
                    <dt>created_at</dt>
                    <dd>{selectedReport.createdAt}</dd>
                  </div>
                  <div>
                    <dt>updated_at</dt>
                    <dd>{selectedReport.updatedAt}</dd>
                  </div>
                </dl>
              </section>
            </div>
          ) : (
            <p className="pf-algo-detail-empty">请选择左侧报告查看详情</p>
          )}
        </section>
      </div>
    </div>
  );
}
