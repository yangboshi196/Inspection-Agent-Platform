import type { BreakdownItem } from "../dashboardTrend";



type Props = {

  title: string;

  items: BreakdownItem[];

};



function fillPercent(value: number, max: number) {

  if (value <= 0 || max <= 0) return 0;

  return Math.min(100, Math.max(6, Math.round((value / max) * 100)));

}



export function EventCategoryBreakdown({ title, items }: Props) {

  if (items.length === 0) return null;



  const max = Math.max(0, ...items.map((i) => i.value));

  const total = items.reduce((s, i) => s + i.value, 0);



  return (

    <section className="pf-dc-breakdown" aria-label={title}>

      <h3 className="pf-dc-breakdown-title">{title}</h3>

      <ul className="pf-dc-breakdown-list">

        {items.map((item) => {

          const pct = total > 0 ? Math.round((item.value / total) * 100) : 0;

          return (

            <li key={item.id} className="pf-dc-breakdown-row">

              <div className="pf-dc-breakdown-head">

                <span className="pf-dc-breakdown-dot" style={{ background: item.color }} aria-hidden />

                <span className="pf-dc-breakdown-name" title={item.label}>

                  {item.label}

                </span>

                <span className="pf-dc-breakdown-meta">

                  <strong className="pf-dc-breakdown-count">{item.value}</strong>

                  {total > 0 ? <span className="pf-dc-breakdown-pct">{pct}%</span> : null}

                </span>

              </div>

              <div className="pf-dc-breakdown-bar" aria-hidden>

                <span

                  className="pf-dc-breakdown-bar-fill"

                  style={{

                    width: `${fillPercent(item.value, max)}%`,

                    background: item.color,

                  }}

                />

              </div>

            </li>

          );

        })}

      </ul>

    </section>

  );

}

