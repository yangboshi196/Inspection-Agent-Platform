import { useCallback, useEffect, useState } from "react";
import {
  getAlgorithmPage,
  getSpecStats,
  listDocuments,
  listKnowledgeDocuments,
  listSpecRules,
  patchRegion,
  postAlgorithmSeedBuiltin,
  postKnowledgeIngest,
  postRegion,
  postInspectionWorkGenerate,
  postSpecExtractPreflight,
  postSpecRulesExtract,
  readApiError,
  type SpecStats,
  uploadDocument,
} from "./api";

type StepId = 1 | 2 | 3 | 4 | 5;

type DocumentRow = {
  id: string;
  name: string;
  doc_type: string;
  created_at: string;
  ext?: string;
};

type SpecRule = {
  rule_id: string;
  name: string;
  desc: string;
  level: string;
  status: string;
  requirements: string;
};

type ExtractPreflight = {
  ready: boolean;
  kb_id: string;
  documents: Array<{
    doc_id: string;
    document_exists: boolean;
    file_present: boolean;
    vectorized: boolean;
    document_name: string;
    chunk_count: number;
    ok: boolean;
  }>;
  messages: string[];
};

type InspectionWork = {
  work_id: string;
  name: string;
  region_id: string;
  desc: string;
  rule_set: Array<{ rule_id: string; name: string; level?: string }>;
  algorithm_set: Array<{ algorithm_id: string; name: string; health?: string }>;
  equipment_set: Array<{ equipment_id: string; name: string; role?: string }>;
};

const STEPS: { id: StepId; title: string; hint: string }[] = [
  { id: 1, title: "区域", hint: "登记巡检区域 region_id" },
  { id: 2, title: "文档与向量化", hint: "先上传文档库，再选择向量化" },
  { id: 3, title: "规范提取", hint: "doc_ids 必填，仅从选定已向量化文档检索" },
  { id: 4, title: "算法目录", hint: "导入可匹配算法" },
  { id: 5, title: "巡检业务生成", hint: "规则 × 算法 → 巡检业务" },
];

function StepBadge({ n, active, done }: { n: number; active: boolean; done: boolean }) {
  const cls = done ? "wf-step-badge done" : active ? "wf-step-badge active" : "wf-step-badge";
  return <span className={cls}>{done ? "✓" : n}</span>;
}

export function SpecWorkflowDemoPage() {
  const [step, setStep] = useState<StepId>(1);
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState(false);

  const [regionId, setRegionId] = useState("demo-region-1");
  const [regionName, setRegionName] = useState("演示区域");

  const [kbId, setKbId] = useState("default");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("law");
  const [libraryDocs, setLibraryDocs] = useState<DocumentRow[]>([]);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [vectorizedIds, setVectorizedIds] = useState<Set<string>>(new Set());
  const [kbDocCount, setKbDocCount] = useState<number | null>(null);

  const [extractTopic, setExtractTopic] = useState("安全生产 现场管理 人员防护");
  const [extractMaxRules, setExtractMaxRules] = useState(10);
  const [extractPersist, setExtractPersist] = useState(true);
  const [extractReExtract, setExtractReExtract] = useState(false);
  const [extractPreflight, setExtractPreflight] = useState<ExtractPreflight | null>(null);
  const [rules, setRules] = useState<SpecRule[]>([]);

  const [algoCount, setAlgoCount] = useState<number | null>(null);

  const [maxWorks, setMaxWorks] = useState(8);
  const [workPersist, setWorkPersist] = useState(true);
  const [works, setWorks] = useState<InspectionWork[]>([]);
  const [specStats, setSpecStats] = useState<SpecStats | null>(null);

  const [doneSteps, setDoneSteps] = useState<Set<StepId>>(new Set());

  const markDone = (s: StepId) => setDoneSteps((prev) => new Set(prev).add(s));

  const loadRules = useCallback(async () => {
    const res = await listSpecRules();
    if (!res.ok) return;
    setRules((await res.json()) as SpecRule[]);
  }, []);

  const loadLibraryDocs = useCallback(async (preferId?: string) => {
    const res = await listDocuments({ limit: 100 });
    if (!res.ok) return;
    const rows = (await res.json()) as DocumentRow[];
    setLibraryDocs(rows);
    const pick = preferId || selectedDocId;
    if (rows.length === 0) {
      setSelectedDocId("");
    } else if (!pick || !rows.some((r) => r.id === pick)) {
      setSelectedDocId(rows[0].id);
    }
  }, [selectedDocId]);

  const loadKbStats = useCallback(async (kb: string) => {
    const docs = await listKnowledgeDocuments(kb);
    if (!docs.ok) return;
    const list = (await docs.json()) as Array<{ source_doc_id?: string; doc_id?: string }>;
    const ids = new Set<string>();
    for (const row of list) {
      const sid = (row.source_doc_id || row.doc_id || "").trim();
      if (sid) ids.add(sid);
    }
    setVectorizedIds(ids);
    setKbDocCount(list.length);
  }, []);

  const loadAlgoCount = useCallback(async () => {
    const res = await getAlgorithmPage(1);
    if (!res.ok) return;
    const j = (await res.json()) as { total?: number };
    setAlgoCount(typeof j.total === "number" ? j.total : null);
  }, []);

  useEffect(() => {
    void (async () => {
      const r = await getSpecStats();
      if (!r.ok) return;
      setSpecStats((await r.json()) as SpecStats);
    })();
  }, []);

  useEffect(() => {
    void loadAlgoCount();
  }, [loadAlgoCount]);

  useEffect(() => {
    if (step === 2) {
      void loadLibraryDocs();
      void loadKbStats(kbId);
    }
  }, [step, kbId, loadLibraryDocs, loadKbStats]);

  useEffect(() => {
    if (step === 3) {
      void loadLibraryDocs();
      void loadKbStats(kbId);
    }
  }, [step, kbId, loadLibraryDocs, loadKbStats]);

  const ensureRegion = async () => {
    const rid = regionId.trim();
    if (!rid) {
      setHint("请填写 region_id");
      return;
    }
    setBusy(true);
    setHint("");
    try {
      let res = await postRegion({ id: rid, name: regionName, desc: "规范提取演示" });
      if (res.status === 409) {
        res = await patchRegion(rid, { name: regionName });
      }
      if (!res.ok) {
        setHint(`区域登记失败：${await readApiError(res)}`);
        return;
      }
      setHint("区域已就绪");
      markDone(1);
      setStep(2);
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const uploadToDocumentLibrary = async () => {
    if (!uploadFile) {
      setHint("请选择要上传到文档库的文件");
      return;
    }
    setBusy(true);
    setHint("正在写入文档库（SQLite + 磁盘）…");
    try {
      const fd = new FormData();
      fd.append("file", uploadFile);
      fd.append("doc_type", docType.trim() || "law");
      const res = await uploadDocument(fd);
      if (!res.ok) {
        setHint(`上传失败：${await readApiError(res)}`);
        return;
      }
      const out = (await res.json()) as { id?: string; name?: string };
      setHint(`文档库已保存：${out.name ?? ""}（id=${out.id?.slice(0, 10) ?? "—"}…）`);
      setUploadFile(null);
      await loadLibraryDocs(out.id);
      if (out.id) setSelectedDocId(out.id);
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const vectorizeSelectedDocument = async () => {
    const did = selectedDocId.trim();
    if (!did) {
      setHint("请从列表中选择要向量化的文档");
      return;
    }
    setBusy(true);
    setHint("向量化中（读取文档库原文 → Milvus，可能较慢）…");
    try {
      const res = await postKnowledgeIngest({
        document_id: did,
        kb_id: kbId.trim() || "default",
        replace: true,
      });
      if (!res.ok) {
        setHint(`向量化失败：${await readApiError(res)}`);
        return;
      }
      const out = (await res.json()) as { doc_id?: string; chunks?: number; document_name?: string };
      setHint(
        `向量化成功：${out.document_name ?? did}，分块 ${out.chunks ?? "?"} 条（Milvus doc_id 与 document.id 一致）`,
      );
      markDone(2);
      await loadKbStats(kbId);
      setStep(3);
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const extractRules = async () => {
    const did = selectedDocId.trim();
    if (!did) {
      setHint("规则抽取须指定来源文档：请在步骤②中选择一条 document");
      return;
    }
    setBusy(true);
    setHint("正在执行抽取预检…");
    try {
      const preRes = await postSpecExtractPreflight({
        kb_id: kbId.trim() || "default",
        doc_ids: [did],
      });
      if (!preRes.ok) {
        setHint(`预检失败：${await readApiError(preRes)}`);
        return;
      }
      const preflight = (await preRes.json()) as ExtractPreflight;
      setExtractPreflight(preflight);
      if (!preflight.ready) {
        setHint(`抽取预检未通过：${preflight.messages.join("；")}`);
        return;
      }
      if (!vectorizedIds.has(did)) {
        setHint("所选文档尚未向量化（或状态未刷新）：请在步骤②完成向量化并点击「刷新向量化状态」");
        return;
      }
      setHint("规范规则抽取中（LLM，可能较慢）…");
      const res = await postSpecRulesExtract({
        kb_id: kbId.trim() || "default",
        doc_ids: [did],
        topic: extractTopic,
        max_rules: extractMaxRules,
        persist: extractPersist,
        re_extract: extractReExtract,
        model_name: null,
      });
      if (!res.ok) {
        setHint(`抽取失败：${await readApiError(res)}`);
        return;
      }
      const out = (await res.json()) as {
        rules?: SpecRule[];
        created_rule_ids?: string[];
        persisted?: boolean;
      };
      const cnt = out.rules?.length ?? 0;
      const ids = out.created_rule_ids?.length ?? 0;
      setHint(
        extractPersist
          ? `抽取完成：识别 ${cnt} 条，已落库草稿 ${ids} 条`
          : `抽取完成：识别 ${cnt} 条（未落库）`,
      );
      await loadRules();
      markDone(3);
      setStep(4);
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const seedAlgorithms = async () => {
    setBusy(true);
    setHint("导入内置算法种子…");
    try {
      const res = await postAlgorithmSeedBuiltin();
      if (!res.ok) {
        setHint(`导入失败：${await readApiError(res)}`);
        return;
      }
      const out = (await res.json()) as { imported?: number };
      setHint(`算法目录已更新：${out.imported ?? 0} 条`);
      markDone(4);
      await loadAlgoCount();
      setStep(5);
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const generateWorks = async () => {
    const rid = regionId.trim();
    if (!rid) {
      setHint("请先完成区域步骤");
      return;
    }
    const topicText = extractTopic.trim() || "物业日常巡检";
    setBusy(true);
    setHint("巡检业务生成中（向量检索规范 + LLM 编组，可能较慢）…");
    try {
      const res = await postInspectionWorkGenerate({
        topic: topicText,
        region_id: rid,
        max_works: maxWorks,
        persist: workPersist,
        algorithm_limit: 120,
      });
      if (!res.ok) {
        setHint(`生成失败：${await readApiError(res)}`);
        return;
      }
      const out = (await res.json()) as { works?: InspectionWork[]; count?: number };
      const list = out.works ?? [];
      setWorks(list);
      setHint(`已生成 ${out.count ?? list.length} 条巡检业务`);
      markDone(5);
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const refreshRules = () => void loadRules();

  const runExtractPreflight = async () => {
    const did = selectedDocId.trim();
    if (!did) {
      setHint("请先选择来源文档");
      return;
    }
    setBusy(true);
    setHint("正在执行抽取预检…");
    try {
      const res = await postSpecExtractPreflight({
        kb_id: kbId.trim() || "default",
        doc_ids: [did],
      });
      if (!res.ok) {
        setHint(`预检失败：${await readApiError(res)}`);
        return;
      }
      const preflight = (await res.json()) as ExtractPreflight;
      setExtractPreflight(preflight);
      setHint(
        preflight.ready
          ? "预检通过，可以开始抽取"
          : `预检未通过：${preflight.messages.join("；")}`,
      );
    } catch (e) {
      setHint(`异常：${String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const extractSourceId = selectedDocId.trim();
  const extractReady = Boolean(extractSourceId) && vectorizedIds.has(extractSourceId);
  const extractBodyPreview = {
    kb_id: kbId.trim() || "default",
    doc_ids: extractSourceId ? [extractSourceId] : ["<在步骤②选择已向量化文档的 document.id>"],
    topic: extractTopic || "",
    max_rules: extractMaxRules,
    persist: extractPersist,
    re_extract: extractReExtract,
    model_name: null,
  };

  return (
    <div className="main wf-page">
      <div className="toolbar wf-toolbar">
        <span className="wf-toolbar-title">规范提取 · 巡检业务 Demo</span>
        <span className="wf-toolbar-sub">
          文档库 + 知识库向量 → 规范仅存规则（SQLite）与规则向量
          {specStats?.rule_chunks != null ? ` · rule_chunks=${specStats.rule_chunks}` : ""}
        </span>
      </div>

      <div className="wf-layout">
        <nav className="wf-steps" aria-label="流程步骤">
          {STEPS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`wf-step-nav${step === s.id ? " current" : ""}${doneSteps.has(s.id) ? " completed" : ""}`}
              onClick={() => setStep(s.id)}
            >
              <StepBadge n={s.id} active={step === s.id} done={doneSteps.has(s.id)} />
              <span className="wf-step-nav-text">
                <strong>{s.title}</strong>
                <small>{s.hint}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="wf-panel">
          {hint ? <div className="wf-hint">{hint}</div> : null}

          {step === 1 && (
            <section className="wf-section">
              <h2>① 准备区域</h2>
              <p className="wf-lead">
                登记巡检区域（供设备与 AI 编组参考）。规范条目为<strong>全局</strong>资源，文档库上传<strong>无 region 字段</strong>。
              </p>
              <div className="wf-form-grid">
                <label>
                  region_id
                  <input
                    type="text"
                    value={regionId}
                    onChange={(e) => setRegionId(e.target.value)}
                    placeholder="demo-region-1"
                  />
                </label>
                <label>
                  展示名称
                  <input
                    type="text"
                    value={regionName}
                    onChange={(e) => setRegionName(e.target.value)}
                  />
                </label>
              </div>
              <button type="button" disabled={busy} onClick={() => void ensureRegion()}>
                登记 / 更新区域
              </button>
            </section>
          )}

          {step === 2 && (
            <section className="wf-section">
              <h2>② 文档库上传与向量化</h2>
              <p className="wf-lead">
                文件必须先 <strong>POST /api/document</strong> 进入 SQLite；知识库
                <strong>只接受 document_id</strong>，不再直接上传文件。
              </p>

              <h3 className="wf-subhead">2.1 上传到文档库</h3>
              <div className="wf-form-grid">
                <label>
                  doc_type
                  <input type="text" value={docType} onChange={(e) => setDocType(e.target.value)} />
                </label>
                <label>
                  region_id
                  <input type="text" value={regionId} readOnly className="wf-readonly" />
                </label>
                <label className="wf-span-2">
                  文件
                  <input
                    type="file"
                    accept=".docx,.pdf,.md,.txt,.xlsx,.pptx,.json"
                    onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  />
                </label>
              </div>
              <div className="wf-btn-row">
                <button type="button" disabled={busy} onClick={() => void uploadToDocumentLibrary()}>
                  上传到文档库
                </button>
                <button
                  type="button"
                  className="wf-btn-ghost"
                  disabled={busy}
                  onClick={() => void loadLibraryDocs()}
                >
                  刷新文档列表
                </button>
              </div>

              <h3 className="wf-subhead">2.2 选择并向量化</h3>
              <div className="wf-form-grid">
                <label>
                  kb_id
                  <input type="text" value={kbId} onChange={(e) => setKbId(e.target.value)} />
                </label>
              </div>
              {kbDocCount != null ? (
                <p className="wf-muted">当前 kb 已向量化 {kbDocCount} 篇</p>
              ) : null}

              {libraryDocs.length > 0 ? (
                <div className="wf-table-wrap">
                  <table className="wf-table">
                    <thead>
                      <tr>
                        <th />
                        <th>名称</th>
                        <th>document.id</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {libraryDocs.map((d) => (
                        <tr key={d.id}>
                          <td>
                            <input
                              type="radio"
                              name="lib-doc"
                              checked={selectedDocId === d.id}
                              onChange={() => setSelectedDocId(d.id)}
                            />
                          </td>
                          <td>
                            {d.name}
                            {d.ext ? <span className="wf-muted"> {d.ext}</span> : null}
                          </td>
                          <td>
                            <code className="wf-code-sm">{d.id.slice(0, 12)}…</code>
                          </td>
                          <td>
                            {vectorizedIds.has(d.id) ? (
                              <span className="wf-tag wf-tag-published">已向量化</span>
                            ) : (
                              <span className="wf-tag">未向量化</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="wf-muted">暂无文档，请先上传。</p>
              )}

              <div className="wf-btn-row wf-tight-top">
                <button type="button" disabled={busy} onClick={() => void vectorizeSelectedDocument()}>
                  向量化所选文档
                </button>
                <button
                  type="button"
                  className="wf-btn-ghost"
                  disabled={busy}
                  onClick={() => void loadKbStats(kbId)}
                >
                  刷新向量化状态
                </button>
              </div>
            </section>
          )}

          {step === 3 && (
            <section className="wf-section">
              <h2>③ 规范规则提取</h2>
              <p className="wf-lead">
                调用{" "}
                <code className="wf-code-sm">{`POST /api/spec/rules/extract`}</code>。
                请求体中 <strong>doc_ids 必填</strong>（至少一个已向量化文档的{" "}
                <code className="wf-code-sm">document.id</code>，与 Milvus metadata{" "}
                <code className="wf-code-sm">doc_id</code> 一致），不再支持省略后隐式检索整库。
              </p>
              <p className="wf-muted">
                规范为全局条目；检索范围由 <code className="wf-code-sm">kb_id</code> +{" "}
                <code className="wf-code-sm">doc_ids</code> 限定。同一 doc_id 仅允许抽取一次（persist）。
              </p>
              <p className="wf-muted">
                规范库不再存原文：仅 <code className="wf-code-sm">spec_rule</code> 表 + 规则向量（
                <code className="wf-code-sm">GET /api/spec/stats</code> 的 <code className="wf-code-sm">rule_chunks</code>
                ）；原文检索请用 <code className="wf-code-sm">POST /api/knowledge/query</code>。
              </p>
              <div className="wf-form-grid">
                <label>
                  kb_id（须与向量化一致）
                  <input type="text" value={kbId} onChange={(e) => setKbId(e.target.value)} />
                </label>
                <label className="wf-span-2">
                  主题 topic
                  <input
                    type="text"
                    value={extractTopic}
                    onChange={(e) => setExtractTopic(e.target.value)}
                  />
                </label>
                <label>
                  max_rules
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={extractMaxRules}
                    onChange={(e) => setExtractMaxRules(Number(e.target.value) || 10)}
                  />
                </label>
                <label className="wf-check">
                  <input
                    type="checkbox"
                    checked={extractPersist}
                    onChange={(e) => setExtractPersist(e.target.checked)}
                  />
                  persist 落库草稿
                </label>
                <label className="wf-check">
                  <input
                    type="checkbox"
                    checked={extractReExtract}
                    onChange={(e) => setExtractReExtract(e.target.checked)}
                  />
                  re_extract 清除草稿后重抽
                </label>
              </div>
              {extractSourceId ? (
                <p className="wf-muted">
                  当前来源文档 <code className="wf-code-sm">{extractSourceId}</code>
                  {extractReady ? (
                    <span className="wf-tag wf-tag-published wf-tight-inline">已向量化</span>
                  ) : (
                    <span className="wf-tag wf-tag-draft wf-tight-inline">未检测到向量化</span>
                  )}
                </p>
              ) : (
                <p className="wf-muted">尚未选择文档：请返回步骤②在表格中单选一行。</p>
              )}
              <p className="wf-muted wf-tight-top">与 Swagger 一致的 JSON 请求体示例（当前表单值）：</p>
              <pre className="wf-pre">{JSON.stringify(extractBodyPreview, null, 2)}</pre>
              {extractPreflight ? (
                <div className="wf-preflight">
                  <strong>最近预检：{extractPreflight.ready ? "通过" : "未通过"}</strong>
                  <pre className="wf-pre">{JSON.stringify(extractPreflight, null, 2)}</pre>
                </div>
              ) : null}
              <div className="wf-btn-row">
                <button type="button" className="wf-btn-ghost" disabled={busy || !extractSourceId} onClick={() => void runExtractPreflight()}>
                  抽取预检
                </button>
                <button
                  type="button"
                  disabled={busy || !extractReady}
                  title={
                    extractReady
                      ? undefined
                      : "须先在步骤②选择文档并完成向量化（可点「刷新向量化状态」）"
                  }
                  onClick={() => void extractRules()}
                >
                  开始抽取
                </button>
                <button type="button" className="wf-btn-ghost" disabled={busy} onClick={refreshRules}>
                  刷新规则列表
                </button>
              </div>
              {rules.length > 0 ? (
                <div className="wf-table-wrap">
                  <table className="wf-table">
                    <thead>
                      <tr>
                        <th>rule_id</th>
                        <th>名称</th>
                        <th>等级</th>
                        <th>状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rules.map((r) => (
                        <tr key={r.rule_id}>
                          <td>
                            <code className="wf-code-sm">{r.rule_id.slice(0, 10)}…</code>
                          </td>
                          <td>{r.name}</td>
                          <td>{r.level}</td>
                          <td>
                            <span className={`wf-tag wf-tag-${r.status}`}>{r.status}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="wf-muted">暂无规则，请先抽取。</p>
              )}
            </section>
          )}

          {step === 4 && (
            <section className="wf-section">
              <h2>④ 算法目录</h2>
              <p className="wf-lead">巡检业务生成需库内算法；首次可导入内置种子（约 91 条）。</p>
              {algoCount != null ? (
                <p className="wf-stat">
                  当前算法库 <strong>{algoCount}</strong> 条
                </p>
              ) : null}
              <div className="wf-btn-row">
                <button type="button" disabled={busy} onClick={() => void seedAlgorithms()}>
                  导入 builtin 种子
                </button>
                <button type="button" className="wf-btn-ghost" disabled={busy} onClick={() => void loadAlgoCount()}>
                  刷新计数
                </button>
              </div>
            </section>
          )}

          {step === 5 && (
            <section className="wf-section">
              <h2>⑤ 巡检业务生成</h2>
              <p className="wf-lead">
                规则与算法匹配编组；每条含 rule_set[].rule_id 与 algorithm_set[].algorithm_id。
              </p>
              <div className="wf-form-grid">
                <label>
                  max_works
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={maxWorks}
                    onChange={(e) => setMaxWorks(Number(e.target.value) || 8)}
                  />
                </label>
                <label className="wf-check">
                  <input
                    type="checkbox"
                    checked={workPersist}
                    onChange={(e) => setWorkPersist(e.target.checked)}
                  />
                  persist 写入 inspection_work
                </label>
              </div>
              <button type="button" disabled={busy} onClick={() => void generateWorks()}>
                生成巡检业务
              </button>

              {works.length > 0 ? (
                <div className="wf-works">
                  {works.map((w, i) => (
                    <article key={w.work_id || `draft-${i}`} className="wf-work-card">
                      <header className="wf-work-head">
                        <h3>{w.name}</h3>
                        {w.work_id ? (
                          <code className="wf-code-sm">{w.work_id.slice(0, 12)}…</code>
                        ) : (
                          <span className="wf-tag">未落库</span>
                        )}
                      </header>
                      {w.desc ? <p className="wf-work-desc">{w.desc}</p> : null}
                      <div className="wf-work-cols">
                        <div>
                          <h4>规范 rule_set</h4>
                          <ul>
                            {w.rule_set.map((r) => (
                              <li key={r.rule_id}>
                                <code>{r.rule_id.slice(0, 8)}…</code> {r.name}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <h4>算法 algorithm_set</h4>
                          <ul>
                            {w.algorithm_set.map((a) => (
                              <li key={a.algorithm_id}>
                                <code>{a.algorithm_id}</code> {a.name}
                                {a.health ? (
                                  <span className="wf-tag wf-tag-muted">{a.health}</span>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <h4>设备 equipment_set</h4>
                          {w.equipment_set.length === 0 ? (
                            <p className="wf-muted">—</p>
                          ) : (
                            <ul>
                              {w.equipment_set.map((eq) => (
                                <li key={eq.equipment_id}>
                                  {eq.name}
                                  {eq.role ? ` (${eq.role})` : ""}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
