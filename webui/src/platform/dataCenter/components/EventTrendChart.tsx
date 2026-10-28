import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import type { TrendSeries } from "../dashboardTrend";

type EventTrendChartProps = {
  labels: string[];
  series: TrendSeries[];
};

type PlotPoint = { x: number; y: number };

const Y_AXIS_WIDTH = 40;
const PAD_RIGHT = 12;
const PLOT_HEIGHT = 204;
const X_AXIS_HEIGHT = 26;
const LABEL_MIN_GAP = 52;

function linePath(points: PlotPoint[]): string {
  if (points.length === 0) return "";
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
    .join(" ");
}

function areaPath(points: PlotPoint[], baseline: number): string {
  if (points.length === 0) return "";
  const line = linePath(points);
  const last = points[points.length - 1];
  const first = points[0];
  return `${line} L ${last.x.toFixed(1)} ${baseline.toFixed(1)} L ${first.x.toFixed(1)} ${baseline.toFixed(1)} Z`;
}

function slugId(value: string, index: number) {
  const safe = value.replace(/[^a-zA-Z0-9_-]/g, "");
  return safe || `series-${index}`;
}

function nearestIndex(localX: number, count: number, xAt: (index: number) => number) {
  if (count <= 1) return 0;
  let nearest = 0;
  let minDist = Infinity;
  for (let i = 0; i < count; i += 1) {
    const dist = Math.abs(localX - xAt(i));
    if (dist < minDist) {
      minDist = dist;
      nearest = i;
    }
  }
  return nearest;
}

function buildXTickIndices(count: number, plotW: number, hoverIndex: number | null): number[] {
  if (count <= 0) return [];
  if (count === 1) return [0];

  const maxTicks = Math.max(2, Math.floor(plotW / LABEL_MIN_GAP));
  if (count <= maxTicks) {
    return Array.from({ length: count }, (_, i) => i);
  }

  const step = Math.max(1, Math.ceil(count / maxTicks));
  const indices: number[] = [];
  for (let i = 0; i < count; i += step) indices.push(i);
  if (indices[indices.length - 1] !== count - 1) indices.push(count - 1);

  if (hoverIndex != null && !indices.includes(hoverIndex)) {
    indices.push(hoverIndex);
  }

  return [...new Set(indices)].sort((a, b) => a - b);
}

function plotRatio(index: number, count: number) {
  if (count <= 1) return 0.5;
  return index / (count - 1);
}

function xLabelStyle(index: number, count: number): CSSProperties {
  const ratio = plotRatio(index, count);
  const isFirst = index === 0;
  const isLast = index === count - 1;
  if (isFirst) return { left: "0", transform: "none" };
  if (isLast) return { left: "100%", transform: "translateX(-100%)" };
  return { left: `${ratio * 100}%`, transform: "translateX(-50%)" };
}

export function EventTrendChart({ labels, series }: EventTrendChartProps) {
  const plotRef = useRef<HTMLDivElement>(null);
  const [plotWidth, setPlotWidth] = useState(0);
  const [hover, setHover] = useState<{ index: number; clientX: number; clientY: number } | null>(null);
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => new Set());

  useLayoutEffect(() => {
    const node = plotRef.current;
    if (!node) return;

    const syncWidth = () => {
      const w = node.getBoundingClientRect().width;
      if (w > 0) setPlotWidth(w);
    };

    syncWidth();
    const observer = new ResizeObserver(syncWidth);
    observer.observe(node);
    window.addEventListener("resize", syncWidth);
    window.visualViewport?.addEventListener("resize", syncWidth);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncWidth);
      window.visualViewport?.removeEventListener("resize", syncWidth);
    };
  }, []);

  const hoverIndex = hover?.index ?? null;
  const activeIndex = hoverIndex ?? Math.max(0, labels.length - 1);

  const layout = useMemo(() => {
    const width = Math.max(plotWidth || 560, 240);
    const baseline = PLOT_HEIGHT;
    const xAt = (index: number) => {
      if (labels.length <= 1) return width / 2;
      return plotRatio(index, labels.length) * width;
    };
    const tickIndices = buildXTickIndices(labels.length, width, hoverIndex);
    return { width, baseline, xAt, tickIndices };
  }, [plotWidth, labels.length, hoverIndex]);

  const visibleSeries = useMemo(
    () => series.filter((item) => !hiddenIds.has(item.id)),
    [series, hiddenIds],
  );

  const maxValue = Math.max(1, ...visibleSeries.flatMap((item) => item.values));
  const yMax = Math.max(4, Math.ceil(maxValue / 2) * 2);
  const yTicks = Array.from({ length: 5 }, (_, i) => Math.round((yMax / 4) * i));

  const yAt = (value: number) => {
    const clamped = Math.max(0, value);
    return PLOT_HEIGHT - (clamped / yMax) * PLOT_HEIGHT;
  };

  const yLabelTop = (tick: number) => `${(1 - tick / yMax) * 100}%`;

  const toggleSeries = (id: string) => {
    setHiddenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (visibleSeries.length > 1) next.add(id);
      return next;
    });
  };

  const handlePointer = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const pointerX = event.clientX - rect.left;
    const localX = (pointerX / rect.width) * layout.width;
    if (localX < -8 || localX > layout.width + 8) {
      setHover(null);
      return;
    }
    const index = nearestIndex(localX, labels.length, layout.xAt);
    setHover({ index, clientX: event.clientX, clientY: event.clientY });
  };

  const dotPosition = (index: number, value: number) => ({
    left: `${(layout.xAt(index) / layout.width) * 100}%`,
    top: `${(yAt(value) / PLOT_HEIGHT) * 100}%`,
  });

  if (series.length === 0) {
    return <p className="pf-dc-chart-empty">暂无趋势数据</p>;
  }

  const tickSet = new Set(layout.tickIndices);
  const clipId = "pf-dc-plot-clip";

  return (
    <div className="pf-dc-trend-chart">
      <div className="pf-dc-chart-legend" aria-label="图例，点击可隐藏或显示">
        {series.map((item) => {
          const hidden = hiddenIds.has(item.id);
          return (
            <button
              key={item.id}
              type="button"
              className={`pf-dc-chart-legend-item${hidden ? " is-muted" : ""}`}
              aria-pressed={!hidden}
              onClick={() => toggleSeries(item.id)}
            >
              <i className="pf-dc-chart-legend-line" style={{ background: item.color }} />
              {item.label}
            </button>
          );
        })}
      </div>

      <div
        className="pf-dc-chart-stage"
        onMouseLeave={() => setHover(null)}
      >
        <div className="pf-dc-chart-plot-row">
          <div className="pf-dc-chart-y-axis" aria-hidden="true">
            {yTicks.map((tick) => (
              <span
                key={tick}
                className="pf-dc-chart-y-label"
                style={{ top: yLabelTop(tick) }}
              >
                {tick}
              </span>
            ))}
          </div>

          <div
            ref={plotRef}
            className="pf-dc-chart-plot-wrap"
            onMouseMove={handlePointer}
          >
            {hover != null &&
              createPortal(
                <div
                  className="pf-dc-chart-tooltip"
                  style={{ left: hover.clientX, top: hover.clientY }}
                >
                  <strong>{labels[activeIndex]}</strong>
                  <ul>
                    {visibleSeries.map((item) => (
                      <li key={item.id}>
                        <i style={{ background: item.color }} />
                        <span>{item.label}</span>
                        <em>{item.values[activeIndex]}</em>
                      </li>
                    ))}
                  </ul>
                </div>,
                document.body,
              )}

            {hoverIndex != null && (
              <div
                className="pf-dc-chart-crosshair-html"
                style={{ left: `${(layout.xAt(hoverIndex) / layout.width) * 100}%` }}
                aria-hidden
              />
            )}

            {visibleSeries.map((item) =>
              item.values.map((value, index) => {
                if (hoverIndex != null ? index !== hoverIndex : index !== activeIndex) return null;
                return (
                  <span
                    key={`${item.id}-${index}`}
                    className={`pf-dc-chart-dot-html${hoverIndex != null ? " is-hover" : ""}`}
                    style={{ ...dotPosition(index, value), background: item.color }}
                    aria-hidden
                  />
                );
              }),
            )}

            <svg
              className="pf-dc-line-chart"
              width="100%"
              height={PLOT_HEIGHT}
              viewBox={`0 0 ${layout.width} ${PLOT_HEIGHT}`}
              preserveAspectRatio="none"
              role="img"
              aria-label="巡检事件数量趋势折线图"
            >
              <defs>
                <clipPath id={clipId}>
                  <rect x="0" y="0" width={layout.width} height={PLOT_HEIGHT} />
                </clipPath>
                {series.map((item, index) => {
                  const gradId = slugId(item.id, index);
                  return (
                    <linearGradient key={item.id} id={`pf-dc-fill-${gradId}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={item.color} stopOpacity="0.14" />
                      <stop offset="100%" stopColor={item.color} stopOpacity="0" />
                    </linearGradient>
                  );
                })}
              </defs>

              <g clipPath={`url(#${clipId})`}>
                {yTicks.map((tick) => {
                  const y = yAt(tick);
                  return (
                    <line
                      key={tick}
                      x1={0}
                      y1={y}
                      x2={layout.width}
                      y2={y}
                      className={`pf-dc-chart-grid${tick === 0 ? " pf-dc-chart-grid-base" : ""}`}
                      vectorEffect="non-scaling-stroke"
                    />
                  );
                })}

                {visibleSeries.map((item, seriesIndex) => {
                  const sourceIndex = series.findIndex((s) => s.id === item.id);
                  const gradId = slugId(item.id, sourceIndex >= 0 ? sourceIndex : seriesIndex);
                  const points = item.values.map((value, index) => ({
                    x: layout.xAt(index),
                    y: yAt(value),
                  }));
                  return (
                    <g key={item.id}>
                      <path
                        d={areaPath(points, layout.baseline)}
                        fill={`url(#pf-dc-fill-${gradId})`}
                        className="pf-dc-chart-area"
                      />
                      <path
                        d={linePath(points)}
                        className="pf-dc-chart-line"
                        stroke={item.color}
                        vectorEffect="non-scaling-stroke"
                      />
                    </g>
                  );
                })}
              </g>

              <line
                x1={0}
                y1={layout.baseline}
                x2={layout.width}
                y2={layout.baseline}
                className="pf-dc-chart-axis-line"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          </div>
        </div>

        <div className="pf-dc-chart-x-axis" style={{ marginLeft: Y_AXIS_WIDTH, paddingRight: PAD_RIGHT }}>
          <div className="pf-dc-chart-x-axis-inner">
            {labels.map((label, index) => {
              if (!tickSet.has(index)) return null;
              const isActive = index === activeIndex;
              return (
                <span
                  key={`${label}-${index}`}
                  className={`pf-dc-chart-x-label${isActive ? " is-active" : ""}`}
                  style={xLabelStyle(index, labels.length)}
                >
                  {label}
                </span>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
