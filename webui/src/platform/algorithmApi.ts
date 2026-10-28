import {
  createAlgorithm,
  deleteAlgorithmById,
  getVaioCoreHealth,
  getVaioMcpTools,
  listAlgorithms,
  patchAlgorithm,
  postAlgorithmSeedBuiltin,
  postVaioMcpRegister,
  postVaioSync,
  readApiError,
  type AlgorithmApiRow,
  type VaioCoreHealth,
  type VaioMcpTool,
} from "../api";
import type { AlgorithmItem } from "./types";
import type { AlgorithmDemoItem } from "./admin/algorithmMock";

function normalizeHealth(raw: string): AlgorithmItem["health"] {
  if (raw === "healthy" || raw === "degraded") return raw;
  return "unknown";
}

function inferInputType(row: AlgorithmApiRow): AlgorithmDemoItem["inputType"] {
  const schema = row.schema as {
    input?: { type?: string; properties?: Record<string, unknown> };
    vaio_id?: number;
  } | undefined;
  if (schema?.input?.type === "video" || schema?.vaio_id != null) return "video";
  const text = `${row.name} ${row.desc}`.toLowerCase();
  if (/传感|噪声|时序|温湿|dB|阈值/.test(text)) return "sensor";
  if (/视频|视觉|摄像|识别|检测|入侵|烟火|安全帽|vaio/.test(text)) return "video";
  if (schema?.input?.properties?.video_stream) return "video";
  return "video";
}

function inferCategoryId(row: AlgorithmApiRow, inputType: AlgorithmDemoItem["inputType"]): string {
  if (inputType === "sensor") return "cat-env";
  const text = `${row.name} ${row.desc}`;
  if (/安全帽|PPE|人员|反光/.test(text)) return "cat-safety";
  return "cat-vision";
}

export function apiRowToAlgorithmItem(row: AlgorithmApiRow): AlgorithmItem {
  return {
    id: row.algorithm_id,
    name: row.name,
    version: "1.0",
    description: row.desc ?? "",
    uploadedAt: "—",
    health: normalizeHealth(row.health),
  };
}

export function apiRowToDemoItem(row: AlgorithmApiRow): AlgorithmDemoItem {
  const base = apiRowToAlgorithmItem(row);
  const inputType = inferInputType(row);
  return {
    ...base,
    categoryId: inferCategoryId(row, inputType),
    inputType,
    modelSize: "—",
    linkedWorks: 0,
    linkedRules: 0,
    inferenceMs: inputType === "sensor" ? 12 : 45,
    accuracy: 0,
    author: row.link?.startsWith("vaio://") ? "vaio 核心" : row.link?.includes("invoke") ? "平台内置" : "导入",
  };
}

export async function loadAlgorithmCatalog(): Promise<AlgorithmItem[]> {
  const rows = await fetchAlgorithmRows();
  return rows.map(apiRowToAlgorithmItem);
}

export async function loadAlgorithmDemoItems(): Promise<AlgorithmDemoItem[]> {
  const rows = await fetchAlgorithmRows();
  return rows.map(apiRowToDemoItem);
}

async function fetchAlgorithmRows(): Promise<AlgorithmApiRow[]> {
  let res = await listAlgorithms(500);
  if (!res.ok) throw new Error(await readApiError(res));
  let body = (await res.json()) as { items: AlgorithmApiRow[]; total: number };
  if (body.total === 0) {
    const seed = await postAlgorithmSeedBuiltin();
    if (!seed.ok) throw new Error(await readApiError(seed));
    res = await listAlgorithms(500);
    if (!res.ok) throw new Error(await readApiError(res));
    body = (await res.json()) as typeof body;
  }
  return body.items;
}

export async function updateAlgorithmDesc(algorithmId: string, desc: string): Promise<AlgorithmApiRow> {
  const res = await patchAlgorithm(algorithmId, { desc });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as AlgorithmApiRow;
}

export async function removeAlgorithm(algorithmId: string): Promise<void> {
  const res = await deleteAlgorithmById(algorithmId);
  if (!res.ok) throw new Error(await readApiError(res));
}

export async function importAlgorithmPlaceholder(name: string): Promise<AlgorithmApiRow> {
  const id = `algo-import-${Date.now()}`;
  const res = await createAlgorithm({
    algorithm_id: id,
    name,
    desc: "通过 ZIP 包导入（演示占位）。",
    health: "unknown",
  });
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as AlgorithmApiRow;
}

export async function fetchVaioCoreHealth(): Promise<VaioCoreHealth> {
  const res = await getVaioCoreHealth();
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as VaioCoreHealth;
}

export async function syncAlgorithmsFromVaio(): Promise<{ synced: number; core_health: string }> {
  const res = await postVaioSync();
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as { synced: number; core_health: string };
}

export async function loadVaioMcpTools(): Promise<VaioMcpTool[]> {
  const res = await getVaioMcpTools();
  if (!res.ok) throw new Error(await readApiError(res));
  const body = (await res.json()) as { tools: VaioMcpTool[] };
  return body.tools ?? [];
}

export async function registerVaioHermesMcp(): Promise<{ registered: boolean; config_path: string }> {
  const res = await postVaioMcpRegister();
  if (!res.ok) throw new Error(await readApiError(res));
  return (await res.json()) as { registered: boolean; config_path: string };
}

export function getVaioMeta(row: AlgorithmApiRow): { vaioId?: number; mcpTools?: VaioMcpTool[] } {
  const schema = row.schema as { vaio_id?: number; mcp_tools?: VaioMcpTool[] } | undefined;
  if (!schema) return {};
  return { vaioId: schema.vaio_id, mcpTools: schema.mcp_tools };
}
