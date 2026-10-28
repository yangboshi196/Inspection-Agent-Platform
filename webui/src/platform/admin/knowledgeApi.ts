import {
  createSpecRule,
  deleteDocument,
  deleteKnowledgeDocument,
  deleteSpecRule,
  getAlgorithmPage,
  getSpecRule,
  getSpecRulePublishReadiness,
  listDocuments,
  listKnowledgeDocuments,
  listSpecRules,
  patchSpecRule,
  postAlgorithmSeedBuiltin,
  postKnowledgeIngest,
  postKnowledgeCleanupOrphans,
  postSpecExtractPreflight,
  streamSpecRulesExtractPipeline,
  publishSpecRule,
  readApiError,
  rebuildSpecRuleVectors,
  uploadDocument,
  type SpecExtractStreamEvent,
  type SpecPipelineEvent,
  type SpecPipelineResponse,
  type SpecPublishReadiness,
  type SpecRuleRow,
} from "../../api";
import type { AlgorithmItem, KnowledgeRule, Region } from "../types";
import { loadRegions, type RegionRow } from "../regionApi";
import {
  KB_CATEGORIES,
  type KnowledgeDocument,
  categoryForDocType,
  categoryToDocType,
  enrichKnowledgeRule,
  kbStats,
  rulesForCategory,
  categoryRuleCount,
  docRuleCount,
} from "./knowledgeMock";

export type { RegionRow, SpecPublishReadiness };

export type LibraryDocumentRow = {
  id: string;
  name: string;
  doc_type: string;
  created_at: string;
  file_size_bytes?: number;
  page_count?: number | null;
};

function formatFileSize(bytes: number | undefined): string {
  if (bytes == null || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export {
  KB_CATEGORIES,
  kbStats,
  rulesForCategory,
  categoryRuleCount,
  docRuleCount,
  categoryForDocType,
  categoryToDocType,
};

export function specRuleToKnowledgeRule(
  row: SpecRuleRow,
  docNameById: Map<string, string>,
): KnowledgeRule {
  const docName = row.doc_id ? docNameById.get(row.doc_id) : undefined;
  return {
    id: row.rule_id,
    name: row.name,
    scenario: row.desc ?? "",
    requirements: row.requirements ?? "",
    sourceFile: docName ?? row.source ?? "—",
    docId: row.doc_id ?? undefined,
    recommendedAlgorithms: row.recommended_algorithms ?? [],
    recommendedRegions: row.recommended_regions ?? [],
    algorithmReasoning: row.algorithm_reasoning?.trim() ?? "",
    regionReasoning: row.region_reasoning?.trim() ?? "",
    status: row.status === "published" ? "published" : "draft",
    extractedAt: row.updated_at ?? row.created_at,
  };
}

export type SpecExtractPreflight = {
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

function recommendationPayload(patch: {
  recommendedAlgorithms?: string[];
  recommendedRegions?: string[];
  algorithmReasoning?: string;
  regionReasoning?: string;
}): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (patch.recommendedAlgorithms !== undefined) {
    payload.recommended_algorithms = patch.recommendedAlgorithms;
  }
  if (patch.recommendedRegions !== undefined) {
    payload.recommended_regions = patch.recommendedRegions;
  }
  if (patch.algorithmReasoning !== undefined && patch.algorithmReasoning.trim()) {
    payload.algorithm_reasoning = patch.algorithmReasoning.trim();
  }
  if (patch.regionReasoning !== undefined && patch.regionReasoning.trim()) {
    payload.region_reasoning = patch.regionReasoning.trim();
  }
  return payload;
}

export function buildDocumentsFromLibrary(
  rows: LibraryDocumentRow[],
  rules: KnowledgeRule[],
  vectorizedIds: Set<string>,
): KnowledgeDocument[] {
  return rows.map((doc) => ({
    id: doc.id,
    name: doc.name,
    categoryId: categoryForDocType(doc.doc_type),
    size: formatFileSize(doc.file_size_bytes),
    pages: doc.page_count ?? 0,
    uploadedAt: doc.created_at,
    status: vectorizedIds.has(doc.id) ? "ready" : ("processing" as const),
    ruleCount: rules.filter((r) => r.docId === doc.id).length,
  }));
}

export function regionRowsToRegions(rows: RegionRow[]): Region[] {
  return rows.map((r) => ({
    id: r.id,
    code: r.id,
    name: r.name,
    parentId: r.parent_id?.trim() ? r.parent_id.trim() : null,
    description: r.desc ?? "",
    cameraCount: 0,
    childCount: rows.filter((x) => (x.parent_id ?? "").trim() === r.id).length,
  }));
}

export async function loadAlgorithms(limit = 200): Promise<AlgorithmItem[]> {
  let res = await getAlgorithmPage(limit);
  if (res.status === 404) {
    return [];
  }
  if (!res.ok) throw new Error(await readApiError(res));
  let body = (await res.json()) as {
    items: Array<{
      algorithm_id: string;
      name: string;
      desc?: string;
      health?: string;
      created_at?: string;
      updated_at?: string;
    }>;
    total: number;
  };
  if (body.total === 0) {
    const seed = await postAlgorithmSeedBuiltin();
    if (!seed.ok && seed.status !== 404) throw new Error(await readApiError(seed));
    if (seed.ok) {
      res = await getAlgorithmPage(limit);
      if (!res.ok) throw new Error(await readApiError(res));
      body = (await res.json()) as typeof body;
    }
  }
  return body.items.map((row) => ({
    id: row.algorithm_id,
    name: row.name,
    version: "1.0",
    description: row.desc ?? "",
    uploadedAt: (row.updated_at ?? row.created_at ?? "").slice(0, 16).replace("T", " "),
    health: (row.health === "healthy" || row.health === "degraded" ? row.health : "unknown") as
      | "healthy"
      | "degraded"
      | "unknown",
  }));
}

const KB_DOC_LIST_TIMEOUT_MS = 12_000;

async function listKnowledgeDocumentsWithTimeout(kbId: string): Promise<Response> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      listKnowledgeDocuments(kbId),
      new Promise<Response>((resolve) => {
        timer = setTimeout(() => {
          resolve(
            new Response("[]", {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }, KB_DOC_LIST_TIMEOUT_MS);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export async function loadKnowledgeData(kbId = "default"): Promise<{
  regions: RegionRow[];
  documents: LibraryDocumentRow[];
  rules: KnowledgeRule[];
  vectorizedIds: Set<string>;
}> {
  const [regions, docsRes, rulesRes, kbRes] = await Promise.all([
    loadRegions(),
    listDocuments({ limit: 500 }),
    listSpecRules(),
    listKnowledgeDocumentsWithTimeout(kbId),
  ]);

  if (!docsRes.ok) {
    throw new Error(await readApiError(docsRes));
  }
  const documents = (await docsRes.json()) as LibraryDocumentRow[];
  const docNameById = new Map(documents.map((d) => [d.id, d.name]));

  if (!rulesRes.ok) {
    throw new Error(await readApiError(rulesRes));
  }
  const ruleRows = (await rulesRes.json()) as SpecRuleRow[];
  const rules = ruleRows.map((row) => specRuleToKnowledgeRule(row, docNameById));

  const vectorizedIds = new Set<string>();
  if (kbRes.ok) {
    const list = (await kbRes.json()) as Array<{ source_doc_id?: string; doc_id?: string }>;
    for (const row of list) {
      const sid = (row.source_doc_id || row.doc_id || "").trim();
      if (sid) vectorizedIds.add(sid);
    }
  }

  return { regions, documents, rules, vectorizedIds };
}

/** 首屏核心数据：文档 + 规范条目 + 向量化状态（不含区域/算法） */
export async function loadKnowledgePageCore(kbId = "default"): Promise<{
  documents: KnowledgeDocument[];
  rules: KnowledgeRule[];
  vectorizedIds: Set<string>;
}> {
  const [docsRes, rulesRes, kbRes] = await Promise.all([
    listDocuments({ limit: 500 }),
    listSpecRules(),
    listKnowledgeDocumentsWithTimeout(kbId),
  ]);

  if (!docsRes.ok) {
    throw new Error(await readApiError(docsRes));
  }
  const docRows = (await docsRes.json()) as LibraryDocumentRow[];
  const docNameById = new Map(docRows.map((d) => [d.id, d.name]));

  if (!rulesRes.ok) {
    throw new Error(await readApiError(rulesRes));
  }
  const ruleRows = (await rulesRes.json()) as SpecRuleRow[];
  const rules = ruleRows
    .map((row) => specRuleToKnowledgeRule(row, docNameById))
    .map((r) => enrichKnowledgeRule(r));

  const vectorizedIds = new Set<string>();
  if (kbRes.ok) {
    const list = (await kbRes.json()) as Array<{ source_doc_id?: string; doc_id?: string }>;
    for (const row of list) {
      const sid = (row.source_doc_id || row.doc_id || "").trim();
      if (sid) vectorizedIds.add(sid);
    }
  }

  const documents = buildDocumentsFromLibrary(docRows, rules, vectorizedIds);
  return { documents, rules, vectorizedIds };
}

/** 推荐面板依赖：区域 + 算法（可首屏后异步加载） */
export async function loadKnowledgePageExtras(): Promise<{
  regions: RegionRow[];
  enrichRegions: Region[];
  algorithms: AlgorithmItem[];
}> {
  const [regions, algorithms] = await Promise.all([
    loadRegions({ seedIfEmpty: false }),
    loadAlgorithms(),
  ]);
  return {
    regions,
    enrichRegions: regionRowsToRegions(regions),
    algorithms,
  };
}

/** 已发布规范（巡检业务工作室 / AI 编组用） */
export async function loadPublishedRules(): Promise<KnowledgeRule[]> {
  const res = await listSpecRules({ status: "published" });
  if (!res.ok) throw new Error(await readApiError(res));
  const ruleRows = (await res.json()) as SpecRuleRow[];
  return ruleRows.map((row) => specRuleToKnowledgeRule(row, new Map()));
}

export async function fetchPublishReadiness(ruleId: string): Promise<SpecPublishReadiness> {
  const res = await getSpecRulePublishReadiness(ruleId);
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as SpecPublishReadiness;
}

export async function prepareKnowledgePageState(kbId = "default"): Promise<{
  regions: RegionRow[];
  enrichRegions: Region[];
  documents: KnowledgeDocument[];
  rules: KnowledgeRule[];
  algorithms: AlgorithmItem[];
}> {
  const [algorithms, core] = await Promise.all([loadAlgorithms(), loadKnowledgeData(kbId)]);
  const enrichRegions = regionRowsToRegions(core.regions);
  const rules = core.rules.map((r) => enrichKnowledgeRule(r));
  const documents = buildDocumentsFromLibrary(core.documents, rules, core.vectorizedIds);
  return {
    regions: core.regions,
    enrichRegions,
    documents,
    rules,
    algorithms,
  };
}

export async function preflightExtract(params: {
  documentId: string;
  kbId?: string;
}): Promise<SpecExtractPreflight> {
  const res = await postSpecExtractPreflight({
    kb_id: params.kbId ?? "default",
    doc_ids: [params.documentId],
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as SpecExtractPreflight;
}

export async function reIngestDocument(params: {
  documentId: string;
  kbId?: string;
}): Promise<{ chunks?: number }> {
  const res = await postKnowledgeIngest({
    document_id: params.documentId,
    kb_id: params.kbId ?? "default",
    replace: true,
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as { chunks?: number };
}

export async function uploadAndIngestDocument(params: {
  file: File;
  docType: string;
  kbId?: string;
  onProgress?: (phase: "upload" | "ingest") => void;
}): Promise<{ documentId: string }> {
  const form = new FormData();
  form.append("file", params.file);
  form.append("doc_type", params.docType);
  form.append("name", params.file.name);

  const up = await uploadDocument(form);
  if (!up.ok) {
    throw new Error(await readApiError(up));
  }
  const doc = (await up.json()) as { id: string };
  const docId = doc.id?.trim();
  if (!docId) {
    throw new Error("上传成功但未返回 document id");
  }

  params.onProgress?.("ingest");
  const ingest = await postKnowledgeIngest({
    document_id: docId,
    kb_id: params.kbId ?? "default",
    replace: true,
  });
  if (!ingest.ok) {
    throw new Error(await readApiError(ingest));
  }
  const ingestBody = (await ingest.json()) as { chunks?: number };
  if ((ingestBody.chunks ?? 0) <= 0) {
    throw new Error("向量化入库完成但未写入分片，请稍后重试");
  }

  return { documentId: docId, chunks: ingestBody.chunks };
}

const PIPELINE_PHASE_LABEL: Record<string, string> = {
  preflight: "预检",
  extract: "规范抽取",
  recommend_verify: "推荐确认",
  review: "合规审核",
};

export function formatPipelineEventsSummary(events: SpecPipelineEvent[] | undefined): string {
  if (!events?.length) return "";
  return events
    .map((e) => {
      const label = PIPELINE_PHASE_LABEL[e.phase] ?? e.phase;
      const mark = e.ok ? "✓" : "✗";
      const detail = (e.detail ?? "").trim();
      return detail ? `${label}${mark} ${detail}` : `${label}${mark}`;
    })
    .join(" → ");
}

export function handleExtractStreamEvent(
  ev: SpecExtractStreamEvent,
  params: {
    documentId: string;
    docNameById: Map<string, string>;
    onRules: (updater: (prev: KnowledgeRule[]) => KnowledgeRule[]) => void;
    setHint?: (msg: string) => void;
  },
): KnowledgeRule | null {
  if (ev.type === "phase" && ev.phase === "preflight") {
    params.setHint?.(`预检通过，共 ${ev.chunks_total ?? "?"} 个分片，开始并发抽取…`);
    return null;
  }
  if (ev.type === "extract_start") {
    const cleared = ev.cleared_draft_count ?? 0;
    if (cleared > 0) {
      params.onRules((prev) =>
        prev.filter((r) => !(r.docId === params.documentId && r.status === "draft")),
      );
    }
    params.setHint?.(
      `并发抽取 0/${ev.chunks_total ?? "?"}（${ev.workers ?? "?"} 线程）；首批约 30–90 秒出现第 1 条…`,
    );
    return null;
  }
  if (ev.type === "extract_heartbeat") {
    params.setHint?.(
      `处理中 ${ev.done_count ?? 0}/${ev.chunks_total ?? "?"}（${ev.detail ?? "LLM 抽取+推荐中"}）…`,
    );
    return null;
  }
  if ((ev.type === "rule_created" || ev.type === "chunk_skipped" || ev.type === "chunk_failed") && ev.done_count != null) {
    if (ev.type === "rule_created" && ev.rule) {
      const local = enrichKnowledgeRule(specRuleToKnowledgeRule(ev.rule, params.docNameById));
      params.onRules((prev) => {
        if (prev.some((r) => r.id === local.id)) return prev;
        return [local, ...prev];
      });
      params.setHint?.(`已抽取 ${ev.done_count}/${ev.chunks_total ?? "?"} 条…`);
      return local;
    }
    params.setHint?.(`已处理 ${ev.done_count}/${ev.chunks_total ?? "?"} 片…`);
    return null;
  }
  return null;
}

export async function extractRulesFromDocument(params: {
  documentId: string;
  kbId?: string;
  reExtract?: boolean;
  goal?: string;
  topic?: string;
  docNameById?: Map<string, string>;
  onStreamEvent?: (ev: SpecExtractStreamEvent) => void;
}): Promise<{
  createdIds: string[];
  warnings: string[];
  clearedDraftCount?: number;
  pipelineEvents?: SpecPipelineEvent[];
  reviewSummary?: string;
}> {
  const docNameMap = params.docNameById ?? new Map<string, string>();
  const body = await streamSpecRulesExtractPipeline(
    {
      kb_id: params.kbId ?? "default",
      doc_ids: [params.documentId],
      persist: true,
      re_extract: params.reExtract ?? false,
      goal: params.goal ?? params.topic ?? "知识库规范条目抽取与智能推荐",
      topic: params.topic ?? "",
    },
    (ev) => {
      params.onStreamEvent?.(ev);
    },
  );
  return {
    createdIds: body.created_rule_ids ?? [],
    warnings: body.warnings ?? [],
    clearedDraftCount: body.cleared_draft_count,
    pipelineEvents: body.pipeline_events,
    reviewSummary: body.review?.summary,
  };
}

export async function createKnowledgeRule(params: {
  name: string;
  scenario?: string;
  requirements?: string;
  docId?: string | null;
  docName?: string;
  recommendedRegions?: string[];
  recommendedAlgorithms?: string[];
  regionReasoning?: string;
  algorithmReasoning?: string;
}): Promise<SpecRuleRow> {
  const docId = params.docId?.trim() || null;
  const res = await createSpecRule({
    name: params.name.trim(),
    desc: params.scenario?.trim() ?? "",
    requirements: params.requirements?.trim() ?? "",
    doc_id: docId,
    source_trace: docId
      ? { doc_id: docId, document_name: params.docName?.trim() || undefined }
      : undefined,
    ...recommendationPayload({
      recommendedRegions: params.recommendedRegions,
      recommendedAlgorithms: params.recommendedAlgorithms,
      regionReasoning: params.regionReasoning,
      algorithmReasoning: params.algorithmReasoning,
    }),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as SpecRuleRow;
}

export async function updateKnowledgeRule(
  ruleId: string,
  patch: {
    name?: string;
    scenario?: string;
    requirements?: string;
    status?: "draft" | "published";
    recommendedAlgorithms?: string[];
    recommendedRegions?: string[];
    algorithmReasoning?: string;
    regionReasoning?: string;
  },
): Promise<SpecRuleRow> {
  const { status, ...contentPatch } = patch;
  const hasCoreFields =
    contentPatch.name !== undefined ||
    contentPatch.scenario !== undefined ||
    contentPatch.requirements !== undefined;
  const hasRecommendationFields =
    contentPatch.recommendedAlgorithms !== undefined ||
    contentPatch.recommendedRegions !== undefined ||
    contentPatch.algorithmReasoning !== undefined ||
    contentPatch.regionReasoning !== undefined;
  const hasContent = hasCoreFields || hasRecommendationFields;

  const payload: Record<string, unknown> = {
    ...recommendationPayload(contentPatch),
  };
  if (contentPatch.name !== undefined) payload.name = contentPatch.name;
  if (contentPatch.scenario !== undefined) payload.desc = contentPatch.scenario;
  if (contentPatch.requirements !== undefined) payload.requirements = contentPatch.requirements;

  if (status === "draft") {
    payload.status = "draft";
  }

  if (hasContent || status === "draft") {
    const res = await patchSpecRule(ruleId, payload);
    if (!res.ok) {
      throw new Error(await readApiError(res));
    }
    if (status !== "published") {
      return (await res.json()) as SpecRuleRow;
    }
  }

  if (status === "published") {
    const res = await publishSpecRule(ruleId);
    if (!res.ok) {
      throw new Error(await readApiError(res));
    }
    return (await res.json()) as SpecRuleRow;
  }

  const res = await getSpecRule(ruleId);
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as SpecRuleRow;
}

export async function removeKnowledgeRule(ruleId: string): Promise<void> {
  const res = await deleteSpecRule(ruleId);
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
}

export async function removeKnowledgeVectors(docId: string, kbId = "default"): Promise<void> {
  const res = await deleteKnowledgeDocument(kbId, docId);
  if (!res.ok && res.status !== 404) {
    throw new Error(await readApiError(res));
  }
}

export async function removeLibraryDocument(docId: string): Promise<void> {
  const res = await deleteDocument(docId);
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
}

export async function cleanupKnowledgeOrphans(): Promise<{
  removed_chunks: number;
  orphan_doc_ids: string[];
}> {
  const res = await postKnowledgeCleanupOrphans();
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as { removed_chunks: number; orphan_doc_ids: string[] };
}

export async function rebuildKnowledgeRuleVectors(): Promise<{ total: number; rebuilt: number; failed: { rule_id: string; error: string }[] }> {
  const res = await rebuildSpecRuleVectors();
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as { total: number; rebuilt: number; failed: { rule_id: string; error: string }[] };
}
