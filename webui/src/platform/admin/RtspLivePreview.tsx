import { useEffect, useRef, useState } from "react";
import { MediaLivePlayer } from "./MediaLivePlayer";
import { GO2RTC_LIVE_DEFAULTS, type EquipmentLiveStreamOptions } from "../equipmentApi";

type LivePlayMode = "webrtc" | "mjpeg" | "snapshot" | "mp4" | "hls" | "flv" | "none";

/** RTSP 实时预览：go2rtc WebRTC 或 RTSP 快照轮询。 */
export function RtspLivePreview({
  equipmentId,
  paused = false,
  large = false,
  embedded = false,
  onZoom,
  stream: _streamProp = GO2RTC_LIVE_DEFAULTS.stream,
  quality: _qualityProp = GO2RTC_LIVE_DEFAULTS.quality,
  previewRtsp,
}: {
  equipmentId: string;
  paused?: boolean;
  large?: boolean;
  embedded?: boolean;
  onZoom?: () => void;
  refreshMs?: number;
  stream?: EquipmentLiveStreamOptions["stream"];
  quality?: EquipmentLiveStreamOptions["quality"];
  previewRtsp?: string;
}) {
  const quality = "hd";
  const stream = "main";
  const wrapRef = useRef<HTMLDivElement>(null);
  const [connecting, setConnecting] = useState(true);
  const [error, setError] = useState("");
  const [playMode, setPlayMode] = useState<LivePlayMode>("none");

  useEffect(() => {
    setConnecting(true);
    setError("");
    setPlayMode("none");
  }, [equipmentId, previewRtsp, stream, quality, paused]);

  const handleZoom = () => {
    if (!large && onZoom) {
      onZoom();
      return;
    }
    const el = wrapRef.current;
    if (el?.requestFullscreen) {
      void el.requestFullscreen();
    }
  };

  if (paused || !equipmentId) return null;

  const zoomLabel = large ? "全屏" : "放大";
  const statusText =
    playMode === "webrtc"
      ? "正在连接 WebRTC（H.265 1080p）…"
      : playMode === "mjpeg"
        ? "正在加载 MJPEG 实时流…"
        : playMode === "snapshot"
          ? "正在加载实时画面…"
          : "正在连接…";

  return (
    <div ref={wrapRef} className={`pf-dev-monitor-live-wrap${embedded ? " is-embedded" : ""}`}>
      <MediaLivePlayer
        equipmentId={equipmentId}
        paused={paused}
        stream={stream}
        quality={quality}
        previewRtsp={previewRtsp}
        preferMjpeg
        skipLivePlayProbe={embedded}
        onModeChange={setPlayMode}
        onConnected={() => {
          setConnecting(false);
          setError("");
        }}
        onError={(msg) => {
          setConnecting(false);
          const hint =
            msg.includes("SETUP") || msg.includes("mse")
              ? "摄像机 RTSP 连接数已满或码流冲突，请关闭多余预览/分析后重试"
              : msg.includes("无法从平台服务器连接") || msg.includes("网段")
                ? `${msg}（VLC 在本机能播，不代表平台服务器能连到摄像机，请在服务器上测试 RTSP）`
                : msg || "无法连接 RTSP，请检查地址、账号密码与网络";
          setError(hint);
        }}
      />
      {!embedded ? (
        <button
          type="button"
          className="pf-dev-monitor-live-zoom"
          title={zoomLabel}
          aria-label={zoomLabel}
          onClick={(e) => {
            e.stopPropagation();
            handleZoom();
          }}
        >
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
            <path
              fill="currentColor"
              d="M15.5 14h-.79l-.28-.27a6.5 6.5 0 1 0-.7.7l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9zM19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V5h14v14z"
            />
          </svg>
          <span>{zoomLabel}</span>
        </button>
      ) : null}
      {connecting && !error && !embedded ? (
        <span className="pf-dev-monitor-live-status">{statusText}</span>
      ) : null}
      {error ? <span className="pf-dev-monitor-live-status is-error">{error}</span> : null}
    </div>
  );
}
