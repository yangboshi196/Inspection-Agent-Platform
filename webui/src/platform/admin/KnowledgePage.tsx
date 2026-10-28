import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "../components/Badge";
import { Modal } from "../components/Modal";
import { useConfirmDialog } from "../hooks/useConfirmDialog";
import type { AlgorithmItem, KnowledgeRule, Region } from "../types";
import {
  categoryLabel,
  categoryTagsForDocument,
  categoryTagsForRule,
  docRuleCount,
  kbStats,
  type KnowledgeDocument,
} from "./knowledgeMock";
import {
  categoryToDocType,
  cleanupKnowledgeOrphans,
  createKnowledgeRule,
  extractRulesFromDocument,
  fetchPublishReadiness,
  formatPipelineEventsSummary,
  handleExtractStreamEvent,
  KB_CATEGORIES as KB_CATS,
  preflightExtract,
  prepareKnowledgePageState,
  loadKnowledgePageCore,
  loadKnowledgePageExtras,
  rebuildKnowledgeRuleVectors,
  reIngestDocument,
  removeKnowledgeRule,
  removeKnowledgeVectors,
  removeLibraryDocument,
  specRuleToKnowledgeRule,
  updateKnowledgeRule,
  uploadAndIngestDocument,
  type SpecExtractPreflight,
  type SpecPublishReadiness,
} from "./knowledgeApi";

const DOC_CATEGORIES = KB_CATS.filter((c) => c.parentId === "cat-root");

function statusLabel(s: KnowledgeRule["status"]) {
  return s === "published" ? "已发布" : "草稿";
}

function statusTone(s: KnowledgeRule["status"]): "success" | "draft" {
  return s === "published" ? "success" : "draft";
}

type CreateDraft = {
  name: string;
  scenario: string;
  requirements: string;
  docId: string;
  recommendedRegions: string[];
  recommendedAlgorithms: string[];
  regionReasoning: string;
  algorithmReasoning: string;
};

const EMPTY_CREATE: CreateDraft = {
  name: "",
  scenario: "",
  requirements: "",
  docId: "",
  recommendedRegions: [],
  recommendedAlgorithms: [],
  regionReasoning: "",
  algorithmReasoning: "",
};

type RuleEditDraft = {
  name: string;
  scenario: string;
  requirements: string;
  recommendedRegions: string[];
  recommendedAlgorithms: string[];
  regionReasoning: string;
  algorithmReasoning: string;
};

function ruleToEditDraft(rule: KnowledgeRule): RuleEditDraft {
  return {
    name: rule.name,
    scenario: rule.scenario,
    requirements: rule.requirements,
    recommendedRegions: rule.recommendedRegions ?? [],
    recommendedAlgorithms: rule.recommendedAlgorithms ?? [],
    regionReasoning: rule.regionReasoning ?? "",
    algorithmReasoning: rule.algorithmReasoning ?? "",
  };
}

type RecommendPickerItem = { id: string; name: string; desc?: string };

function RecommendPickerModal({
  open,
  title,
  items,
  selectedIds,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  items: RecommendPickerItem[];
  selectedIds: string[];
  onClose: () => void;
  onConfirm: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setDraft([...selectedIds]);
  }, [open, selectedIds]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        (item.desc ?? "").toLowerCase().includes(q),
    );
  }, [items, query]);

  const toggle = (id: string) => {
    setDraft((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      modalClassName="pf-modal-kb-recommend-picker"
      footer={
        <>
          <button type="button" className="pf-btn" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-primary"
            onClick={() => onConfirm(draft)}
          >
            确定（{draft.length}）
          </button>
        </>
      }
    >
      <div className="pf-kb-recommend-picker">
        <input
          type="search"
          className="pf-kb-recommend-picker-search"
          placeholder="搜索名称或说明…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="pf-kb-recommend-picker-list">
          {filtered.length === 0 ? (
            <p className="pf-kb-recommend-picker-empty">没有匹配项</p>
          ) : (
            filtered.map((item) => {
              const checked = draft.includes(item.id);
              return (
                <label key={item.id} className={`pf-kb-recommend-picker-item${checked ? " is-checked" : ""}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(item.id)}
                  />
                  <span className="pf-kb-recommend-picker-item-body">
                    <strong>{item.name}</strong>
                    {item.desc ? <em>{item.desc}</em> : null}
                  </span>
                </label>
              );
            })
          )}
        </div>
      </div>
    </Modal>
  );
}

function RuleRecommendationEditor({
  value,
  onChange,
  disabled,
  regions,
  algorithms,
}: {
  value: {
    recommendedRegions: string[];
    recommendedAlgorithms: string[];
    regionReasoning: string;
    algorithmReasoning: string;
  };
  onChange: (next: {
    recommendedRegions: string[];
    recommendedAlgorithms: string[];
    regionReasoning: string;
    algorithmReasoning: string;
  }) => void;
  disabled?: boolean;
  regions: Region[];
  algorithms: AlgorithmItem[];
}) {
  const [picker, setPicker] = useState<"region" | "algorithm" | null>(null);
  const regionName = (id: string) => regions.find((r) => r.id === id)?.name ?? id;
  const algoName = (id: string) => algorithms.find((a) => a.id === id)?.name ?? id;

  const removeRegion = (id: string) => {
    onChange({
      ...value,
      recommendedRegions: value.recommendedRegions.filter((x) => x !== id),
    });
  };

  const removeAlgorithm = (id: string) => {
    onChange({
      ...value,
      recommendedAlgorithms: value.recommendedAlgorithms.filter((x) => x !== id),
    });
  };

  const regionPickerItems = useMemo(
    () => regions.map((r) => ({ id: r.id, name: r.name, desc: r.description })),
    [regions],
  );
  const algorithmPickerItems = useMemo(
    () => algorithms.map((a) => ({ id: a.id, name: a.name, desc: a.description })),
    [algorithms],
  );

  return (
    <div className="pf-kb-recommend-block">
      <div className="pf-kb-field pf-kb-recommend-field">
        <div className="pf-kb-recommend-head">
          <span className="pf-kb-recommend-title">智能推荐 · 适用区域</span>
          {regions.length > 0 && value.recommendedRegions.length === 0 ? (
            <span className="pf-kb-recommend-empty">暂无推荐的区域，请手动选择</span>
          ) : null}
          <button
            type="button"
            className="pf-kb-recommend-add"
            disabled={disabled || regions.length === 0}
            aria-label="选择适用区域"
            title="选择适用区域"
            onClick={() => setPicker("region")}
          >
            +
          </button>
        </div>
        <div className="pf-kb-recommend-tags">
          {regions.length === 0 ? (
            <span className="pf-kb-recommend-placeholder">暂无区域数据</span>
          ) : value.recommendedRegions.length === 0 ? (
            <span className="pf-kb-recommend-placeholder">点击右侧「+」添加适用区域</span>
          ) : (
            value.recommendedRegions.map((id) => (
              <span key={id} className="pf-kb-recommend-chip">
                <span className="pf-kb-recommend-chip-label">{regionName(id)}</span>
                <button
                  type="button"
                  className="pf-kb-recommend-chip-remove"
                  disabled={disabled}
                  aria-label={`移除 ${regionName(id)}`}
                  onClick={() => removeRegion(id)}
                >
                  ×
                </button>
              </span>
            ))
          )}
        </div>
      </div>
      <label className="pf-kb-field pf-kb-recommend-note">
        <span>适用说明</span>
        <textarea
          className="pf-cell-textarea pf-kb-textarea pf-kb-recommend-textarea"
          rows={2}
          value={value.regionReasoning}
          disabled={disabled}
          placeholder="根据区域描述与条目语义匹配生成的适用说明…"
          onChange={(e) => onChange({ ...value, regionReasoning: e.target.value })}
        />
      </label>

      <div className="pf-kb-field pf-kb-recommend-field">
        <div className="pf-kb-recommend-head">
          <span className="pf-kb-recommend-title">智能推荐 · 推荐算法</span>
          {algorithms.length > 0 && value.recommendedAlgorithms.length === 0 ? (
            <span className="pf-kb-recommend-empty">暂无推荐的算法，请手动选择</span>
          ) : null}
          <button
            type="button"
            className="pf-kb-recommend-add"
            disabled={disabled || algorithms.length === 0}
            aria-label="选择推荐算法"
            title="选择推荐算法"
            onClick={() => setPicker("algorithm")}
          >
            +
          </button>
        </div>
        <div className="pf-kb-recommend-tags">
          {algorithms.length === 0 ? (
            <span className="pf-kb-recommend-placeholder">暂无算法目录</span>
          ) : value.recommendedAlgorithms.length === 0 ? (
            <span className="pf-kb-recommend-placeholder">点击右侧「+」添加推荐算法</span>
          ) : (
            value.recommendedAlgorithms.map((id) => (
              <span key={id} className="pf-kb-recommend-chip">
                <span className="pf-kb-recommend-chip-label">{algoName(id)}</span>
                <button
                  type="button"
                  className="pf-kb-recommend-chip-remove"
                  disabled={disabled}
                  aria-label={`移除 ${algoName(id)}`}
                  onClick={() => removeAlgorithm(id)}
                >
                  ×
                </button>
              </span>
            ))
          )}
        </div>
      </div>
      <label className="pf-kb-field pf-kb-recommend-note">
        <span>推荐说明</span>
        <textarea
          className="pf-cell-textarea pf-kb-textarea pf-kb-recommend-textarea"
          rows={2}
          value={value.algorithmReasoning}
          disabled={disabled}
          placeholder="根据项目场景与要求智能推荐的算法说明…"
          onChange={(e) => onChange({ ...value, algorithmReasoning: e.target.value })}
        />
      </label>

      <RecommendPickerModal
        open={picker === "region"}
        title="选择适用区域"
        items={regionPickerItems}
        selectedIds={value.recommendedRegions}
        onClose={() => setPicker(null)}
        onConfirm={(ids) => {
          onChange({ ...value, recommendedRegions: ids });
          setPicker(null);
        }}
      />
      <RecommendPickerModal
        open={picker === "algorithm"}
        title="选择推荐算法"
        items={algorithmPickerItems}
        selectedIds={value.recommendedAlgorithms}
        onClose={() => setPicker(null)}
        onConfirm={(ids) => {
          onChange({ ...value, recommendedAlgorithms: ids });
          setPicker(null);
        }}
      />
    </div>
  );
}

function formatPreflightSummary(preflight: SpecExtractPreflight): string {
  const docLines = preflight.documents.map((d) => {
    const flags = [
      d.document_exists ? "存在" : "缺失",
      d.file_present ? "原文在盘" : "原文缺失",
      d.vectorized ? `已向量化(${d.chunk_count})` : "未向量化",
    ];
    return `${d.document_name || d.doc_id}：${flags.join(" · ")}`;
  });
  return [...docLines, ...(preflight.messages.length ? preflight.messages : [])].join("\n");
}

export function KnowledgePage() {
  const [loading, setLoading] = useState(true);
  const [extrasLoading, setExtrasLoading] = useState(false);
  const [hint, setHint] = useState("");
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [rules, setRules] = useState<KnowledgeRule[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [algorithms, setAlgorithms] = useState<AlgorithmItem[]>([]);

  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [docKw, setDocKw] = useState("");
  const [docCategoryFilter, setDocCategoryFilter] = useState<string>("all");
  const [ruleKw, setRuleKw] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "published" | "draft">("all");
  const [uploading, setUploading] = useState(false);
  const [rebuildingVectors, setRebuildingVectors] = useState(false);
  const [creatingRule, setCreatingRule] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(EMPTY_CREATE);
  const [publishReadiness, setPublishReadiness] = useState<SpecPublishReadiness | null>(null);
  const [extractPreflight, setExtractPreflight] = useState<SpecExtractPreflight | null>(null);
  const [ruleEditDraft, setRuleEditDraft] = useState<RuleEditDraft | null>(null);
  const [savingRule, setSavingRule] = useState(false);
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const docById = useMemo(() => new Map(documents.map((d) => [d.id, d])), [documents]);
  const docNameById = useMemo(() => new Map(documents.map((d) => [d.id, d.name])), [documents]);

  const reload = useCallback(async (selectRuleId?: string | null) => {
    const state = await prepareKnowledgePageState();
    setDocuments(state.documents);
    setRules(state.rules);
    setRegions(state.enrichRegions);
    setAlgorithms(state.algorithms);
    if (selectRuleId !== undefined) {
      setSelectedRuleId(selectRuleId);
    } else if (state.rules[0]?.id) {
      setSelectedRuleId((prev) => prev ?? state.rules[0].id);
    }
    return state;
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const core = await loadKnowledgePageCore();
        if (!active) return;
        setDocuments(core.documents);
        setRules(core.rules);
        if (core.rules[0]?.id) {
          setSelectedRuleId((prev) => prev ?? core.rules[0].id);
        }
        setLoading(false);

        setExtrasLoading(true);
        const extras = await loadKnowledgePageExtras();
        if (!active) return;
        setRegions(extras.enrichRegions);
        setAlgorithms(extras.algorithms);
      } catch (e) {
        if (active) setHint(String(e));
      } finally {
        if (active) {
          setLoading(false);
          setExtrasLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const stats = useMemo(
    () => ({
      ...kbStats(rules),
      documents: documents.length,
    }),
    [rules, documents],
  );

  const visibleDocs = useMemo(() => {
    let list = documents;
    if (docCategoryFilter !== "all") {
      list = list.filter((d) => d.categoryId === docCategoryFilter);
    }
    const q = docKw.trim().toLowerCase();
    if (q) {
      list = list.filter((d) =>
        [d.name, categoryLabel(d.categoryId)].join(" ").toLowerCase().includes(q),
      );
    }
    return list;
  }, [documents, docCategoryFilter, docKw]);

  const filteredRules = useMemo(() => {
    let list = selectedDocId ? rules.filter((r) => r.docId === selectedDocId) : rules;
    if (statusFilter !== "all") list = list.filter((r) => r.status === statusFilter);
    const q = ruleKw.trim().toLowerCase();
    if (q) {
      list = list.filter((r) =>
        [r.name, r.scenario, r.requirements, r.sourceFile, ...categoryTagsForRule(r, documents)]
          .join(" ")
          .toLowerCase()
          .includes(q),
      );
    }
    return list;
  }, [rules, selectedDocId, statusFilter, ruleKw, documents]);

  const selectedRule = creatingRule
    ? null
    : rules.find((r) => r.id === selectedRuleId) ?? filteredRules[0] ?? null;

  useEffect(() => {
    if (!selectedRule) {
      setRuleEditDraft(null);
      return;
    }
    setRuleEditDraft(ruleToEditDraft(selectedRule));
  }, [selectedRule?.id]);

  useEffect(() => {
    if (!selectedRule || selectedRule.status === "published") {
      setPublishReadiness(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const readiness = await fetchPublishReadiness(selectedRule.id);
        if (!cancelled) setPublishReadiness(readiness);
      } catch {
        if (!cancelled) setPublishReadiness(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedRule]);

  useEffect(() => {
    if (!creatingRule && !selectedRuleId && filteredRules[0]?.id) {
      setSelectedRuleId(filteredRules[0].id);
    }
  }, [creatingRule, selectedRuleId, filteredRules]);

  const selectDocument = (doc: KnowledgeDocument | null) => {
    setSelectedDocId(doc?.id ?? null);
    setSelectedRuleId(null);
    setCreatingRule(false);
  };

  const showGlobalView = () => selectDocument(null);

  const runExtractPreflight = async (documentId: string) => {
    const preflight = await preflightExtract({ documentId });
    setExtractPreflight(preflight);
    return preflight;
  };

  const saveSelectedRule = async () => {
    if (!selectedRule || !ruleEditDraft) return;
    setSavingRule(true);
    setHint("正在保存…");
    try {
      const row = await updateKnowledgeRule(selectedRule.id, {
        name: ruleEditDraft.name.trim(),
        scenario: ruleEditDraft.scenario,
        requirements: ruleEditDraft.requirements,
        recommendedRegions: ruleEditDraft.recommendedRegions,
        recommendedAlgorithms: ruleEditDraft.recommendedAlgorithms,
        regionReasoning: ruleEditDraft.regionReasoning,
        algorithmReasoning: ruleEditDraft.algorithmReasoning,
      });
      const saved = specRuleToKnowledgeRule(row, docNameById);
      setRules((list) => list.map((r) => (r.id === saved.id ? saved : r)));
      setRuleEditDraft(ruleToEditDraft(saved));
      setHint("已保存");
    } catch (e) {
      setHint(String(e));
    } finally {
      setSavingRule(false);
    }
  };

  const togglePublish = async (rule: KnowledgeRule) => {
    const nextStatus = rule.status === "published" ? "draft" : "published";
    try {
      if (nextStatus === "published") {
        const readiness = await fetchPublishReadiness(rule.id);
        if (!readiness.ready) {
          const failed = readiness.checks.filter((c) => !c.ok).map((c) => c.message);
          setHint(`发布就绪检查未通过：${failed.join("；")}`);
          setPublishReadiness(readiness);
          return;
        }
      }
      const row = await updateKnowledgeRule(rule.id, { status: nextStatus });
      const enriched = specRuleToKnowledgeRule(row, docNameById);
      setRules((list) => list.map((r) => (r.id === rule.id ? enriched : r)));
      setPublishReadiness(null);
      setHint(nextStatus === "published" ? "已发布" : "已转为草稿（引用该规范的巡检业务已自动下线）");
    } catch (e) {
      setHint(String(e));
    }
  };

  const deleteRule = async (rule: KnowledgeRule) => {
    const ok = await confirm({
      title: "删除规范条目？",
      description:
        `确定删除「${rule.name}」？\n` +
        "将同时删除该条目在规则向量库（spec_rules）中的向量分片，此操作不可恢复。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await removeKnowledgeRule(rule.id);
      setRules((list) => list.filter((r) => r.id !== rule.id));
      setSelectedRuleId(null);
      setHint("");
    } catch (e) {
      setHint(String(e));
    }
  };

  const deleteDoc = async (doc: KnowledgeDocument, e: React.MouseEvent) => {
    e.stopPropagation();
    const linked = rules.filter((r) => r.docId === doc.id);
    const published = linked.filter((r) => r.status === "published");
    const drafts = linked.filter((r) => r.status === "draft");
    if (published.length > 0) {
      setHint(
        `无法删除：文档下有 ${published.length} 条已发布规范条目。请先撤回为草稿或解除关联后再删。`,
      );
      return;
    }
    const ok = await confirm({
      title: "删除文档？",
      description:
        `确定从文档库删除「${doc.name}」？\n` +
        `将同时清除知识库向量分片（doc_id=${doc.id}）` +
        (drafts.length > 0 ? `，并级联删除 ${drafts.length} 条草稿规范条目及其规则向量` : "") +
        "。",
      confirmLabel: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await removeLibraryDocument(doc.id);
      setDocuments((list) => list.filter((d) => d.id !== doc.id));
      setRules((list) => list.filter((r) => r.docId !== doc.id));
      if (selectedDocId === doc.id) setSelectedDocId(null);
      setHint("");
    } catch (err) {
      setHint(String(err));
    }
  };

  const clearDocVectors = async (doc: KnowledgeDocument) => {
    const ok = await confirm({
      title: "清除知识库向量？",
      description: `仅清除「${doc.name}」的知识库向量；文档原文与已发布规范条目不受影响。可稍后重新向量化。`,
      confirmLabel: "继续",
    });
    if (!ok) return;
    try {
      await removeKnowledgeVectors(doc.id);
      await reload(selectedRuleId);
      setHint("已清除知识库向量（文档与规范条目保留）");
    } catch (e) {
      setHint(String(e));
    }
  };

  const reVectorizeDoc = async (doc: KnowledgeDocument) => {
    const ok = await confirm({
      title: "重新向量化？",
      description: `重新向量化「${doc.name}」将替换当前知识库分片，不影响文档原文与规范条目。`,
      confirmLabel: "继续",
    });
    if (!ok) return;
    setUploading(true);
    setHint(`正在重新向量化「${doc.name}」…`);
    try {
      const out = await reIngestDocument({ documentId: doc.id });
      await reload(selectedRuleId);
      setHint(`重新向量化完成：${doc.name}，分块 ${out.chunks ?? "?"} 条`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setUploading(false);
    }
  };

  const reExtractDoc = async (doc: KnowledgeDocument) => {
    const drafts = rules.filter((r) => r.docId === doc.id && r.status === "draft").length;
    const published = rules.filter((r) => r.docId === doc.id && r.status === "published").length;
    setUploading(true);
    setHint("正在执行抽取预检…");
    try {
      const preflight = await runExtractPreflight(doc.id);
      if (!preflight.ready) {
        setHint(`抽取预检未通过：${preflight.messages.join("；")}`);
        return;
      }
      const preflightNote = formatPreflightSummary(preflight);
      const ok = await confirm({
        title: "重新抽取规范条目？",
        description:
          `重新抽取「${doc.name}」？\n` +
          (drafts > 0 ? `· 将清除 ${drafts} 条草稿\n` : "") +
          (published > 0 ? `· 已发布 ${published} 条保留\n` : "") +
          "· 基于当前知识库向量生成新草稿\n\n预检结果：\n" +
          preflightNote,
        confirmLabel: "开始抽取",
      });
      if (!ok) {
        return;
      }
      setSelectedDocId(doc.id);
      let createdIds: string[] = [];
      let pipelineNote = "";
      let warnings: string[] = [];
      let clearedDraftCount: number | undefined;
      let firstRuleId: string | null = null;
      try {
        const extracted = await extractRulesFromDocument({
          documentId: doc.id,
          reExtract: true,
          goal: `重新抽取文档「${doc.name}」规范条目`,
          docNameById,
          onStreamEvent: (ev) => {
            const added = handleExtractStreamEvent(ev, {
              documentId: doc.id,
              docNameById,
              onRules: setRules,
              setHint,
            });
            if (added && !firstRuleId) firstRuleId = added.id;
          },
        });
        createdIds = extracted.createdIds;
        warnings = extracted.warnings;
        clearedDraftCount = extracted.clearedDraftCount;
        pipelineNote = formatPipelineEventsSummary(extracted.pipelineEvents);
        if (warnings.some((w) => w.includes("流式连接"))) {
          setSelectedRuleId(firstRuleId ?? createdIds[0] ?? null);
          setHint(
            createdIds.length > 0
              ? `重新抽取部分完成：已入库 ${createdIds.length} 条（${warnings.join("；")}）`
              : `重新抽取未完成：${warnings.join("；")}`,
          );
          return;
        }
      } catch (extractErr) {
        await reload(null);
        setSelectedDocId(doc.id);
        const msg = String(extractErr);
        if (msg.includes("已保留已入库条目") || msg.includes("抽取阶段中断")) {
          setHint(`重新抽取未跑完全程：${msg}`);
          return;
        }
        setHint(`重新抽取失败：${extractErr}`);
        return;
      }
      setSelectedRuleId(firstRuleId ?? createdIds[0] ?? null);
      const warnNote = warnings.length > 0 ? `；${warnings.length} 条警告` : "";
      const pipeNote = pipelineNote ? `｜${pipelineNote}` : "";
      setHint(
        `重新抽取完成：清除草稿 ${clearedDraftCount ?? 0} 条，新增 ${createdIds.length} 条${warnNote}${pipeNote}`,
      );
    } catch (e) {
      setHint(String(e));
    } finally {
      setUploading(false);
    }
  };

  const startCreateRule = () => {
    setCreatingRule(true);
    setSelectedRuleId(null);
    setCreateDraft({
      ...EMPTY_CREATE,
      docId: selectedDocId ?? "",
    });
    setHint("");
  };

  const submitCreateRule = async () => {
    const name = createDraft.name.trim();
    if (!name) {
      setHint("请填写条目标题");
      return;
    }
    try {
      const row = await createKnowledgeRule({
        name,
        scenario: createDraft.scenario,
        requirements: createDraft.requirements,
        docId: createDraft.docId || null,
        docName: createDraft.docId ? docNameById.get(createDraft.docId) : undefined,
        recommendedRegions: createDraft.recommendedRegions,
        recommendedAlgorithms: createDraft.recommendedAlgorithms,
        regionReasoning: createDraft.regionReasoning || undefined,
        algorithmReasoning: createDraft.algorithmReasoning || undefined,
      });
      const local = specRuleToKnowledgeRule(row, docNameById);
      setRules((list) => [local, ...list]);
      setSelectedRuleId(local.id);
      setCreatingRule(false);
      setHint("");
    } catch (e) {
      setHint(String(e));
    }
  };

  const handleUpload = async (file: File) => {
    setUploading(true);
    setHint("正在上传文档…");
    setExtractPreflight(null);
    const docType =
      docCategoryFilter !== "all" ? categoryToDocType(docCategoryFilter) : categoryToDocType("cat-safety");
    try {
      const { documentId } = await uploadAndIngestDocument({
        file,
        docType,
        onProgress: (phase) => {
          if (phase === "ingest") {
            setHint("正在向量化入库（首次加载本地模型较慢，约 1–5 分钟，请勿关闭页面）…");
          }
        },
      });
      const preflight = await runExtractPreflight(documentId);
      if (!preflight.ready) {
        setHint(`入库完成；抽取预检未通过：${preflight.messages.join("；")}`);
        await reload(null);
        setSelectedDocId(documentId);
        return;
      }
      setSelectedDocId(documentId);
      let createdIds: string[] = [];
      let pipelineNote = "";
      let firstRuleId: string | null = null;
      try {
        const extracted = await extractRulesFromDocument({
          documentId,
          goal: "上传文档后自动规范抽取与智能推荐",
          docNameById,
          onStreamEvent: (ev) => {
            const added = handleExtractStreamEvent(ev, {
              documentId,
              docNameById,
              onRules: setRules,
              setHint,
            });
            if (added && !firstRuleId) firstRuleId = added.id;
          },
        });
        createdIds = extracted.createdIds;
        pipelineNote = formatPipelineEventsSummary(extracted.pipelineEvents);
        if (extracted.warnings?.some((w) => w.includes("流式连接"))) {
          setSelectedDocId(documentId);
          setSelectedRuleId(firstRuleId ?? createdIds[0] ?? null);
          setHint(
            createdIds.length > 0
              ? `入库完成；部分抽取成功 ${createdIds.length} 条（${extracted.warnings.join("；")}）`
              : `入库完成；抽取未完成（${extracted.warnings.join("；")}，可手动新建条目）`,
          );
          return;
        }
      } catch (extractErr) {
        await reload(null);
        setSelectedDocId(documentId);
        const msg = String(extractErr);
        if (msg.includes("已保留已入库条目")) {
          setHint(`入库完成；抽取未跑完全程，但部分条目已入库（${msg}）`);
          return;
        }
        setHint(`入库完成；规范流水线抽取失败：${extractErr}（可手动新建条目）`);
        return;
      }
      setSelectedDocId(null);
      setSelectedRuleId(firstRuleId ?? createdIds[0] ?? null);
      const pipeNote = pipelineNote ? `｜${pipelineNote}` : "";
      setHint(
        createdIds.length > 0
          ? `入库完成，规范流水线抽取 ${createdIds.length} 条规范条目${pipeNote}`
          : `入库完成，未抽取到新条目（可手动新建）${pipeNote}`,
      );
    } catch (e) {
      setHint(String(e));
    } finally {
      setUploading(false);
    }
  };

  const handleRebuildVectors = async () => {
    const ok = await confirm({
      title: "重建规则向量？",
      description: "将按当前索引模板重建全部已发布规范向量。历史仅 desc 的向量会被更新。",
      confirmLabel: "继续",
    });
    if (!ok) {
      return;
    }
    setRebuildingVectors(true);
    setHint("");
    try {
      const result = await rebuildKnowledgeRuleVectors();
      const failNote =
        result.failed.length > 0 ? `，失败 ${result.failed.length} 条` : "";
      setHint(`向量重建完成：${result.rebuilt}/${result.total} 条${failNote}`);
    } catch (e) {
      setHint(String(e));
    } finally {
      setRebuildingVectors(false);
    }
  };

  const handleCleanupOrphans = async () => {
    const ok = await confirm({
      title: "清理孤儿向量？",
      description:
        "将扫描知识库向量库，删除 doc_id 在文档库中已不存在的孤儿分片。不影响现有文档与规范。",
      confirmLabel: "继续",
    });
    if (!ok) {
      return;
    }
    setRebuildingVectors(true);
    setHint("");
    try {
      const result = await cleanupKnowledgeOrphans();
      const ids = result.orphan_doc_ids?.length ?? 0;
      setHint(`孤儿分片清理完成：删除 ${result.removed_chunks ?? 0} 条分片（涉及 ${ids} 个 doc_id）`);
      await reload(null);
    } catch (e) {
      setHint(String(e));
    } finally {
      setRebuildingVectors(false);
    }
  };

  const selectedDoc = selectedDocId ? docById.get(selectedDocId) : null;
  const scopeLabel = selectedDoc?.name ?? "全局视图";
  const hasCoreData = documents.length > 0 || rules.length > 0;
  const statusMsg = loading && !hasCoreData
    ? "加载知识库…"
    : rebuildingVectors
      ? "正在重建规则向量…"
      : hint || (uploading ? "正在处理文档，请稍候…" : "");

  return (
    <div className="pf-scroll pf-kb-page">
      <header className="pf-kb-top-bar">
        <div className="pf-kb-top-left">
          <div className="pf-kb-title-block">
            <span className="pf-kb-title-mark" aria-hidden>◈</span>
            <h1>知识库</h1>
          </div>
          <div className="pf-kb-metrics" aria-label="知识库统计">
            <span className="pf-kb-metric pf-kb-metric-blue">
              <strong>{stats.documents}</strong><em>文档</em>
            </span>
            <span className="pf-kb-metric pf-kb-metric-purple">
              <strong>{stats.rules}</strong><em>条目</em>
            </span>
            <span className="pf-kb-metric pf-kb-metric-green">
              <strong>{stats.published}</strong><em>已发布</em>
            </span>
            <span className="pf-kb-metric pf-kb-metric-orange">
              <strong>{stats.draft}</strong><em>草稿</em>
            </span>
          </div>
        </div>
        <div className="pf-kb-header-actions">
          <button
            type="button"
            className="pf-btn"
            onClick={() => void handleCleanupOrphans()}
            disabled={uploading || loading || rebuildingVectors}
            title="清理无文档库关联的知识库向量分片"
          >
            清理孤儿向量
          </button>
          <button
            type="button"
            className="pf-btn"
            onClick={() => void handleRebuildVectors()}
            disabled={uploading || loading || rebuildingVectors}
            title="升级 #11 嵌入模板后，重建全部已发布规则向量"
          >
            重建规则向量
          </button>
          <button type="button" className="pf-btn" onClick={startCreateRule} disabled={uploading || loading || rebuildingVectors}>
            新建条目
          </button>
          <label className="pf-btn pf-btn-primary">
            上传并抽取
            <input
              type="file"
              hidden
              accept=".docx,.pdf,.md,.txt"
              disabled={uploading || loading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void handleUpload(f);
              }}
            />
          </label>
        </div>
      </header>

      {statusMsg ? <div className="pf-kb-status">{statusMsg}</div> : null}
      {extractPreflight ? (
        <div className="pf-kb-status pf-kb-preflight">
          <strong>抽取预检{extractPreflight.ready ? "通过" : "未通过"}</strong>
          <pre>{formatPreflightSummary(extractPreflight)}</pre>
        </div>
      ) : null}

      <div className="pf-kb-layout">
        <aside className="pf-panel pf-kb-sidebar">
          <div className="pf-kb-sidebar-head">
            <h2 className="pf-kb-section-title">文档库</h2>
            <span className="pf-kb-sidebar-meta">
              {selectedDocId ? "按文档筛选" : "全局"} · {visibleDocs.length} / {documents.length}
            </span>
          </div>

          {selectedDoc ? (
            <div className="pf-kb-doc-actions">
              <button
                type="button"
                className="pf-btn pf-btn-sm"
                disabled={uploading || loading}
                onClick={() => void reVectorizeDoc(selectedDoc)}
              >
                重新向量化
              </button>
              {selectedDoc.status === "ready" ? (
                <>
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm"
                    disabled={uploading || loading}
                    onClick={() => void reExtractDoc(selectedDoc)}
                  >
                    重新抽取
                  </button>
                  <button
                    type="button"
                    className="pf-btn pf-btn-sm"
                    disabled={uploading || loading}
                    onClick={() => void clearDocVectors(selectedDoc)}
                  >
                    清除向量
                  </button>
                </>
              ) : null}
            </div>
          ) : null}

          <input
            type="search"
            className="pf-cell-input pf-kb-doc-search"
            placeholder="搜索文档…"
            value={docKw}
            onChange={(e) => setDocKw(e.target.value)}
          />

          <div className="pf-kb-doc-filter-row">
            <button
              type="button"
              className={`pf-kb-filter-chip${docCategoryFilter === "all" ? " is-active" : ""}`}
              onClick={() => setDocCategoryFilter("all")}
            >
              全部
            </button>
            {DOC_CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                type="button"
                className={`pf-kb-filter-chip${docCategoryFilter === cat.id ? " is-active" : ""}`}
                onClick={() => setDocCategoryFilter(cat.id)}
              >
                {cat.name}
              </button>
            ))}
          </div>

          <ul className="pf-kb-doc-list pf-kb-doc-list-scroll">
            <li className="pf-kb-doc-row">
              <button
                type="button"
                className={`pf-kb-doc-item pf-kb-doc-item-global${selectedDocId === null ? " is-active" : ""}`}
                onClick={showGlobalView}
              >
                <span className="pf-kb-doc-name">全局视图</span>
                <span className="pf-kb-doc-meta">全部 {rules.length} 条规范</span>
              </button>
            </li>
            {visibleDocs.map((doc) => (
              <li key={doc.id} className="pf-kb-doc-row">
                <button
                  type="button"
                  className={`pf-kb-doc-item${selectedDocId === doc.id ? " is-active" : ""}`}
                  onClick={() => selectDocument(doc)}
                >
                  <span className="pf-kb-doc-name">{doc.name}</span>
                  <span className="pf-kb-doc-meta">
                    {docRuleCount(doc.id, rules)} 条 · {doc.size}
                    {doc.status === "ready" ? "" : " · 处理中"}
                  </span>
                  {categoryTagsForDocument(doc).length > 0 ? (
                    <span className="pf-kb-doc-tags">
                      {categoryTagsForDocument(doc).map((tag) => (
                        <span key={tag} className="pf-kb-tag">{tag}</span>
                      ))}
                    </span>
                  ) : null}
                </button>
                <button
                  type="button"
                  className="pf-kb-doc-row-delete"
                  title="从文档库删除（须无规范引用）"
                  disabled={uploading || loading}
                  onClick={(e) => void deleteDoc(doc, e)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="pf-kb-main">
          <div className="pf-kb-split">
            <section className="pf-panel pf-kb-rules-panel">
              <div className="pf-kb-panel-head pf-kb-panel-head-inline">
                <div className="pf-kb-rules-head-left">
                  <h2 className="pf-kb-section-title">规范条目</h2>
                  <span className="pf-kb-context">
                    {scopeLabel}
                    <span className="pf-kb-context-count">{filteredRules.length} 条</span>
                  </span>
                </div>
                <div className="pf-kb-toolbar">
                  <input
                    type="search"
                    className="pf-cell-input pf-kb-search"
                    placeholder="搜索条目…"
                    value={ruleKw}
                    onChange={(e) => setRuleKw(e.target.value)}
                  />
                  <div className="pf-kb-filter-row">
                    {(["all", "published", "draft"] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        className={`pf-kb-filter-chip${statusFilter === s ? " is-active" : ""}`}
                        onClick={() => setStatusFilter(s)}
                      >
                        {s === "all" ? "全部" : s === "published" ? "已发布" : "草稿"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="pf-kb-rule-list">
                {filteredRules.length === 0 ? (
                  <p className="pf-kb-list-empty">当前筛选下暂无条目</p>
                ) : null}
                {filteredRules.map((r) => {
                  const tags = categoryTagsForRule(r, documents);
                  return (
                    <button
                      key={r.id}
                      type="button"
                      className={`pf-kb-rule-item${selectedRule?.id === r.id ? " is-active" : ""}`}
                      onClick={() => {
                        setCreatingRule(false);
                        setSelectedRuleId(r.id);
                      }}
                    >
                      <div className="pf-kb-rule-item-top">
                        <strong>{r.name}</strong>
                        <Badge tone={statusTone(r.status)}>{statusLabel(r.status)}</Badge>
                      </div>
                      {tags.length > 0 ? (
                        <div className="pf-kb-rule-tags">
                          {tags.map((tag) => (
                            <span key={tag} className="pf-kb-tag">{tag}</span>
                          ))}
                        </div>
                      ) : null}
                      <p>{r.scenario}</p>
                      <div className="pf-kb-rule-item-meta">
                        <span>{r.sourceFile.replace(/\.(docx|pdf)$/i, "")}</span>
                        {r.extractedAt ? <time>{r.extractedAt.slice(5, 16)}</time> : null}
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="pf-panel pf-kb-detail-panel">
              <div className="pf-kb-detail-body">
                {creatingRule ? (
                  <>
                    <div className="pf-kb-detail-head">
                      <h2>新建规范条目</h2>
                      <button type="button" className="pf-btn pf-btn-sm" onClick={() => setCreatingRule(false)}>
                        取消
                      </button>
                    </div>
                    <label className="pf-kb-field">
                      <span>条目标题</span>
                      <input
                        className="pf-cell-input"
                        value={createDraft.name}
                        onChange={(e) => setCreateDraft((d) => ({ ...d, name: e.target.value }))}
                      />
                    </label>
                    <label className="pf-kb-field">
                      <span>关联文档</span>
                      <select
                        className="pf-cell-input"
                        value={createDraft.docId}
                        onChange={(e) => setCreateDraft((d) => ({ ...d, docId: e.target.value }))}
                      >
                        <option value="">无</option>
                        {documents.map((d) => (
                          <option key={d.id} value={d.id}>{d.name}</option>
                        ))}
                      </select>
                    </label>
                    <label className="pf-kb-field">
                      <span>适用场景</span>
                      <input
                        className="pf-cell-input"
                        value={createDraft.scenario}
                        onChange={(e) => setCreateDraft((d) => ({ ...d, scenario: e.target.value }))}
                      />
                    </label>
                    <label className="pf-kb-field">
                      <span>具体要求</span>
                      <textarea
                        className="pf-cell-textarea pf-kb-textarea"
                        rows={3}
                        value={createDraft.requirements}
                        onChange={(e) => setCreateDraft((d) => ({ ...d, requirements: e.target.value }))}
                      />
                    </label>
                    <RuleRecommendationEditor
                      value={{
                        recommendedRegions: createDraft.recommendedRegions,
                        recommendedAlgorithms: createDraft.recommendedAlgorithms,
                        regionReasoning: createDraft.regionReasoning,
                        algorithmReasoning: createDraft.algorithmReasoning,
                      }}
                      regions={regions}
                      algorithms={algorithms}
                      disabled={uploading || loading || extrasLoading}
                      onChange={(next) =>
                        setCreateDraft((d) => ({
                          ...d,
                          recommendedRegions: next.recommendedRegions,
                          recommendedAlgorithms: next.recommendedAlgorithms,
                          regionReasoning: next.regionReasoning,
                          algorithmReasoning: next.algorithmReasoning,
                        }))
                      }
                    />
                    <button
                      type="button"
                      className="pf-btn pf-btn-primary"
                      disabled={uploading || loading || extrasLoading}
                      onClick={() => void submitCreateRule()}
                    >
                      创建条目
                    </button>
                  </>
                ) : selectedRule ? (
                  <>
                    <div className="pf-kb-detail-head">
                      <div>
                        <div className="pf-kb-detail-badges">
                          <Badge tone={statusTone(selectedRule.status)}>{statusLabel(selectedRule.status)}</Badge>
                          {categoryTagsForRule(selectedRule, documents).map((tag) => (
                            <span key={tag} className="pf-kb-tag pf-kb-tag-detail">{tag}</span>
                          ))}
                        </div>
                        <h2>{selectedRule.name}</h2>
                      </div>
                      <div className="pf-kb-detail-actions">
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm pf-btn-primary"
                          disabled={uploading || loading || extrasLoading || savingRule || !ruleEditDraft}
                          onClick={() => void saveSelectedRule()}
                        >
                          {savingRule ? "保存中…" : "保存"}
                        </button>
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm"
                          disabled={uploading || loading || extrasLoading || savingRule}
                          onClick={() => void togglePublish(selectedRule)}
                        >
                          {selectedRule.status === "published" ? "转为草稿" : "发布"}
                        </button>
                        <button
                          type="button"
                          className="pf-btn pf-btn-sm pf-btn-danger"
                          disabled={uploading || loading || extrasLoading || savingRule}
                          onClick={() => void deleteRule(selectedRule)}
                        >
                          删除
                        </button>
                      </div>
                    </div>

                    <label className="pf-kb-field">
                      <span>条目标题</span>
                      <input
                        className="pf-cell-input"
                        value={ruleEditDraft?.name ?? ""}
                        disabled={savingRule}
                        onChange={(e) =>
                          setRuleEditDraft((d) => (d ? { ...d, name: e.target.value } : d))
                        }
                      />
                    </label>

                    <label className="pf-kb-field">
                      <span>适用场景</span>
                      <input
                        className="pf-cell-input"
                        value={ruleEditDraft?.scenario ?? ""}
                        disabled={savingRule}
                        onChange={(e) =>
                          setRuleEditDraft((d) => (d ? { ...d, scenario: e.target.value } : d))
                        }
                      />
                    </label>

                    <label className="pf-kb-field">
                      <span>具体要求</span>
                      <textarea
                        className="pf-cell-textarea pf-kb-textarea"
                        rows={3}
                        value={ruleEditDraft?.requirements ?? ""}
                        disabled={savingRule}
                        onChange={(e) =>
                          setRuleEditDraft((d) => (d ? { ...d, requirements: e.target.value } : d))
                        }
                      />
                    </label>

                    <div className="pf-kb-field">
                      <span>来源文档</span>
                      <p className="pf-kb-field-value">{selectedRule.sourceFile}</p>
                    </div>

                    {selectedRule.status === "draft" && publishReadiness ? (
                      <div className="pf-kb-field">
                        <span>发布就绪检查</span>
                        <ul className="pf-kb-readiness-list">
                          {publishReadiness.checks.map((c) => (
                            <li key={c.id} className={c.ok ? "is-ok" : "is-fail"}>
                              {c.message}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    <RuleRecommendationEditor
                      value={{
                        recommendedRegions: ruleEditDraft?.recommendedRegions ?? [],
                        recommendedAlgorithms: ruleEditDraft?.recommendedAlgorithms ?? [],
                        regionReasoning: ruleEditDraft?.regionReasoning ?? "",
                        algorithmReasoning: ruleEditDraft?.algorithmReasoning ?? "",
                      }}
                      regions={regions}
                      algorithms={algorithms}
                      disabled={uploading || loading || extrasLoading || savingRule}
                      onChange={(next) =>
                        setRuleEditDraft((d) =>
                          d
                            ? {
                                ...d,
                                recommendedRegions: next.recommendedRegions,
                                recommendedAlgorithms: next.recommendedAlgorithms,
                                regionReasoning: next.regionReasoning,
                                algorithmReasoning: next.algorithmReasoning,
                              }
                            : d,
                        )
                      }
                    />
                  </>
                ) : (
                  <p className="pf-kb-detail-empty">请选择条目，或点击「新建条目」</p>
                )}
              </div>
            </section>
          </div>
        </div>
      </div>
      {confirmDialog}
    </div>
  );
}
