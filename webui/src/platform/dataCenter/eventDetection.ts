export type EventDetectionBox = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label?: string;
  confidence?: number;
};

export type EventDetectionFrame = {
  sourceWidth: number;
  sourceHeight: number;
  /** VAIO 解码时间轴上的毫秒位置（image_name），短视频需对 duration 取模。 */
  frameMs?: number;
  /** 相对当前录像文件的秒位置（后端 ffprobe + frame_ms 对齐）。 */
  videoTimeSec?: number;
  /** 检测帧在完整设备录像上的偏移（持续监控窗口起点）。 */
  videoOffsetSec?: number;
  /** 与检测框对齐的静态抓拍 URL。 */
  snapshotUrl?: string;
  /** 抓拍 JPEG 与检测框/判定未对齐（后端 snapshot_mismatch）。 */
  snapshotMismatch?: boolean;
  /** 与抓拍对齐的 LLM 置信度；未对齐时不展示 event value_num。 */
  displayConfidence?: number;
  /** snapshot_llm | vaio_alert_frame */
  judgmentSource?: string;
  /** 判定与框不一致时的说明。 */
  judgmentNote?: string;
  boxes: EventDetectionBox[];
};

export function resolveSnapshotSeekSeconds(
  detection: EventDetectionFrame | null | undefined,
  duration: number,
): number | null {
  if (!Number.isFinite(duration) || duration <= 0) {
    return detection?.videoTimeSec ?? null;
  }
  const maxSeek = Math.max(0, duration - 0.08);
  const videoTimeSec = detection?.videoTimeSec;
  const offsetSec = detection?.videoOffsetSec ?? 0;
  if (videoTimeSec != null && videoTimeSec >= 0) {
    return Math.min(maxSeek, Math.max(0, videoTimeSec + offsetSec));
  }
  const frameMs = detection?.frameMs;
  if (frameMs != null && frameMs > 0) {
    const durationMs = Math.max(1, Math.round(duration * 1000));
    const wrappedMs = frameMs % durationMs;
    return Math.min(maxSeek, Math.max(0, wrappedMs / 1000));
  }
  if (detection?.boxes?.length) {
    return null;
  }
  return Math.min(maxSeek, Math.max(0.5, duration * 0.35));
}

export function parseEventDetection(raw: string | null | undefined): EventDetectionFrame | null {
  if (!raw?.trim()) return null;
  try {
    const data = JSON.parse(raw) as {
      source_width?: number;
      source_height?: number;
      frame_ms?: number;
      video_time_sec?: number;
      video_offset_sec?: number;
      snapshot_url?: string;
      snapshot_mismatch?: boolean;
      display_confidence?: number;
      judgment_note?: string;
      judgment_source?: string;
      boxes?: Array<{
        x?: number;
        y?: number;
        width?: number;
        height?: number;
        label?: string;
        confidence?: number;
      }>;
    };
    const sourceWidth = Number(data.source_width) || 1280;
    const sourceHeight = Number(data.source_height) || 720;
    const snapshotMismatch = Boolean(data.snapshot_mismatch);
    const snapshotUrl = data.snapshot_url?.trim() || undefined;
    const displayConfidenceRaw = Number(data.display_confidence);
    const displayConfidence =
      Number.isFinite(displayConfidenceRaw) && displayConfidenceRaw > 0
        ? displayConfidenceRaw
        : undefined;
    const judgmentNote = data.judgment_note?.trim() || undefined;
    const judgmentSource = data.judgment_source?.trim() || undefined;
    const boxes = (data.boxes ?? [])
      .map((box, index) => {
        const x = Number(box.x);
        const y = Number(box.y);
        const width = Number(box.width);
        const height = Number(box.height);
        if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
          return null;
        }
        const confidence =
          box.confidence == null || Number.isNaN(Number(box.confidence))
            ? undefined
            : Number(box.confidence);
        return {
          id: `box-${index}`,
          x,
          y,
          width,
          height,
          label: box.label?.trim() || undefined,
          confidence,
        } satisfies EventDetectionBox;
      })
      .filter((item): item is EventDetectionBox => item != null);
    if (!boxes.length && !snapshotMismatch && !snapshotUrl) return null;
    const frameMsRaw = Number(data.frame_ms);
    const frameMs =
      Number.isFinite(frameMsRaw) && frameMsRaw > 0 ? Math.round(frameMsRaw) : undefined;
    const videoTimeRaw = Number(data.video_time_sec);
    const videoTimeSec =
      Number.isFinite(videoTimeRaw) && videoTimeRaw >= 0 ? videoTimeRaw : undefined;
    const offsetRaw = Number(data.video_offset_sec);
    const videoOffsetSec =
      Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : undefined;
    return {
      sourceWidth,
      sourceHeight,
      frameMs,
      videoTimeSec,
      videoOffsetSec,
      snapshotUrl,
      snapshotMismatch,
      displayConfidence,
      judgmentNote,
      judgmentSource,
      boxes,
    };
  } catch {
    return null;
  }
}

export function plausibleVideoTimeSec(
  frame: EventDetectionFrame | null | undefined,
): number | undefined {
  if (!frame) return undefined;
  const vts = frame.videoTimeSec;
  if (vts != null && vts >= 0 && vts <= 3600) return vts;
  const fm = frame.frameMs;
  if (fm != null && fm > 0 && fm < 3_600_000) return fm / 1000;
  return undefined;
}

/** 将源坐标映射到 object-fit: contain 的显示区域。 */
export function mapBoxToContainDisplay(
  box: Pick<EventDetectionBox, "x" | "y" | "width" | "height">,
  sourceW: number,
  sourceH: number,
  displayW: number,
  displayH: number,
) {
  const scale = Math.min(displayW / sourceW, displayH / sourceH);
  const renderedW = sourceW * scale;
  const renderedH = sourceH * scale;
  const offsetX = (displayW - renderedW) / 2;
  const offsetY = (displayH - renderedH) / 2;
  return {
    left: offsetX + box.x * scale,
    top: offsetY + box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
    scale,
    offsetX,
    offsetY,
    renderedW,
    renderedH,
  };
}

export function primaryDetectionBox(frame: EventDetectionFrame | null): EventDetectionBox | null {
  if (!frame?.boxes.length) return null;
  return [...frame.boxes].sort(
    (a, b) => (b.confidence ?? 0) * b.width * b.height - (a.confidence ?? 0) * a.width * a.height,
  )[0];
}
