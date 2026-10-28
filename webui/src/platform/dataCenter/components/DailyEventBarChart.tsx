import { useMemo, useState, type MouseEvent } from "react";

import { createPortal } from "react-dom";

import type { BucketBreakdownItem } from "../dashboardTrend";

import type { DashboardDayEvent } from "../inspectionEventApi";



const STATUS_LABEL: Record<string, string> = {

  pending: "待处理",

  processing: "处理中",

  resolved: "已处置",

  ignored: "已忽略",

};



const TOOLTIP_EVENT_LIMIT = 5;



type Props = {

  labels: string[];

  values: number[];

  /** 24 小时等密集刻度时缩小标签 */

  dense?: boolean;

  /** 每个柱对应桶内的分类明细（与当前「分布」维度一致） */

  bucketBreakdowns: BucketBreakdownItem[][];

  groupTitle: string;

  slotLabel?: string;

  isHourly?: boolean;

  dayEvents?: DashboardDayEvent[];

};



function hourFromLabel(label: string) {

  const m = label.match(/^(\d{1,2}):/);

  return m ? parseInt(m[1], 10) : null;

}



function eventsForBucket(

  events: DashboardDayEvent[] | undefined,

  isHourly: boolean | undefined,

  label: string,

) {

  if (!events?.length) return [];

  if (!isHourly) return [];

  const hour = hourFromLabel(label);

  if (hour == null) return [];

  return events.filter((ev) => {

    const raw = ev.occurred_time || ev.occurred_at;

    const m = raw.match(/(\d{1,2}):(\d{2})/);

    return m ? parseInt(m[1], 10) === hour : false;

  });

}



export function DailyEventBarChart({

  labels,

  values,

  dense,

  bucketBreakdowns,

  groupTitle,

  slotLabel = "时段",

  isHourly,

  dayEvents,

}: Props) {

  const [hover, setHover] = useState<{ index: number; clientX: number; clientY: number } | null>(

    null,

  );



  const max = useMemo(() => Math.max(1, ...values), [values]);

  const total = useMemo(() => values.reduce((a, b) => a + b, 0), [values]);



  if (total === 0) {

    return null;

  }



  const activeIndex = hover?.index ?? null;

  const tooltip =

    activeIndex != null

      ? (() => {

          const label = labels[activeIndex] ?? "";

          const count = values[activeIndex] ?? 0;

          const breakdown = bucketBreakdowns[activeIndex] ?? [];

          const events = eventsForBucket(dayEvents, isHourly, label);

          const shownEvents = events.slice(0, TOOLTIP_EVENT_LIMIT);

          const moreEvents = events.length - shownEvents.length;

          return { label, count, breakdown, shownEvents, moreEvents };

        })()

      : null;



  const showTooltip = (e: MouseEvent<HTMLDivElement>, index: number) => {

    const rect = e.currentTarget.getBoundingClientRect();

    setHover({

      index,

      clientX: rect.left + rect.width / 2,

      clientY: rect.top,

    });

  };



  return (

    <div

      className={`pf-dc-daily-chart${dense ? " is-dense" : ""}`}

      role="img"

      aria-label={dense ? "按小时事件数量柱状图" : "每日事件数量柱状图"}

      onMouseLeave={() => setHover(null)}

    >

      <div className="pf-dc-daily-chart-plot">

        {labels.map((label, index) => {

          const value = values[index] ?? 0;

          const pct = (value / max) * 100;

          const active = activeIndex === index;

          return (

            <div

              key={`${label}-${index}`}

              className={`pf-dc-daily-bar-col${active ? " is-active" : ""}`}

              onMouseEnter={(e) => showTooltip(e, index)}

              onMouseMove={(e) => showTooltip(e, index)}

            >

              <span className={`pf-dc-daily-bar-value${value > 0 ? "" : " is-zero"}`}>{value}</span>

              <div className="pf-dc-daily-bar-track">

                <div

                  className="pf-dc-daily-bar-fill"

                  style={{ height: `${Math.max(value > 0 ? 8 : 0, pct)}%` }}

                />

              </div>

              <span className="pf-dc-daily-bar-label">{label}</span>

            </div>

          );

        })}

      </div>



      {hover != null && tooltip != null

        ? createPortal(

            <div

              className="pf-dc-chart-tooltip pf-dc-daily-bar-tooltip"

              style={{ left: hover.clientX, top: hover.clientY }}

              role="tooltip"

            >

              <strong>

                {slotLabel} {tooltip.label}

              </strong>

              <p className="pf-dc-chart-tooltip-summary">

                共 <em>{tooltip.count}</em> 起

              </p>

              {tooltip.breakdown.length > 0 ? (

                <>

                  <span className="pf-dc-chart-tooltip-section">{groupTitle}</span>

                  <ul>

                    {tooltip.breakdown.map((item) => (

                      <li key={item.id}>

                        <i style={{ background: item.color }} aria-hidden />

                        <span>{item.label}</span>

                        <em>{item.value}</em>

                      </li>

                    ))}

                  </ul>

                </>

              ) : (

                <p className="pf-dc-chart-tooltip-empty">该{slotLabel}暂无事件</p>

              )}

              {tooltip.shownEvents.length > 0 ? (

                <>

                  <span className="pf-dc-chart-tooltip-section">事件摘要</span>

                  <ul className="pf-dc-chart-tooltip-events">

                    {tooltip.shownEvents.map((ev) => (

                      <li key={ev.event_id}>

                        <time>{ev.occurred_time || ev.occurred_at.slice(11, 19)}</time>

                        <span className="pf-dc-chart-tooltip-event-title" title={ev.title}>

                          {ev.title}

                        </span>

                        <em>{STATUS_LABEL[ev.status] ?? ev.status}</em>

                      </li>

                    ))}

                  </ul>

                  {tooltip.moreEvents > 0 ? (

                    <p className="pf-dc-chart-tooltip-more">另有 {tooltip.moreEvents} 条，见下方明细</p>

                  ) : null}

                </>

              ) : null}

            </div>,

            document.body,

          )

        : null}

    </div>

  );

}

