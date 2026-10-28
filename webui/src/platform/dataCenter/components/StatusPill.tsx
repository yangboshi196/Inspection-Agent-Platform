type Tone = "ok" | "warn" | "err" | "idle" | "neutral";

const LABEL: Record<Tone, string> = {
  ok: "正常",
  warn: "关注",
  err: "异常",
  idle: "空闲",
  neutral: "—",
};

export function StatusPill({ tone, label }: { tone: Tone; label?: string }) {
  return (
    <span className={`pf-dc-pill pf-dc-pill-${tone}`}>
      <span className="pf-dc-pill-dot" aria-hidden />
      {label ?? LABEL[tone]}
    </span>
  );
}

export function DeltaText({ value, suffix = "%" }: { value: number; suffix?: string }) {
  if (value === 0) return <span className="pf-dc-delta pf-dc-delta-flat">持平</span>;
  const up = value > 0;
  return (
    <span className={`pf-dc-delta${up ? " pf-dc-delta-up" : " pf-dc-delta-down"}`}>
      {up ? "↑" : "↓"} {Math.abs(value)}
      {suffix}
    </span>
  );
}
