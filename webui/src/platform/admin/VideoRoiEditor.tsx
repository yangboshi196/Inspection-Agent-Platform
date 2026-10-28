import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  clampPercent,
  newShapeId,
  normalizeRectShape,
  rectFromPoints,
  type DetectionRoiBundle,
  type DetectionShape,
  type DrawTool,
  type RoiPoint,
} from "./detectionRoi";
import { RtspLivePreview } from "./RtspLivePreview";

type VideoRoiEditorProps = {
  background: string;
  /** 配置 RTSP 时实时流（与设备页预览同源） */
  equipmentId?: string;
  rtspAddress?: string;
  online: boolean;
  liveTime: string;
  roi: DetectionRoiBundle;
  onChange: (next: DetectionRoiBundle) => void;
  onReset: () => void;
};

function pointsToSvg(points: RoiPoint[]) {
  return points.map((p) => `${p.x},${p.y}`).join(" ");
}

function dist(a: RoiPoint, b: RoiPoint) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export function VideoRoiEditor({
  background,
  equipmentId,
  rtspAddress,
  online,
  liveTime,
  roi,
  onChange,
  onReset,
}: VideoRoiEditorProps) {
  const useRtsp = Boolean(equipmentId && (rtspAddress || "").trim());
  const hasStream = useRtsp;
  const canvasRef = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState<DrawTool>(null);
  const [draftPoints, setDraftPoints] = useState<RoiPoint[]>([]);
  const [cursorPoint, setCursorPoint] = useState<RoiPoint | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragging, setDragging] = useState<
    | { kind: "draw-rect"; start: RoiPoint }
    | { kind: "move"; shapeId: string; layer: "detection" | "inverse"; last: RoiPoint }
    | null
  >(null);

  useEffect(() => {
    setDraftPoints([]);
    setCursorPoint(null);
    setDragging(null);
    if (tool !== null) {
      setSelectedId(null);
    }
  }, [tool]);

  const findShapeLayer = useCallback(
    (shapeId: string): "detection" | "inverse" | null => {
      if (roi.detection.some((shape) => shape.id === shapeId)) return "detection";
      if (roi.inverse.some((shape) => shape.id === shapeId)) return "inverse";
      return null;
    },
    [roi.detection, roi.inverse],
  );

  const deleteSelectedShape = useCallback(() => {
    if (!selectedId) return;
    const layer = findShapeLayer(selectedId);
    if (!layer) return;
    onChange({
      ...roi,
      [layer]: roi[layer].filter((shape) => shape.id !== selectedId),
    });
    setSelectedId(null);
  }, [selectedId, findShapeLayer, roi, onChange]);

  useEffect(() => {
    if (selectedId && !findShapeLayer(selectedId)) {
      setSelectedId(null);
    }
  }, [roi, selectedId, findShapeLayer]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Delete" && event.key !== "Backspace") return;
      if (!selectedId || tool !== null) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select")) return;
      event.preventDefault();
      deleteSelectedShape();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedId, tool, deleteSelectedShape]);

  const toLocalPoint = useCallback((clientX: number, clientY: number): RoiPoint | null => {
    const el = canvasRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: clampPercent(((clientX - rect.left) / rect.width) * 100),
      y: clampPercent(((clientY - rect.top) / rect.height) * 100),
    };
  }, []);

  const patchLayer = (layer: "detection" | "inverse", shapes: DetectionShape[]) => {
    onChange({ ...roi, [layer]: shapes });
  };

  const commitShape = (layer: "detection" | "inverse", shape: DetectionShape) => {
    patchLayer(layer, [...roi[layer], shape]);
    setDraftPoints([]);
    setCursorPoint(null);
    setSelectedId(shape.id);
    setTool(null);
  };

  const finishPolygon = () => {
    if (draftPoints.length < 3) return;
    const layer = tool === "inverse-polygon" ? "inverse" : "detection";
    commitShape(layer, {
      id: newShapeId(),
      type: "polygon",
      points: draftPoints,
    });
  };

  const handleCanvasPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (tool === null) {
      setSelectedId(null);
      return;
    }
    handlePointerDown(event);
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (tool === null) return;
    const point = toLocalPoint(event.clientX, event.clientY);
    if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId);

    if (tool === "rect") {
      setDragging({ kind: "draw-rect", start: point });
      setDraftPoints([point, point]);
      return;
    }

    if (tool === "line") {
      const next = [...draftPoints, point];
      if (next.length >= 2) {
        commitShape("detection", { id: newShapeId(), type: "line", points: next.slice(0, 2) });
        setDraftPoints([]);
      } else {
        setDraftPoints(next);
      }
      return;
    }

    if (tool === "polygon" || tool === "inverse-polygon") {
      setDraftPoints((prev) => [...prev, point]);
    }
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const point = toLocalPoint(event.clientX, event.clientY);
    if (!point) return;

    if (dragging?.kind === "draw-rect") {
      setDraftPoints([dragging.start, point]);
      return;
    }

    if (dragging?.kind === "move") {
      const { shapeId, layer, last } = dragging;
      const dx = point.x - last.x;
      const dy = point.y - last.y;
      if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01) {
        patchLayer(
          layer,
          roi[layer].map((shape) => {
            if (shape.id !== shapeId) return shape;
            const moved = {
              ...shape,
              points: shape.points.map((p) => ({
                x: clampPercent(p.x + dx),
                y: clampPercent(p.y + dy),
              })),
            };
            return shape.type === "rect" ? normalizeRectShape(moved) : moved;
          }),
        );
        setDragging({ ...dragging, last: point });
      }
      return;
    }

    if (tool === "rect" && draftPoints.length === 2) {
      setDraftPoints([draftPoints[0], point]);
    } else if (tool === "rect" || tool === "polygon" || tool === "inverse-polygon") {
      setCursorPoint(point);
    }
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragging?.kind === "draw-rect") {
      const end = toLocalPoint(event.clientX, event.clientY);
      const start = dragging.start;
      if (end && dist(start, end) > 1.5) {
        commitShape("detection", {
          id: newShapeId(),
          type: "rect",
          points: [start, end],
        });
      }
      setDraftPoints([]);
      setDragging(null);
      return;
    }

    if (dragging?.kind === "move") {
      setDragging(null);
    }
  };

  const selectShape = (
    shape: DetectionShape,
    layer: "detection" | "inverse",
    event: ReactPointerEvent<SVGGElement>,
  ) => {
    if (tool !== null) return;
    const point = toLocalPoint(event.clientX, event.clientY);
    if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelectedId(shape.id);
    setDragging({ kind: "move", shapeId: shape.id, layer, last: point });
  };

  const renderShape = (shape: DetectionShape, layer: "detection" | "inverse") => {
    const selected = selectedId === shape.id;
    const stroke = layer === "inverse" ? "#ef4444" : "#3b82f6";
    const fill = layer === "inverse" ? "rgba(239,68,68,0.12)" : "rgba(59,130,246,0.12)";

    if (shape.type === "rect" && shape.points.length >= 2) {
      const rect = rectFromPoints(shape.points);
      return (
        <g
          key={shape.id}
          className={`pf-roi-shape${selected ? " is-selected" : ""}`}
          onPointerDown={(e) => {
            e.stopPropagation();
            selectShape(shape, layer, e);
          }}
        >
          <rect
            x={rect.x}
            y={rect.y}
            width={rect.width}
            height={rect.height}
            fill={fill}
            stroke={stroke}
            strokeWidth={selected ? 0.45 : 0.35}
            vectorEffect="non-scaling-stroke"
          />
          {selected
            ? shape.points.map((p, index) => (
                <circle key={`${shape.id}-h-${index}`} cx={p.x} cy={p.y} r={0.9} fill="#fff" stroke={stroke} strokeWidth={0.25} />
              ))
            : null}
        </g>
      );
    }

    if (shape.type === "line" && shape.points.length >= 2) {
      return (
        <g
          key={shape.id}
          className={`pf-roi-shape${selected ? " is-selected" : ""}`}
          onPointerDown={(e) => {
            e.stopPropagation();
            selectShape(shape, layer, e);
          }}
        >
          <polyline
            points={pointsToSvg(shape.points.slice(0, 2))}
            fill="none"
            stroke={stroke}
            strokeWidth={selected ? 0.55 : 0.4}
            vectorEffect="non-scaling-stroke"
          />
          {shape.points.slice(0, 2).map((p, index) => (
            <circle key={`${shape.id}-p-${index}`} cx={p.x} cy={p.y} r={0.8} fill={stroke} />
          ))}
        </g>
      );
    }

    if (shape.type === "polygon" && shape.points.length >= 3) {
      return (
        <g
          key={shape.id}
          className={`pf-roi-shape${selected ? " is-selected" : ""}`}
          onPointerDown={(e) => {
            e.stopPropagation();
            selectShape(shape, layer, e);
          }}
        >
          <polygon
            points={pointsToSvg(shape.points)}
            fill={fill}
            stroke={stroke}
            strokeWidth={selected ? 0.45 : 0.35}
            vectorEffect="non-scaling-stroke"
          />
          {selected
            ? shape.points.map((p, index) => (
                <circle key={`${shape.id}-h-${index}`} cx={p.x} cy={p.y} r={0.9} fill="#fff" stroke={stroke} strokeWidth={0.25} />
              ))
            : null}
        </g>
      );
    }

    return null;
  };

  const draftPreview = () => {
    if (tool === "rect" && draftPoints.length === 2) {
      const rect = rectFromPoints(draftPoints);
      return (
        <rect
          x={rect.x}
          y={rect.y}
          width={rect.width}
          height={rect.height}
          fill="rgba(59,130,246,0.1)"
          stroke="#3b82f6"
          strokeDasharray="1.2 0.8"
          strokeWidth={0.35}
          vectorEffect="non-scaling-stroke"
        />
      );
    }

    if ((tool === "polygon" || tool === "inverse-polygon") && draftPoints.length > 0) {
      const stroke = tool === "inverse-polygon" ? "#ef4444" : "#3b82f6";
      const previewPoints =
        cursorPoint && draftPoints.length > 0 ? [...draftPoints, cursorPoint] : draftPoints;
      return (
        <>
          {previewPoints.length >= 2 ? (
            <polyline
              points={pointsToSvg(previewPoints)}
              fill="none"
              stroke={stroke}
              strokeDasharray="1.2 0.8"
              strokeWidth={0.35}
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
          {previewPoints.map((p, index) => (
            <circle key={`draft-${index}`} cx={p.x} cy={p.y} r={0.75} fill={stroke} />
          ))}
        </>
      );
    }

    if (tool === "line" && draftPoints.length === 1 && cursorPoint) {
      return (
        <line
          x1={draftPoints[0].x}
          y1={draftPoints[0].y}
          x2={cursorPoint.x}
          y2={cursorPoint.y}
          stroke="#3b82f6"
          strokeDasharray="1.2 0.8"
          strokeWidth={0.35}
          vectorEffect="non-scaling-stroke"
        />
      );
    }

    return null;
  };

  return (
    <div className="pf-roi-editor">
      <div className="pf-roi-toolbar">
        <div className="pf-roi-toolbar-group">
          <span className="pf-roi-toolbar-label">编辑</span>
          <button
            type="button"
            className={`pf-roi-tool${tool === null ? " is-active" : ""}`}
            title="选择"
            onClick={() => setTool(null)}
          >
            ↖
          </button>
          <button
            type="button"
            className={`pf-roi-tool pf-roi-tool-danger${selectedId && tool === null ? "" : " is-disabled"}`}
            title="删除选中 (Delete)"
            disabled={!selectedId || tool !== null}
            onClick={deleteSelectedShape}
          >
            −
          </button>
        </div>
        <div className="pf-roi-toolbar-group">
          <span className="pf-roi-toolbar-label">检测区域</span>
          <button type="button" className={`pf-roi-tool${tool === "rect" ? " is-active" : ""}`} title="矩形" onClick={() => setTool("rect")}>□</button>
          <button type="button" className={`pf-roi-tool${tool === "polygon" ? " is-active" : ""}`} title="多边形" onClick={() => setTool("polygon")}>⬡</button>
          <button type="button" className={`pf-roi-tool${tool === "line" ? " is-active" : ""}`} title="直线" onClick={() => setTool("line")}>/</button>
        </div>
        <div className="pf-roi-toolbar-group">
          <span className="pf-roi-toolbar-label">反向检测区域</span>
          <button type="button" className={`pf-roi-tool${tool === "inverse-polygon" ? " is-active" : ""}`} title="反向多边形" onClick={() => setTool("inverse-polygon")}>⬡</button>
          <button type="button" className="pf-roi-tool" title="恢复默认" onClick={onReset}>↺</button>
        </div>
        {(tool === "polygon" || tool === "inverse-polygon") && draftPoints.length >= 3 ? (
          <button type="button" className="pf-btn pf-btn-sm pf-roi-finish" onClick={finishPolygon}>
            完成多边形
          </button>
        ) : null}
      </div>

      <div
        ref={canvasRef}
        className={`pf-roi-canvas${tool ? " is-drawing" : " is-selecting"}`}
        onPointerDown={handleCanvasPointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={() => setCursorPoint(null)}
      >
        <div
          className={`pf-roi-video${hasStream ? " has-video" : ""}${useRtsp ? " has-rtsp" : ""}`}
          style={
            hasStream
              ? {
                  backgroundImage: background ? `url(${background})` : undefined,
                  backgroundSize: "cover",
                  backgroundPosition: "center",
                }
              : { background }
          }
        >
          {useRtsp ? (
            <RtspLivePreview equipmentId={equipmentId!} embedded large />
          ) : (
            <span className="pf-studio-equip-live-scan" aria-hidden />
          )}
          <span className="pf-studio-equip-live-badge">
            {useRtsp ? "RTSP" : "LIVE"}
          </span>
          <span className="pf-studio-equip-live-time">{liveTime}</span>
        </div>
        <svg className="pf-roi-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          {roi.detection.map((shape) => renderShape(shape, "detection"))}
          {roi.inverse.map((shape) => renderShape(shape, "inverse"))}
          {draftPreview()}
        </svg>
      </div>

      <p className="pf-roi-hint">
        {tool
          ? tool === "rect"
            ? "拖拽绘制矩形检测框"
            : tool === "line"
              ? "点击两点绘制检测线"
              : "逐点点击绘制多边形，完成后点「完成多边形」"
          : selectedId
            ? "已选中框线，可拖动调整；按 Delete 或点「−」删除；点击空白处取消选中"
            : "点「↖」进入选择模式，点击框线选中后可拖动或删除"}
        {!online && !hasStream ? " · 设备离线，画面为演示占位" : ""}
        {useRtsp ? " · RTSP 主码流 H.265 1080p" : " · 请配置 RTSP 地址"}
      </p>
    </div>
  );
}
