type Props = {
  label: string;
  value: string | number;
  hint?: string;
  trend?: string;
  accent?: "blue" | "green" | "orange" | "purple" | "red";
  icon?: string;
};

export function StatCard({ label, value, hint, trend, accent = "blue", icon }: Props) {
  return (
    <article className={`pf-stat-card pf-stat-${accent}`}>
      <span className="pf-stat-glow" aria-hidden />
      <div className="pf-stat-inner">
        <div className="pf-stat-top">
          <span className="pf-stat-label">{label}</span>
          {icon ? (
            <span className="pf-stat-icon-wrap" aria-hidden>
              {icon}
            </span>
          ) : null}
        </div>
        <div className="pf-stat-value">{value}</div>
        {hint ? <p className="pf-stat-hint">{hint}</p> : null}
        {trend ? <span className="pf-stat-trend">{trend}</span> : null}
      </div>
    </article>
  );
}
