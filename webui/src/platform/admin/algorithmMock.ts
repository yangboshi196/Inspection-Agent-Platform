import { MOCK_ALGORITHMS } from "../mockData";
import type { AlgorithmItem } from "../types";

export type AlgorithmCategory = {
  id: string;
  name: string;
  icon: string;
};

export type AlgorithmDemoItem = AlgorithmItem & {
  categoryId: string;
  inputType: "video" | "sensor" | "mixed";
  modelSize: string;
  linkedWorks: number;
  linkedRules: number;
  inferenceMs: number;
  accuracy: number;
  author: string;
};

const META: Record<string, Omit<AlgorithmDemoItem, keyof AlgorithmItem | "categoryId"> & { categoryId: string }> = {
  "algo-1": {
    categoryId: "cat-safety",
    inputType: "video",
    modelSize: "48 MB",
    linkedWorks: 5,
    linkedRules: 3,
    inferenceMs: 42,
    accuracy: 96.2,
    author: "平台内置",
  },
  "algo-2": {
    categoryId: "cat-vision",
    inputType: "video",
    modelSize: "62 MB",
    linkedWorks: 3,
    linkedRules: 2,
    inferenceMs: 55,
    accuracy: 94.8,
    author: "平台内置",
  },
  "algo-3": {
    categoryId: "cat-vision",
    inputType: "video",
    modelSize: "71 MB",
    linkedWorks: 4,
    linkedRules: 1,
    inferenceMs: 38,
    accuracy: 91.5,
    author: "第三方导入",
  },
  "algo-4": {
    categoryId: "cat-env",
    inputType: "sensor",
    modelSize: "12 MB",
    linkedWorks: 2,
    linkedRules: 2,
    inferenceMs: 8,
    accuracy: 98.1,
    author: "平台内置",
  },
  "algo-5": {
    categoryId: "cat-vision",
    inputType: "video",
    modelSize: "55 MB",
    linkedWorks: 1,
    linkedRules: 1,
    inferenceMs: 44,
    accuracy: 93.5,
    author: "平台内置",
  },
  "algo-6": {
    categoryId: "cat-vision",
    inputType: "video",
    modelSize: "38 MB",
    linkedWorks: 1,
    linkedRules: 1,
    inferenceMs: 36,
    accuracy: 92.0,
    author: "平台内置",
  },
  "algo-7": {
    categoryId: "cat-env",
    inputType: "sensor",
    modelSize: "15 MB",
    linkedWorks: 2,
    linkedRules: 2,
    inferenceMs: 12,
    accuracy: 89.4,
    author: "平台内置",
  },
  "algo-8": {
    categoryId: "cat-vision",
    inputType: "video",
    modelSize: "41 MB",
    linkedWorks: 0,
    linkedRules: 0,
    inferenceMs: 40,
    accuracy: 90.8,
    author: "第三方导入",
  },
};

export const ALGO_CATEGORIES: AlgorithmCategory[] = [
  { id: "cat-all", name: "全部算法", icon: "◈" },
  { id: "cat-vision", name: "视觉检测", icon: "◎" },
  { id: "cat-safety", name: "人员安全", icon: "◉" },
  { id: "cat-env", name: "环境与传感", icon: "◫" },
];

export function buildDemoAlgorithms(): AlgorithmDemoItem[] {
  return MOCK_ALGORITHMS.map((a) => {
    const m = META[a.id] ?? {
      categoryId: "cat-vision",
      inputType: "video" as const,
      modelSize: "—",
      linkedWorks: 0,
      linkedRules: 0,
      inferenceMs: 50,
      accuracy: 90,
      author: "导入",
    };
    return { ...a, ...m };
  });
}

export function algoStats(items: AlgorithmDemoItem[]) {
  return {
    total: items.length,
    healthy: items.filter((a) => a.health === "healthy").length,
    degraded: items.filter((a) => a.health === "degraded").length,
    unknown: items.filter((a) => a.health === "unknown").length,
    linkedWorks: items.reduce((s, a) => s + a.linkedWorks, 0),
  };
}

export function categoryCount(items: AlgorithmDemoItem[], categoryId: string) {
  if (categoryId === "cat-all") return items.length;
  return items.filter((a) => a.categoryId === categoryId).length;
}

export function healthLabel(h: AlgorithmItem["health"]) {
  switch (h) {
    case "healthy":
      return "正常";
    case "degraded":
      return "降级";
    default:
      return "未检测";
  }
}

export function inputTypeLabel(t: AlgorithmDemoItem["inputType"]) {
  switch (t) {
    case "video":
      return "视频流";
    case "sensor":
      return "传感时序";
    default:
      return "混合输入";
  }
}

export function algorithmSearchHaystack(item: AlgorithmDemoItem): string {
  return [
    item.name,
    item.description,
    item.id,
    item.author,
    item.version,
    inputTypeLabel(item.inputType),
    item.modelSize,
  ].join(" ");
}

function tokenMatches(haystack: string, token: string): boolean {
  const h = haystack.toLowerCase();
  const t = token.toLowerCase().trim();
  if (!t) return true;
  if (h.includes(t)) return true;
  let hi = 0;
  for (const ch of t) {
    const idx = h.indexOf(ch, hi);
    if (idx === -1) return false;
    hi = idx + 1;
  }
  return true;
}

/** 支持空格分词；单 token 支持子序列模糊匹配（如「aqm」→「安全帽」） */
export function fuzzyMatchAlgorithm(item: AlgorithmDemoItem, query: string): boolean {
  const q = query.trim();
  if (!q) return true;
  const haystack = algorithmSearchHaystack(item);
  const tokens = q.split(/\s+/).filter(Boolean);
  return tokens.every((token) => tokenMatches(haystack, token));
}
