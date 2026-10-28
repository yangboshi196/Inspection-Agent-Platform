/** 将模型输出中的 JSON 片段格式化为易读缩进（保留非 JSON 原文） */

/** 供聊天 Markdown 使用：整段 JSON 包成代码块，其余走 prettify（含围栏内 JSON） */
export function chatMarkdownSource(raw: string): string {
  const t = raw.trim();
  if (!t) return "";
  if (
    (t.startsWith("{") && t.endsWith("}")) ||
    (t.startsWith("[") && t.endsWith("]"))
  ) {
    try {
      const pretty = JSON.stringify(JSON.parse(t), null, 2);
      return "```json\n" + pretty + "\n```";
    } catch {
      /* 非严格 JSON，交给 prettify */
    }
  }
  return prettifyModelOutput(raw);
}

export function prettifyModelOutput(raw: string): string {
  const text = raw.trim();
  if (!text) return raw;

  let out = raw;
  const fence = /```(?:json)?\s*([\s\S]*?)```/gi;
  let m: RegExpExecArray | null;
  while ((m = fence.exec(raw)) !== null) {
    const inner = m[1].trim();
    const pretty = tryStringifyJson(inner);
    if (pretty) {
      out = out.replace(m[0], "```json\n" + pretty + "\n```");
    }
  }

  const t = out.trim();
  if ((t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"))) {
    const whole = tryStringifyJson(t);
    if (whole) return whole;
  }
  return out;
}

function tryStringifyJson(s: string): string | null {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return null;
  }
}

export function isAbortError(e: unknown): boolean {
  if (e instanceof DOMException && e.name === "AbortError") return true;
  if (e && typeof e === "object" && "name" in e && (e as { name: string }).name === "AbortError")
    return true;
  return false;
}
