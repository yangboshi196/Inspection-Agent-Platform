export function apiBase(): string {
  return import.meta.env.DEV ? "" : ".";
}

const AUTH_TOKEN_KEY = "SIA_auth_token";
const AUTH_USER_KEY = "SIA_auth_user";

const inFlightGet = new Map<string, Promise<Response>>();
const GET_FETCH_TIMEOUT_MS = 30_000;

function readAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function clearAuthSession() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
  try {
    if (typeof document !== "undefined") {
      document.cookie = "SIA_auth_token=; path=/; Max-Age=0; SameSite=Lax";
    }
  } catch {
    /* ignore */
  }
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  const token = readAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const method = (init?.method ?? "GET").toUpperCase();
  const url = String(input);
  const dedupeKey =
    method === "GET" && !init?.signal && !init?.body ? `${method} ${url}` : "";

  const doFetch = () => fetch(input, { ...init, headers });

  const doDedupeGetFetch = () => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), GET_FETCH_TIMEOUT_MS);
    return fetch(input, { ...init, headers, signal: controller.signal })
      .finally(() => window.clearTimeout(timer))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") {
          throw new Error(`Request timed out after ${GET_FETCH_TIMEOUT_MS / 1000}s: ${url}`);
        }
        throw err;
      });
  };

  let res: Response;
  if (dedupeKey) {
    const pending = inFlightGet.get(dedupeKey);
    if (pending) {
      res = await pending.then((r) => r.clone());
    } else {
      const promise = doDedupeGetFetch();
      inFlightGet.set(dedupeKey, promise);
      try {
        res = await promise;
      } finally {
        inFlightGet.delete(dedupeKey);
      }
    }
  } else {
    res = await doFetch();
  }

  if (res.status === 401 && !url.includes("/api/auth/login")) {
    clearAuthSession();
    if (typeof window !== "undefined" && !window.location.hash.includes("/login")) {
      window.location.hash = "#/login";
    }
  }
  return res;
}

export async function readApiError(res: Response): Promise<string> {
  let msg = `HTTP ${res.status}`;
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (j.detail != null) {
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    }
  } catch {
    /* ignore */
  }
  return msg;
}

/** GET /api/region/ */
export async function listRegions(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/region/`);
}

export async function postRegion(body: {
  id: string;
  name: string;
  desc?: string;
  parent_id?: string;
  sort_order?: number;
}): Promise<Response> {
  return apiFetch(`${apiBase()}/api/region/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function patchRegion(
  regionId: string,
  body: { name?: string; desc?: string; parent_id?: string; sort_order?: number },
): Promise<Response> {
  return apiFetch(`${apiBase()}/api/region/${encodeURIComponent(regionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** GET /api/document/?… 文档库列表 */
export async function listDocuments(params: {
  doc_type?: string;
  limit?: number;
} = {}): Promise<Response> {
  const qs = new URLSearchParams();
  if (params.doc_type?.trim()) qs.set("doc_type", params.doc_type.trim());
  qs.set("limit", String(Math.min(500, Math.max(1, params.limit ?? 100))));
  return apiFetch(`${apiBase()}/api/document/?${qs}`);
}

/** POST /api/document/ 上传 multipart */
export async function uploadDocument(formData: FormData): Promise<Response> {
  return apiFetch(`${apiBase()}/api/document/`, { method: "POST", body: formData });
}

/** POST /api/knowledge/ingest — 仅 JSON */
export type KnowledgeIngestPayload = {
  document_id: string;
  kb_id?: string;
  replace?: boolean;
  max_chars?: number;
  overlap?: number;
};

export async function postKnowledgeIngest(payload: KnowledgeIngestPayload): Promise<Response> {
  const body: Record<string, unknown> = {
    document_id: payload.document_id.trim(),
    kb_id: (payload.kb_id ?? "default").trim() || "default",
    replace: payload.replace ?? true,
  };
  if (payload.max_chars != null) body.max_chars = payload.max_chars;
  if (payload.overlap != null) body.overlap = payload.overlap;
  return apiFetch(`${apiBase()}/api/knowledge/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** GET /api/knowledge/{kb_id}/documents */
export async function listKnowledgeDocuments(kbId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/knowledge/${encodeURIComponent(kbId)}/documents`);
}

/** POST /api/knowledge/cleanup-orphans — 清理无文档库关联的向量分片 */
export async function postKnowledgeCleanupOrphans(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/knowledge/cleanup-orphans`, { method: "POST" });
}

/** DELETE /api/knowledge/{kb_id}/documents/{doc_id} — 仅删向量，不删文档库与规范 */
export async function deleteKnowledgeDocument(kbId: string, docId: string): Promise<Response> {
  return apiFetch(
    `${apiBase()}/api/knowledge/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(docId)}`,
    { method: "DELETE" },
  );
}

/** POST /api/knowledge/query */
export type KnowledgeQueryPayload = {
  kb_id?: string;
  query: string;
  top_k?: number;
  doc_id?: string | null;
  source_doc_id?: string | null;
};

export async function postKnowledgeQuery(payload: KnowledgeQueryPayload): Promise<Response> {
  return apiFetch(`${apiBase()}/api/knowledge/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kb_id: (payload.kb_id ?? "default").trim() || "default",
      query: payload.query,
      top_k: payload.top_k ?? 5,
      doc_id: payload.doc_id ?? null,
      source_doc_id: payload.source_doc_id ?? null,
    }),
  });
}

/** GET /api/spec/stats — 仅规则向量分片等（原文走文档库） */
export type SpecStats = {
  rule_chunks?: number;
  vector_backend?: string;
  milvus_uri?: string;
  sqlite_path?: string;
};

export async function getSpecStats(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/stats`);
}

/** GET /api/spec/rules */
export async function listSpecRules(params?: {
  status?: string | null;
}): Promise<Response> {
  const qs = new URLSearchParams();
  if (params?.status != null && String(params.status).trim()) {
    qs.set("status", String(params.status).trim());
  }
  const q = qs.toString();
  return apiFetch(`${apiBase()}/api/spec/rules${q ? `?${q}` : ""}`);
}

/** POST /api/spec/query/rules */
export type SpecRulesQueryPayload = {
  query: string;
  top_k?: number;
};

export async function postSpecRulesQuery(payload: SpecRulesQueryPayload): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/query/rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: payload.query,
      top_k: payload.top_k ?? 5,
    }),
  });
}

/** POST /api/spec/rules/extract — doc_ids 必填 */
export type SpecRuleExtractPayload = {
  kb_id?: string;
  doc_ids: string[];
  topic?: string;
  max_rules?: number;
  persist?: boolean;
  re_extract?: boolean;
  model_name?: string | null;
};

/** 后端 spec_rule 行 */
export type SpecRuleRow = {
  rule_id: string;
  name: string;
  desc: string;
  source: string;
  level: string;
  requirements: string;
  doc_id: string | null;
  status: string;
  recommended_algorithms?: string[];
  recommended_regions?: string[];
  algorithm_reasoning?: string;
  region_reasoning?: string;
  source_trace?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SpecPublishReadiness = {
  rule_id: string;
  ready: boolean;
  checks: Array<{ id: string; ok: boolean; message: string }>;
};

export type SpecRuleCreatePayload = {
  name: string;
  desc?: string;
  source?: string;
  requirements?: string;
  doc_id?: string | null;
  level?: string | null;
  recommended_algorithms?: string[];
  recommended_regions?: string[];
  algorithm_reasoning?: string;
  region_reasoning?: string;
  source_trace?: Record<string, unknown>;
};

export type SpecRulePatchPayload = {
  name?: string;
  desc?: string;
  source?: string;
  requirements?: string;
  doc_id?: string | null;
  level?: string | null;
  status?: "draft";
  recommended_algorithms?: string[];
  recommended_regions?: string[];
  algorithm_reasoning?: string;
  region_reasoning?: string;
  source_trace?: Record<string, unknown>;
};

export async function createSpecRule(payload: SpecRuleCreatePayload): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getSpecRule(ruleId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/rules/${encodeURIComponent(ruleId)}`);
}

export async function patchSpecRule(ruleId: string, payload: SpecRulePatchPayload): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/rules/${encodeURIComponent(ruleId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getSpecRulePublishReadiness(ruleId: string): Promise<Response> {
  return apiFetch(
    `${apiBase()}/api/spec/rules/${encodeURIComponent(ruleId)}/publish-readiness`,
  );
}

export async function publishSpecRule(ruleId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/rules/${encodeURIComponent(ruleId)}/publish`, { method: "POST" });
}

export async function deleteSpecRule(ruleId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });
}

export async function rebuildSpecRuleVectors(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/spec/rules/rebuild-vectors`, { method: "POST" });
}

export async function patchDocument(
  docId: string,
  body: { doc_type?: string; name?: string },
): Promise<Response> {
  return apiFetch(`${apiBase()}/api/document/${encodeURIComponent(docId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** POST /api/spec/rules/extract/pipeline — 多角色 Skill 编排（平台实现） */
export type SpecRuleExtractPipelinePayload = SpecRuleExtractPayload & {
  goal?: string;
};

export type SpecPipelineEvent = {
  phase: string;
  ok: boolean;
  detail?: string;
  agent_id?: string;
  skill?: string;
};

export type SpecPipelineResponse = {
  created_rule_ids?: string[];
  warnings?: string[];
  cleared_draft_count?: number;
  rules?: SpecRuleRow[];
  pipeline_events?: SpecPipelineEvent[];
  plan?: { scope?: string; risks?: string[]; deliverables?: string[]; notes?: string };
  strategy?: { topic?: string; extraction_mode?: string };
  review?: { summary?: string; approved_rule_ids?: string[]; issues?: Array<{ message?: string }> };
  orchestration?: string;
  note?: string;
};

export async function postSpecRulesExtractPipeline(
  payload: SpecRuleExtractPipelinePayload,
): Promise<Response> {
  const doc_ids = payload.doc_ids.map((x) => x.trim()).filter(Boolean);
  if (doc_ids.length === 0) {
    return Promise.reject(new Error("doc_ids 至少包含一个非空文档 id"));
  }
  return apiFetch(`${apiBase()}/api/spec/rules/extract/pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kb_id: (payload.kb_id ?? "default").trim() || "default",
      doc_ids,
      goal: payload.goal ?? payload.topic ?? "",
      topic: payload.topic ?? "",
      ...(payload.max_rules != null ? { max_rules: payload.max_rules } : {}),
      persist: payload.persist ?? true,
      re_extract: payload.re_extract ?? false,
      model_name: payload.model_name ?? null,
    }),
  });
}

export type SpecExtractStreamEvent = {
  type: string;
  phase?: string;
  ok?: boolean;
  detail?: string;
  chunks_total?: number;
  workers?: number;
  cleared_draft_count?: number;
  done_count?: number;
  chunk_index?: number;
  rule_id?: string;
  rule?: SpecRuleRow;
  warnings?: string[];
  created_rule_ids?: string[];
  message?: string;
  result?: SpecPipelineResponse;
};

function parseSseFrames(buffer: string): { events: SpecExtractStreamEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: SpecExtractStreamEvent[] = [];
  for (const frame of frames) {
    const line = frame
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l.startsWith("data:"));
    if (!line) continue;
    const jsonText = line.replace(/^data:\s*/, "");
    if (!jsonText) continue;
    try {
      events.push(JSON.parse(jsonText) as SpecExtractStreamEvent);
    } catch {
      // 忽略截断帧
    }
  }
  return { events, rest };
}

export async function streamSpecRulesExtractPipeline(
  payload: SpecRuleExtractPipelinePayload,
  onEvent: (ev: SpecExtractStreamEvent) => void,
): Promise<SpecPipelineResponse> {
  const doc_ids = payload.doc_ids.map((x) => x.trim()).filter(Boolean);
  if (doc_ids.length === 0) {
    throw new Error("doc_ids 至少包含一个非空文档 id");
  }
  const res = await apiFetch(`${apiBase()}/api/spec/rules/extract/pipeline/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      kb_id: (payload.kb_id ?? "default").trim() || "default",
      doc_ids,
      goal: payload.goal ?? payload.topic ?? "",
      topic: payload.topic ?? "",
      ...(payload.max_rules != null ? { max_rules: payload.max_rules } : {}),
      persist: payload.persist ?? true,
      re_extract: payload.re_extract ?? false,
      model_name: payload.model_name ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  if (!res.body) {
    throw new Error("流式抽取无响应体");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: SpecPipelineResponse | null = null;
  const streamedRuleIds: string[] = [];
  let extractPhaseDone = false;
  let extractStarted = false;

  const consume = (events: SpecExtractStreamEvent[]) => {
    for (const ev of events) {
      if (ev.type === "error") {
        throw new Error(ev.message ?? "规范抽取失败");
      }
      if (ev.type === "rule_created" && ev.rule_id) {
        streamedRuleIds.push(ev.rule_id);
      }
      if (ev.type === "extract_start") {
        extractStarted = true;
      }
      if (ev.type === "phase" && ev.phase === "extract") {
        extractPhaseDone = true;
      }
      onEvent(ev);
      if (ev.type === "done" && ev.result) {
        finalResult = ev.result;
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseFrames(buffer);
      buffer = parsed.rest;
      consume(parsed.events);
    }
    if (done) break;
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    consume(parseSseFrames(buffer).events);
  }

  if (finalResult) {
    return finalResult;
  }
  if (streamedRuleIds.length > 0 || extractPhaseDone) {
    return {
      created_rule_ids: streamedRuleIds,
      warnings: ["流式连接提前结束，已保留已入库条目"],
      chunks_processed: streamedRuleIds.length,
    };
  }
  if (extractStarted) {
    return {
      created_rule_ids: [],
      warnings: ["流式连接在抽取阶段中断，未收到完成信号（请重试或查看后端日志）"],
      chunks_processed: 0,
    };
  }
  throw new Error("流式抽取未返回完成结果（连接中断或审核阶段超时，请重试或查看后端日志）");
}

export async function postSpecRulesExtract(payload: SpecRuleExtractPayload): Promise<Response> {
  const doc_ids = payload.doc_ids.map((x) => x.trim()).filter(Boolean);
  if (doc_ids.length === 0) {
    return Promise.reject(new Error("doc_ids 至少包含一个非空文档 id"));
  }
  return apiFetch(`${apiBase()}/api/spec/rules/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kb_id: (payload.kb_id ?? "default").trim() || "default",
      doc_ids,
      topic: payload.topic ?? "",
      ...(payload.max_rules != null ? { max_rules: payload.max_rules } : {}),
      persist: payload.persist ?? false,
      re_extract: payload.re_extract ?? false,
      model_name: payload.model_name ?? null,
    }),
  });
}

export async function postSpecExtractPreflight(payload: {
  kb_id?: string;
  doc_ids: string[];
}): Promise<Response> {
  const doc_ids = payload.doc_ids.map((x) => x.trim()).filter(Boolean);
  return apiFetch(`${apiBase()}/api/spec/rules/extract/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kb_id: (payload.kb_id ?? "default").trim() || "default",
      doc_ids,
    }),
  });
}

/** GET /api/algorithm/?limit=1 取 total */
export type AlgorithmApiRow = {
  algorithm_id: string;
  name: string;
  desc: string;
  link: string;
  schema?: Record<string, unknown>;
  health: string;
};

export async function listAlgorithms(limit = 500, offset = 0): Promise<Response> {
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch(`${apiBase()}/api/algorithm/?${q}`);
}

export async function getAlgorithmPage(limit = 1): Promise<Response> {
  return listAlgorithms(limit);
}

export async function patchAlgorithm(
  algorithmId: string,
  body: { name?: string; desc?: string; link?: string; health?: string },
): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/${encodeURIComponent(algorithmId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteAlgorithmById(algorithmId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/${encodeURIComponent(algorithmId)}`, {
    method: "DELETE",
  });
}

export async function createAlgorithm(body: {
  algorithm_id?: string;
  name: string;
  desc?: string;
  link?: string;
  health?: string;
}): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function postAlgorithmSeedBuiltin(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/seed/builtin`, { method: "POST" });
}

export type VaioCoreHealth = {
  ok: boolean;
  core?: { status?: string; service?: string };
  error?: string;
  base_url?: string;
};

export type VaioMcpTool = {
  name: string;
  hermes_name: string;
  description: string;
};

export async function getVaioCoreHealth(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/vaio/health`);
}

export async function postVaioSync(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/vaio/sync`, { method: "POST" });
}

export async function getVaioMcpTools(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/vaio/mcp-tools`);
}

export async function postVaioMcpRegister(): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/vaio/mcp/register`, { method: "POST" });
}

export async function getVaioAlgorithmRecipe(vaioId: number): Promise<Response> {
  return apiFetch(`${apiBase()}/api/algorithm/vaio/algorithms/${vaioId}`);
}

/** POST /api/inspection-work/generate */
export async function postInspectionWorkGenerate(body: Record<string, unknown>): Promise<Response> {
  return apiFetch(`${apiBase()}/api/inspection-work/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** GET /api/inspection-work/?region_id= */
export async function listInspectionWorks(regionId?: string, limit = 100): Promise<Response> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (regionId?.trim()) q.set("region_id", regionId.trim());
  return apiFetch(`${apiBase()}/api/inspection-work/?${q}`);
}

/** GET /api/inspection-work/?equipment_id= */
export async function listInspectionWorksByEquipment(equipmentId: string, limit = 50): Promise<Response> {
  const q = new URLSearchParams({ limit: String(limit), equipment_id: equipmentId.trim() });
  return apiFetch(`${apiBase()}/api/inspection-work/?${q}`);
}

/** GET /api/inspection-work/{work_id} */
export async function getInspectionWork(workId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/inspection-work/${encodeURIComponent(workId)}`);
}

/** POST /api/inspection-work/ */
export async function createInspectionWork(body: Record<string, unknown>): Promise<Response> {
  return apiFetch(`${apiBase()}/api/inspection-work/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** PATCH /api/inspection-work/{work_id} */
export async function patchInspectionWork(workId: string, body: Record<string, unknown>): Promise<Response> {
  return apiFetch(`${apiBase()}/api/inspection-work/${encodeURIComponent(workId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** DELETE /api/inspection-work/{work_id} */
export async function deleteInspectionWork(workId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/inspection-work/${encodeURIComponent(workId)}`, { method: "DELETE" });
}

/** POST /api/inspection-work/{work_id}/run — 手动触发执行业务 */
export async function runInspectionWork(workId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/inspection-work/${encodeURIComponent(workId)}/run`, {
    method: "POST",
  });
}

export async function deleteRegion(regionId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/region/${encodeURIComponent(regionId)}`, { method: "DELETE" });
}

export async function deleteDocument(docId: string): Promise<Response> {
  return apiFetch(`${apiBase()}/api/document/${encodeURIComponent(docId)}`, { method: "DELETE" });
}
