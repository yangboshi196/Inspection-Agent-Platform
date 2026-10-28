import { MOCK_RULES } from "../mockData";
import type { KnowledgeRule } from "../types";

export type KnowledgeCategory = {
  id: string;
  name: string;
  parentId: string | null;
  icon?: string;
};

export type KnowledgeDocument = {
  id: string;
  name: string;
  categoryId: string;
  size: string;
  pages: number;
  uploadedAt: string;
  status: "ready" | "processing" | "failed";
  ruleCount: number;
};

const SOURCE_META: Record<string, { categoryId: string; size: string; pages: number; uploadedAt: string }> = {
  "现场安全生产管理规范细则（模拟稿）.docx": {
    categoryId: "cat-safety",
    size: "2.4 MB",
    pages: 48,
    uploadedAt: "2026-05-12 10:00",
  },
  "高处作业安全管理规定.pdf": {
    categoryId: "cat-safety",
    size: "1.1 MB",
    pages: 22,
    uploadedAt: "2026-05-16 09:30",
  },
  "电气安全专项条款.pdf": {
    categoryId: "cat-electric",
    size: "860 KB",
    pages: 18,
    uploadedAt: "2026-05-14 08:20",
  },
  "现场环境保护管理规范.pdf": {
    categoryId: "cat-env",
    size: "1.3 MB",
    pages: 26,
    uploadedAt: "2026-05-13 15:00",
  },
  "设备健康管理标准.docx": {
    categoryId: "cat-equipment",
    size: "980 KB",
    pages: 20,
    uploadedAt: "2026-05-16 07:45",
  },
  "受限空间作业安全规范.docx": {
    categoryId: "cat-work",
    size: "720 KB",
    pages: 16,
    uploadedAt: "2026-05-18 08:00",
  },
};

export const KB_CATEGORIES: KnowledgeCategory[] = [
  { id: "cat-root", name: "规范知识库", parentId: null, icon: "◈" },
  { id: "cat-safety", name: "安全生产", parentId: "cat-root", icon: "◉" },
  { id: "cat-env", name: "环境保护", parentId: "cat-root", icon: "◫" },
  { id: "cat-electric", name: "电气安全", parentId: "cat-root", icon: "⊠" },
  { id: "cat-equipment", name: "设备健康", parentId: "cat-root", icon: "⊡" },
  { id: "cat-work", name: "作业安全", parentId: "cat-root", icon: "⊟" },
];

const DOC_TYPE_CATEGORY: Record<string, string> = {
  law: "cat-safety",
  safety: "cat-safety",
  env: "cat-env",
  environment: "cat-env",
  electric: "cat-electric",
  equipment: "cat-equipment",
  work: "cat-work",
};

export function categoryForDocType(docType: string): string {
  const key = docType.trim().toLowerCase();
  return DOC_TYPE_CATEGORY[key] ?? "cat-safety";
}

export function categoryToDocType(categoryId: string): string {
  switch (categoryId) {
    case "cat-env":
      return "env";
    case "cat-electric":
      return "electric";
    case "cat-equipment":
      return "equipment";
    case "cat-work":
      return "work";
    default:
      return "law";
  }
}

function buildDocuments(rules: KnowledgeRule[]): KnowledgeDocument[] {
  const byFile = new Map<string, number>();
  for (const r of rules) {
    byFile.set(r.sourceFile, (byFile.get(r.sourceFile) ?? 0) + 1);
  }
  return [...byFile.entries()].map(([name, ruleCount], i) => {
    const meta = SOURCE_META[name] ?? {
      categoryId: "cat-safety",
      size: "—",
      pages: 0,
      uploadedAt: "2026-05-19 12:00",
    };
    return {
      id: `doc-${i + 1}`,
      name,
      categoryId: meta.categoryId,
      size: meta.size,
      pages: meta.pages,
      uploadedAt: meta.uploadedAt,
      status: "ready" as const,
      ruleCount,
    };
  });
}

export function categoryLabel(categoryId: string) {
  return KB_CATEGORIES.find((c) => c.id === categoryId)?.name ?? categoryId;
}

export function categoryTagsForRule(rule: KnowledgeRule, documents: KnowledgeDocument[]) {
  const doc = documents.find((d) => d.id === rule.docId || d.name === rule.sourceFile);
  if (!doc) return [] as string[];
  const label = categoryLabel(doc.categoryId);
  return label && doc.categoryId !== "cat-root" ? [label] : [];
}

export function categoryTagsForDocument(doc: KnowledgeDocument) {
  const label = categoryLabel(doc.categoryId);
  return label && doc.categoryId !== "cat-root" ? [label] : [];
}

export function enrichKnowledgeRule(rule: KnowledgeRule): KnowledgeRule {
  return {
    ...rule,
    recommendedAlgorithms: rule.recommendedAlgorithms ?? [],
    recommendedRegions: rule.recommendedRegions ?? [],
    regionReasoning: rule.regionReasoning?.trim() ?? "",
    algorithmReasoning: rule.algorithmReasoning?.trim() ?? "",
  };
}

export const KB_DOCUMENTS = buildDocuments(MOCK_RULES);

export function kbStats(rules: KnowledgeRule[]) {
  const files = new Set(rules.map((r) => r.sourceFile));
  return {
    documents: files.size,
    rules: rules.length,
    published: rules.filter((r) => r.status === "published").length,
    draft: rules.filter((r) => r.status === "draft").length,
  };
}

export function rulesForCategory(
  rules: KnowledgeRule[],
  categoryId: string | null,
  documents: KnowledgeDocument[],
) {
  if (!categoryId || categoryId === "cat-root") return rules;
  const docIds = new Set(documents.filter((d) => d.categoryId === categoryId).map((d) => d.id));
  return rules.filter((r) => r.docId != null && docIds.has(r.docId));
}

export function categoryRuleCount(categoryId: string, rules: KnowledgeRule[], documents: KnowledgeDocument[]) {
  if (categoryId === "cat-root") return rules.length;
  return rulesForCategory(rules, categoryId, documents).length;
}

export function docRuleCount(docId: string, rules: KnowledgeRule[]) {
  return rules.filter((r) => r.docId === docId).length;
}
