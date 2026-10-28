import type { AiGenerationTrace, AiGenerationTraceRuleHit } from "../types";

const CN_INDEX = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"];

/** 向量路未命中时，黄色信息框首行（接在「未命中规范」之后） */
const RULE_MISS_HEADLINE =
  "未命中规范，仅命中阈值大于75%的规范，现列出相似度最高的top3，请手动选择规范";

function pct(value: number): string {
  const p = Math.max(0, Math.min(1, value)) * 100;
  return `${p.toFixed(1)}%`;
}

function joinOrNone(items: string[]): string {
  return items.length > 0 ? items.join("；") : "无";
}

function parseRuleHits(raw: unknown): AiGenerationTraceRuleHit[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((r, i) => {
      if (!r || typeof r !== "object") return null;
      const row = r as Record<string, unknown>;
      return {
        index: Number(row.index ?? i + 1),
        rule_id: String(row.rule_id ?? ""),
        name: String(row.name ?? ""),
        summary: String(row.summary ?? row.name ?? ""),
        similarity: Number(row.similarity ?? 0),
        recall_rate: row.recall_rate != null ? Number(row.recall_rate) : undefined,
        path: row.path === "vector" ? ("vector" as const) : undefined,
      };
    })
    .filter(Boolean) as AiGenerationTraceRuleHit[];
}

type Props = {
  trace: AiGenerationTrace;
};

function RuleHitLine({
  hit,
  labelPrefix,
  showRecall,
}: {
  hit: AiGenerationTraceRuleHit;
  labelPrefix: string;
  showRecall?: boolean;
}) {
  const cn = CN_INDEX[hit.index - 1] ?? String(hit.index);
  const body = hit.summary || hit.name;
  const recall =
    showRecall && hit.recall_rate != null ? `，关键词命中率：${pct(hit.recall_rate)}` : "";
  return (
    <p className="pf-studio-ai-trace-line">
      <strong>
        {labelPrefix}
        {cn}（相似度：{pct(hit.similarity)}
        {recall}）：
      </strong>
      {body}
    </p>
  );
}

export function AiGenerationTracePanel({ trace }: Props) {
  const nearMisses = trace.rule_near_misses ?? [];
  const isMiss = Boolean(trace.rules_miss_message) || (trace.rules.length === 0 && nearMisses.length > 0);

  return (
    <div className="pf-studio-ai-trace pf-kb-status" role="note" aria-label="AI 检索命中摘要">
      {isMiss ? (
        <>
          <p className="pf-studio-ai-trace-line pf-studio-ai-trace-miss-head">
            <strong>{RULE_MISS_HEADLINE}</strong>
          </p>
          {nearMisses.map((hit) => (
            <RuleHitLine
              key={hit.rule_id || `near-${hit.index}`}
              hit={hit}
              labelPrefix="规范"
            />
          ))}
        </>
      ) : (
        trace.rules.map((hit) => (
          <RuleHitLine key={hit.rule_id || String(hit.index)} hit={hit} labelPrefix="命中规范" showRecall />
        ))
      )}
      <p className="pf-studio-ai-trace-line">
        <strong>命中区域：</strong>
        {joinOrNone(trace.regions)}
      </p>
      <p className="pf-studio-ai-trace-line">
        <strong>命中算法：</strong>
        {joinOrNone(trace.algorithms)}
      </p>
      <p className="pf-studio-ai-trace-line">
        <strong>命中设备：</strong>
        {joinOrNone(trace.devices)}
      </p>
    </div>
  );
}

export function parseAiGenerationTrace(raw: unknown): AiGenerationTrace | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  const rules = parseRuleHits(o.rules);
  const nearMisses = parseRuleHits(o.rule_near_misses);
  const rulesMissMessage =
    typeof o.rules_miss_message === "string" && o.rules_miss_message.trim()
      ? o.rules_miss_message.trim()
      : undefined;
  const algorithms = Array.isArray(o.algorithms) ? o.algorithms.map(String) : [];
  const regions = Array.isArray(o.regions) ? o.regions.map(String) : [];
  const devices = Array.isArray(o.devices) ? o.devices.map(String) : [];
  const hasAny =
    rules.length > 0 ||
    nearMisses.length > 0 ||
    Boolean(rulesMissMessage) ||
    algorithms.length > 0 ||
    regions.length > 0 ||
    devices.length > 0 ||
    o.rule_path === "vector" ||
    o.rule_path === "none";
  if (!hasAny) return undefined;
  return {
    rule_path: o.rule_path === "vector" ? "vector" : "none",
    rules_miss_message: rulesMissMessage,
    rules,
    rule_near_misses: nearMisses.length > 0 ? nearMisses : undefined,
    algorithms,
    regions,
    devices,
  };
}
