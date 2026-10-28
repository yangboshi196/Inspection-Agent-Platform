import { Link } from "react-router-dom";
import type { DashboardDayEvent } from "../inspectionEventApi";

const STATUS_LABEL: Record<string, string> = {
  pending: "待处理",
  processing: "处理中",
  resolved: "已处置",
  ignored: "已忽略",
};

type Props = {
  date: string;
  events: DashboardDayEvent[];
};

export function DayEventTimeline({ date, events }: Props) {
  if (events.length === 0) {
    return (
      <section className="pf-dc-day-events">
        <h3 className="pf-dc-day-events-title">{date} 事件明细</h3>
        <p className="pf-dc-day-events-empty">该日当前筛选条件下无事件记录。</p>
      </section>
    );
  }

  return (
    <section className="pf-dc-day-events">
      <h3 className="pf-dc-day-events-title">
        {date} 事件明细 <em>{events.length} 条</em>
      </h3>
      <ul className="pf-dc-day-events-list">
        {events.map((ev) => (
          <li key={ev.event_id} className="pf-dc-day-events-item">
            <time className="pf-dc-day-events-time" dateTime={ev.occurred_at}>
              {ev.occurred_time || ev.occurred_at.slice(11, 19)}
            </time>
            <div className="pf-dc-day-events-main">
              <strong>{ev.title}</strong>
              <span className="pf-dc-day-events-meta">
                {ev.region_name} · {ev.work_name}
                {ev.source_name ? ` · ${ev.source_name}` : ""}
              </span>
            </div>
            <span className={`pf-dc-day-events-status is-${ev.status}`}>
              {STATUS_LABEL[ev.status] ?? ev.status}
            </span>
            <Link to="/user/events" className="pf-dc-day-events-link">
              查看
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
