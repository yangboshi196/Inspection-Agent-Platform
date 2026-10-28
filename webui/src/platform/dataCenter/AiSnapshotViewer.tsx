import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  mapBoxToContainDisplay,
  plausibleVideoTimeSec,
  primaryDetectionBox,
  resolveSnapshotSeekSeconds,
  type EventDetectionFrame,
} from "./eventDetection";

type Props = {
  videoUrl: string;
  snapshotUrl?: string;
  capturedAt: string;
  aiLabel?: string;
  confidence?: number;
  detection: EventDetectionFrame | null;
  eventId: string;
};

export function AiSnapshotViewer({
  videoUrl,
  snapshotUrl,
  capturedAt,
  aiLabel,
  confidence,
  detection,
  eventId,
}: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  const zoomViewportRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const zoomVideoRef = useRef<HTMLVideoElement>(null);
  const snapshotImgRef = useRef<HTMLImageElement>(null);
  const zoomSnapshotRef = useRef<HTMLImageElement>(null);
  const lightboxStageRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [zoomSize, setZoomSize] = useState({ width: 0, height: 0 });
  const [lightboxMediaSize, setLightboxMediaSize] = useState({ width: 0, height: 0 });
  const [zoomEnabled, setZoomEnabled] = useState(false);
  const [activeBoxId, setActiveBoxId] = useState<string | null>(null);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [snapshotLoadFailed, setSnapshotLoadFailed] = useState(false);

  const useSnapshot = Boolean(snapshotUrl?.trim());
  const mediaSrc = useSnapshot ? snapshotUrl : videoUrl;
  const canLightbox = Boolean(mediaSrc?.trim());
  const displayVideoTimeSec = plausibleVideoTimeSec(detection);
  const snapshotMismatch = Boolean(detection?.snapshotMismatch);
  const overlayConfidence =
    detection?.displayConfidence != null && !snapshotMismatch
      ? detection.displayConfidence
      : snapshotMismatch
        ? undefined
        : confidence;
  const toolbarMeta = detection?.boxes.length
    ? `检出 ${detection.boxes.length} 个目标${
        displayVideoTimeSec != null ? ` · 检测帧 ${displayVideoTimeSec.toFixed(1)}s` : ""
      }${detection.judgmentSource === "vaio_alert_frame" ? " · 告警同帧" : useSnapshot ? " · 取证抓拍" : ""}`
    : snapshotMismatch
      ? "抓拍与检测未对齐"
      : "暂无检测框数据";

  const focusBox = useMemo(() => {
    if (!detection) return null;
    const picked = detection.boxes.find((box) => box.id === activeBoxId);
    return picked ?? primaryDetectionBox(detection);
  }, [activeBoxId, detection]);

  useEffect(() => {
    setActiveBoxId(null);
    setZoomEnabled(true);
    setLightboxOpen(false);
    setSnapshotLoadFailed(false);
  }, [eventId, snapshotUrl]);

  useEffect(() => {
    if (!lightboxOpen) {
      document.body.style.overflow = "";
      return;
    }
    document.body.style.overflow = "hidden";
    document.body.classList.add("pf-usr-event-lightbox-open");
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightboxOpen(false);
    };
    window.addEventListener("keydown", onKey);
    const el = lightboxStageRef.current;
    if (el) {
      setLightboxMediaSize({ width: el.clientWidth, height: el.clientHeight });
    }
    const stageEl = lightboxStageRef.current;
    const onResize = () => {
      if (!stageEl) return;
      setLightboxMediaSize({ width: stageEl.clientWidth, height: stageEl.clientHeight });
    };
    const observer = stageEl ? new ResizeObserver(onResize) : null;
    if (observer && stageEl) observer.observe(stageEl);
    return () => {
      document.body.style.overflow = "";
      document.body.classList.remove("pf-usr-event-lightbox-open");
      window.removeEventListener("keydown", onKey);
      observer?.disconnect();
    };
  }, [lightboxOpen]);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const update = () => {
      setStageSize({ width: el.clientWidth, height: el.clientHeight });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = zoomViewportRef.current;
    if (!el) return;
    const update = () => {
      setZoomSize({ width: el.clientWidth, height: el.clientHeight });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [zoomEnabled, detection]);

  useEffect(() => {
    if (useSnapshot) return;
    const el = videoRef.current;
    if (!el) return;
    const freezeFrame = () => {
      const target = resolveSnapshotSeekSeconds(detection, el.duration || 0);
      if (target == null) return;
      el.currentTime = target;
      el.pause();
      if (zoomVideoRef.current) {
        zoomVideoRef.current.currentTime = target;
        zoomVideoRef.current.pause();
      }
    };
    el.addEventListener("loadedmetadata", freezeFrame);
    el.addEventListener("loadeddata", freezeFrame);
    el.load();
    return () => {
      el.removeEventListener("loadedmetadata", freezeFrame);
      el.removeEventListener("loadeddata", freezeFrame);
    };
  }, [videoUrl, eventId, detection, useSnapshot]);

  useEffect(() => {
    if (useSnapshot) return;
    const main = videoRef.current;
    const zoom = zoomVideoRef.current;
    if (!main || !zoom) return;
    const sync = () => {
      zoom.currentTime = main.currentTime;
      zoom.pause();
    };
    main.addEventListener("seeked", sync);
    zoom.addEventListener("loadedmetadata", sync);
    zoom.addEventListener("loadeddata", sync);
    return () => {
      main.removeEventListener("seeked", sync);
      zoom.removeEventListener("loadedmetadata", sync);
      zoom.removeEventListener("loadeddata", sync);
    };
  }, [videoUrl, eventId, detection, useSnapshot]);

  const mappedBoxes = useMemo(() => {
    if (!detection || stageSize.width <= 0 || stageSize.height <= 0) return [];
    return detection.boxes.map((box) => ({
      box,
      rect: mapBoxToContainDisplay(
        box,
        detection.sourceWidth,
        detection.sourceHeight,
        stageSize.width,
        stageSize.height,
      ),
    }));
  }, [detection, stageSize.height, stageSize.width]);

  const mappedLightboxBoxes = useMemo(() => {
    if (!detection || lightboxMediaSize.width <= 0 || lightboxMediaSize.height <= 0) return [];
    return detection.boxes.map((box) => ({
      box,
      rect: mapBoxToContainDisplay(
        box,
        detection.sourceWidth,
        detection.sourceHeight,
        lightboxMediaSize.width,
        lightboxMediaSize.height,
      ),
    }));
  }, [detection, lightboxMediaSize.height, lightboxMediaSize.width]);

  const zoomStyle = useMemo(() => {
    if (!detection || !focusBox || zoomSize.width <= 0 || zoomSize.height <= 0) return null;
    const mag = Math.min(
      4,
      Math.max(
        1.6,
        Math.min(
          detection.sourceWidth / Math.max(focusBox.width, 48),
          detection.sourceHeight / Math.max(focusBox.height, 48),
        ) * 0.9,
      ),
    );
    const baseScale = Math.min(
      zoomSize.width / detection.sourceWidth,
      zoomSize.height / detection.sourceHeight,
    );
    const scale = baseScale * mag;
    const cx = focusBox.x + focusBox.width / 2;
    const cy = focusBox.y + focusBox.height / 2;
    return {
      width: `${detection.sourceWidth}px`,
      height: `${detection.sourceHeight}px`,
      transform: `translate(${zoomSize.width / 2 - cx * scale}px, ${zoomSize.height / 2 - cy * scale}px) scale(${scale})`,
      transformOrigin: "0 0",
    };
  }, [detection, focusBox, zoomSize.height, zoomSize.width]);

  const showTargetZoom = Boolean(zoomEnabled && detection && focusBox && zoomStyle);

  const openLightbox = () => {
    if (!canLightbox) return;
    setLightboxOpen(true);
  };

  const onStageClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest(".pf-usr-event-detect-box")) return;
    if (target.closest(".pf-usr-event-snap-stage-zoom")) return;
    openLightbox();
  };

  return (
    <div className="pf-usr-event-snapshots">
      <div className="pf-usr-event-snap-toolbar">
        <span className="pf-usr-event-snap-toolbar-meta">
          {toolbarMeta}
          {detection?.judgmentNote && snapshotMismatch ? (
            <span className="pf-usr-event-snap-toolbar-warn"> · {detection.judgmentNote}</span>
          ) : null}
        </span>
        <div className="pf-usr-event-snap-toolbar-actions">
          {detection?.boxes.length ? (
            <button
              type="button"
              className={`pf-usr-event-snap-tool-btn${zoomEnabled ? " is-active" : ""}`}
              onClick={() => setZoomEnabled((v) => !v)}
            >
              {zoomEnabled ? "关闭目标放大" : "放大目标"}
            </button>
          ) : null}
          {canLightbox ? (
            <button type="button" className="pf-usr-event-snap-tool-btn" onClick={openLightbox}>
              放大查看
            </button>
          ) : null}
        </div>
      </div>

      <div className="pf-usr-event-snap-layout">
        <div
          ref={stageRef}
          className={`pf-usr-event-snap-main pf-usr-event-snap-main-detect${canLightbox ? " is-clickable" : ""}`}
          onClick={onStageClick}
        >
          {useSnapshot ? (
            snapshotLoadFailed ? (
              <div className="pf-usr-event-snap-load-fail">
                抓拍加载失败，请检查摄像机连接或稍后重试
              </div>
            ) : (
              <img
                ref={snapshotImgRef}
                className="pf-usr-event-media-video pf-usr-event-media-video-contain"
                src={snapshotUrl}
                alt="AI 检测抓拍"
                onLoad={() => {
                  setSnapshotLoadFailed(false);
                  const el = stageRef.current;
                  if (el) {
                    setStageSize({ width: el.clientWidth, height: el.clientHeight });
                  }
                }}
                onError={() => setSnapshotLoadFailed(true)}
              />
            )
          ) : (
            <video
              ref={videoRef}
              className="pf-usr-event-media-video pf-usr-event-media-video-contain"
              src={videoUrl}
              muted
              playsInline
              preload="metadata"
            />
          )}
          {mappedBoxes.length ? (
            <div className="pf-usr-event-detect-layer" aria-hidden={!mappedBoxes.length}>
              {mappedBoxes.map(({ box, rect }) => {
                const active = focusBox?.id === box.id;
                const conf =
                  box.confidence != null && box.confidence > 0
                    ? `${Math.round(box.confidence > 1 ? box.confidence : box.confidence * 100)}%`
                    : null;
                return (
                  <button
                    key={box.id}
                    type="button"
                    className={`pf-usr-event-detect-box${active ? " is-active" : ""}`}
                    style={{
                      left: `${rect.left}px`,
                      top: `${rect.top}px`,
                      width: `${rect.width}px`,
                      height: `${rect.height}px`,
                    }}
                    onClick={() => {
                      setActiveBoxId(box.id);
                      setZoomEnabled(true);
                    }}
                    aria-label={box.label ? `检测目标 ${box.label}` : "检测目标"}
                  >
                    {(box.label || conf) && (
                      <span className="pf-usr-event-detect-box-label">
                        {[box.label, conf].filter(Boolean).join(" · ")}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : null}
          {showTargetZoom ? (
            <div className="pf-usr-event-snap-zoom-mask">
              <div ref={zoomViewportRef} className="pf-usr-event-snap-zoom-viewport">
                {useSnapshot ? (
                  <img
                    ref={zoomSnapshotRef}
                    className="pf-usr-event-snap-zoom-video"
                    style={zoomStyle ?? undefined}
                    src={snapshotUrl}
                    alt=""
                  />
                ) : (
                  <video
                    ref={zoomVideoRef}
                    className="pf-usr-event-snap-zoom-video"
                    style={zoomStyle ?? undefined}
                    src={videoUrl}
                    muted
                    playsInline
                    preload="metadata"
                  />
                )}
              </div>
              <span className="pf-usr-event-snap-zoom-badge">目标放大</span>
            </div>
          ) : null}
          {canLightbox ? (
            <button
              type="button"
              className="pf-usr-event-snap-stage-zoom"
              aria-label="放大查看"
              onClick={(e) => {
                e.stopPropagation();
                openLightbox();
              }}
            >
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden>
                <path
                  fill="currentColor"
                  d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9zM19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V5h14v14z"
                />
              </svg>
            </button>
          ) : null}
          {aiLabel ? (
            <div className="pf-usr-event-snap-ai">
              <span className="pf-usr-event-snap-ai-label">AI 分析</span>
              <strong>{aiLabel}</strong>
              {overlayConfidence != null ? (
                <em>{Math.round(overlayConfidence * 100)}% 置信度</em>
              ) : snapshotMismatch ? (
                <em className="pf-usr-event-snap-ai-warn">未对齐</em>
              ) : null}
            </div>
          ) : null}
          <span className="pf-usr-event-snap-time">{capturedAt}</span>
        </div>
      </div>

      {lightboxOpen && canLightbox
        ? createPortal(
            <div
              className="pf-usr-event-snap-lightbox"
              role="dialog"
              aria-modal="true"
              aria-label="放大查看抓拍"
              onClick={() => setLightboxOpen(false)}
            >
              <button
                type="button"
                className="pf-usr-event-snap-lightbox-close"
                aria-label="关闭"
                onClick={() => setLightboxOpen(false)}
              >
                ×
              </button>
              <div
                className="pf-usr-event-snap-lightbox-body"
                onClick={(e) => e.stopPropagation()}
              >
                <div ref={lightboxStageRef} className="pf-usr-event-snap-lightbox-stage">
                  {useSnapshot ? (
                    <img
                      className="pf-usr-event-snap-lightbox-media"
                      src={snapshotUrl}
                      alt="AI 抓拍放大"
                      onLoad={() => {
                        const el = lightboxStageRef.current;
                        if (el) {
                          setLightboxMediaSize({ width: el.clientWidth, height: el.clientHeight });
                        }
                      }}
                    />
                  ) : (
                    <video
                      className="pf-usr-event-snap-lightbox-media"
                      src={videoUrl}
                      muted
                      playsInline
                      autoPlay
                      loop
                    />
                  )}
                  {mappedLightboxBoxes.length ? (
                    <div
                      className="pf-usr-event-detect-layer pf-usr-event-detect-layer-lightbox"
                      aria-hidden
                    >
                      {mappedLightboxBoxes.map(({ box, rect }) => (
                        <span
                          key={`lb-${box.id}`}
                          className="pf-usr-event-detect-box is-static"
                          style={{
                            left: `${rect.left}px`,
                            top: `${rect.top}px`,
                            width: `${rect.width}px`,
                            height: `${rect.height}px`,
                          }}
                        />
                      ))}
                    </div>
                  ) : null}
                </div>
                {mappedLightboxBoxes.length && detection ? (
                  <div className="pf-usr-event-snap-lightbox-hint">
                    已检出 {detection.boxes.length} 个目标
                  </div>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
