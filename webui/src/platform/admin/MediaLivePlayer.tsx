import { useEffect, useRef, useState } from "react";
import Player from "xgplayer";
import FlvPlugin from "xgplayer-flv";
import Hls from "hls.js";
import "xgplayer/dist/index.min.css";
import { apiFetch, readApiError } from "../../api";
import {
  GO2RTC_LIVE_DEFAULTS,
  equipmentLiveMjpegUrl,
  equipmentLiveSnapshotUrl,
  type EquipmentLiveStreamOptions,
} from "../equipmentApi";
import { consumeMultipartMjpeg } from "./mjpegStream";
import { syncAuthCookie, getAuthToken } from "../auth";
import {
  fetchEquipmentLivePlay,
  go2rtcStreamHtmlUrl,
  normalizeMjpegLiveUrl,
  resolvePlatformMediaUrl,
  type MediaPlayInfo,
} from "../mediaLiveApi";

const CONNECT_TIMEOUT_MS = 12000;
const WEBRTC_TRY_MS = 4000;
const IFRAME_LOAD_HINT_MS = 1500;
const SNAPSHOT_MIN_GAP_MS = 200;
const MJPEG_FPS = 15;

type PlayMode = "webrtc" | "mjpeg" | "snapshot" | "mp4" | "hls" | "flv" | "none";

/** multipart MJPEG 连续流（10–15fps） */
function MjpegStreamPlayer({
  url,
  className,
  onFrame,
  onError,
}: {
  url: string;
  className?: string;
  onFrame?: () => void;
  onError?: (msg: string) => void;
}) {
  const [imgSrc, setImgSrc] = useState("");
  const blobRef = useRef("");
  const framedRef = useRef(false);
  const onFrameRef = useRef(onFrame);
  const onErrorRef = useRef(onError);
  onFrameRef.current = onFrame;
  onErrorRef.current = onError;

  useEffect(() => {
    let cancelled = false;
    const ac = new AbortController();
    framedRef.current = false;
    const token = getAuthToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, ms);
      });

    const run = async () => {
      for (let attempt = 0; attempt < 4 && !cancelled; attempt += 1) {
        const attemptAc = new AbortController();
        const onParentAbort = () => attemptAc.abort();
        ac.signal.addEventListener("abort", onParentAbort, { once: true });
        try {
          await consumeMultipartMjpeg(url, {
            signal: attemptAc.signal,
            headers,
            onFrame: (blob) => {
              if (cancelled) return;
              const next = URL.createObjectURL(blob);
              if (blobRef.current) URL.revokeObjectURL(blobRef.current);
              blobRef.current = next;
              setImgSrc(next);
              if (!framedRef.current) {
                framedRef.current = true;
                onFrameRef.current?.();
              }
            },
          });
          return;
        } catch (e) {
          if (cancelled || ac.signal.aborted) return;
          if (attempt < 3) {
            await sleep(600 * (attempt + 1));
            continue;
          }
          onErrorRef.current?.(e instanceof Error ? e.message : "MJPEG 流失败");
        } finally {
          ac.signal.removeEventListener("abort", onParentAbort);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
      ac.abort();
      if (blobRef.current) URL.revokeObjectURL(blobRef.current);
      blobRef.current = "";
    };
  }, [url]);

  return (
    <img
      className={className ?? "pf-dev-monitor-live-img pf-dev-monitor-mjpeg-stream"}
      src={imgSrc}
      alt="实时预览"
    />
  );
}

/** RTSP 单帧轮询（MJPEG 不可用时的兜底，尽量 2–3fps） */
function SnapshotPollPlayer({
  equipmentId,
  stream,
  quality,
  previewRtsp,
  className,
  onFrame,
  onError,
}: {
  equipmentId: string;
  stream?: EquipmentLiveStreamOptions["stream"];
  quality?: EquipmentLiveStreamOptions["quality"];
  previewRtsp?: string;
  className?: string;
  onFrame?: () => void;
  onError?: (msg: string) => void;
}) {
  const [imgSrc, setImgSrc] = useState("");
  const blobRef = useRef("");
  const onFrameRef = useRef(onFrame);
  const onErrorRef = useRef(onError);
  onFrameRef.current = onFrame;
  onErrorRef.current = onError;

  useEffect(() => {
    let cancelled = false;
    const opts: EquipmentLiveStreamOptions = { stream, quality, previewRtsp };

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, ms);
      });

    const loop = async () => {
      while (!cancelled) {
        const started = Date.now();
        try {
          const res = await apiFetch(equipmentLiveSnapshotUrl(equipmentId, opts));
          if (!res.ok) {
            const msg = await readApiError(res);
            throw new Error(msg || `快照 ${res.status}`);
          }
          const blob = await res.blob();
          if (cancelled || blob.size < 256) continue;
          const next = URL.createObjectURL(blob);
          if (blobRef.current) URL.revokeObjectURL(blobRef.current);
          blobRef.current = next;
          setImgSrc(next);
          onFrameRef.current?.();
        } catch (e) {
          if (!cancelled) {
            onErrorRef.current?.(e instanceof Error ? e.message : "快照拉流失败");
            await sleep(1200);
          }
          continue;
        }
        const elapsed = Date.now() - started;
        const wait = Math.max(SNAPSHOT_MIN_GAP_MS, 450 - elapsed);
        await sleep(wait);
      }
    };

    void loop();
    return () => {
      cancelled = true;
      if (blobRef.current) URL.revokeObjectURL(blobRef.current);
      blobRef.current = "";
    };
  }, [equipmentId, stream, quality, previewRtsp]);

  return (
    <img
      className={className ?? "pf-dev-monitor-live-img pf-dev-monitor-mjpeg-stream"}
      src={imgSrc}
      alt={`${equipmentId} 实时预览`}
    />
  );
}

/**
 * go2rtc：WebRTC H.265 1080p；失败或未就绪时 RTSP 快照轮询（可靠出画）。
 */
export function MediaLivePlayer({
  equipmentId,
  paused = false,
  className,
  stream = GO2RTC_LIVE_DEFAULTS.stream,
  quality = GO2RTC_LIVE_DEFAULTS.quality,
  previewRtsp,
  preferMjpeg = false,
  skipLivePlayProbe = false,
  onConnected,
  onError,
  onModeChange,
}: {
  equipmentId: string;
  paused?: boolean;
  className?: string;
  stream?: EquipmentLiveStreamOptions["stream"];
  quality?: EquipmentLiveStreamOptions["quality"];
  previewRtsp?: string;
  /** 监控页优先 MJPEG，避免 WebRTC 占连接导致间歇黑屏 */
  preferMjpeg?: boolean;
  /** 跳过 live/play（ROI 弹窗等仅需 MJPEG，避免 play 被取消后一直加载） */
  skipLivePlayProbe?: boolean;
  onConnected?: () => void;
  onError?: (msg: string) => void;
  onModeChange?: (mode: PlayMode) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<Player | null>(null);
  const hlsRef = useRef<Hls | null>(null);
  const timerRef = useRef<number | null>(null);
  const connectedRef = useRef(false);
  const [playInfo, setPlayInfo] = useState<MediaPlayInfo | null>(null);
  const [mode, setMode] = useState<PlayMode>("none");

  const liveOpts: EquipmentLiveStreamOptions = { stream, quality, previewRtsp };

  const setPlayMode = (next: PlayMode) => {
    setMode(next);
    onModeChange?.(next);
  };

  const clearTimer = () => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const markConnected = () => {
    if (connectedRef.current) return;
    connectedRef.current = true;
    clearTimer();
    onConnected?.();
  };

  const fail = (msg: string, next?: PlayMode) => {
    if (next) {
      setPlayMode(next);
      return;
    }
    onError?.(msg);
  };

  const destroyPlayers = () => {
    clearTimer();
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
    if (playerRef.current) {
      playerRef.current.destroy();
      playerRef.current = null;
    }
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.removeAttribute("src");
      v.load();
    }
  };

  useEffect(() => {
    if (paused || !equipmentId) {
      setPlayInfo(null);
      setPlayMode("none");
      return;
    }
    const ac = new AbortController();
    let cancelled = false;
    connectedRef.current = false;
    setPlayMode("none");
    syncAuthCookie(getAuthToken());

    // 配置页未保存 RTSP：直接 MJPEG，跳过 live/play（避免长阻塞与重复失败）
    if (previewRtsp?.trim() || skipLivePlayProbe || preferMjpeg) {
      setPlayInfo({
        backend: "go2rtc",
        producer_ready: false,
        mjpeg: equipmentLiveMjpegUrl(equipmentId, MJPEG_FPS, { previewRtsp }),
      });
      setPlayMode("mjpeg");
      return;
    }

    fetchEquipmentLivePlay(equipmentId, liveOpts, ac.signal)
      .then((info) => {
        if (cancelled) return;
        setPlayInfo(info);
        if (preferMjpeg || previewRtsp?.trim()) {
          setPlayMode("mjpeg");
          return;
        }
        const go2rtcOk =
          info.backend === "go2rtc" &&
          info.stream_key &&
          info.producer_ready === true;
        if (go2rtcOk) {
          setPlayMode("webrtc");
        } else if (info.mjpeg || info.backend === "go2rtc") {
          setPlayMode("mjpeg");
        } else if (info.flv) {
          setPlayMode("flv");
        } else {
          setPlayMode("snapshot");
        }
      })
      .catch((e) => {
        if (cancelled || ac.signal.aborted) return;
        fail(e instanceof Error ? e.message : "获取直播信息失败", "snapshot");
      });
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [equipmentId, paused, stream, quality, previewRtsp, preferMjpeg, skipLivePlayProbe]);

  useEffect(() => {
    if (paused || mode !== "webrtc" || !playInfo?.stream_key) return;
    connectedRef.current = false;
    const hintTimer = window.setTimeout(() => onConnected?.(), IFRAME_LOAD_HINT_MS);
    const fallbackTimer = window.setTimeout(() => {
      if (connectedRef.current) return;
      onError?.("WebRTC 未出画，已切换 MJPEG 预览");
      setPlayMode("mjpeg");
    }, WEBRTC_TRY_MS);
    return () => {
      window.clearTimeout(hintTimer);
      window.clearTimeout(fallbackTimer);
    };
  }, [paused, mode, playInfo?.stream_key, onConnected, onError]);

  useEffect(() => {
    if (
      paused ||
      !playInfo ||
      mode === "none" ||
      mode === "mjpeg" ||
      mode === "snapshot" ||
      mode === "webrtc"
    ) {
      destroyPlayers();
      return;
    }

    let cancelled = false;
    destroyPlayers();
    connectedRef.current = false;

    const scheduleTimeout = (next: PlayMode) => {
      clearTimer();
      timerRef.current = window.setTimeout(() => {
        if (!cancelled && !connectedRef.current) {
          setPlayMode(next);
        }
      }, CONNECT_TIMEOUT_MS);
    };

    const tryMp4 = async () => {
      const url = playInfo.mp4 ? resolvePlatformMediaUrl(playInfo.mp4) : "";
      const v = videoRef.current;
      if (!url || !v) {
        setPlayMode("hls");
        return;
      }
      v.muted = true;
      v.playsInline = true;
      v.autoplay = true;
      v.src = url;
      const onOk = () => {
        if (!cancelled) markConnected();
      };
      v.addEventListener("playing", onOk, { once: true });
      v.addEventListener("canplay", onOk, { once: true });
      v.addEventListener(
        "error",
        () => {
          if (!cancelled && !connectedRef.current) setPlayMode("hls");
        },
        { once: true },
      );
      scheduleTimeout("hls");
      try {
        await v.play();
      } catch {
        /* autoplay */
      }
    };

    const tryHls = () => {
      const url = playInfo.hls ? resolvePlatformMediaUrl(playInfo.hls) : "";
      const v = videoRef.current;
      if (!url || !v) {
        setPlayMode("snapshot");
        return;
      }
      if (Hls.isSupported()) {
        const hls = new Hls({ liveDurationInfinity: true, lowLatencyMode: true });
        hlsRef.current = hls;
        hls.loadSource(url);
        hls.attachMedia(v);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          void v.play().catch(() => undefined);
        });
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (!cancelled && !connectedRef.current && data.fatal) setPlayMode("snapshot");
        });
        v.addEventListener("playing", () => markConnected(), { once: true });
        scheduleTimeout("snapshot");
        return;
      }
      if (v.canPlayType("application/vnd.apple.mpegurl")) {
        v.src = url;
        v.addEventListener("playing", () => markConnected(), { once: true });
        v.addEventListener("error", () => setPlayMode("snapshot"), { once: true });
        scheduleTimeout("snapshot");
        void v.play().catch(() => undefined);
        return;
      }
      setPlayMode("snapshot");
    };

    const tryFlv = () => {
      const el = containerRef.current;
      const url = playInfo.flv ? resolvePlatformMediaUrl(playInfo.flv) : "";
      if (!el || !url || el.clientWidth < 8 || el.clientHeight < 8) {
        setPlayMode("snapshot");
        return;
      }
      const player = new Player({
        el,
        url,
        isLive: true,
        autoplay: true,
        autoplayMuted: true,
        playsinline: true,
        width: el.clientWidth,
        height: el.clientHeight,
        fluid: false,
        fitVideoSize: "fixWidth",
        plugins: [FlvPlugin],
        lang: "zh-cn",
        ignores: ["playbackrate", "time", "definition"],
        flv: {
          retryCount: 2,
          retryDelay: 2000,
          loadTimeout: CONNECT_TIMEOUT_MS,
        },
      });
      playerRef.current = player;
      player.on("playing", () => markConnected());
      player.on("play", () => markConnected());
      player.on("canplay", () => markConnected());
      player.on("error", () => {
        if (!cancelled && !connectedRef.current) setPlayMode("snapshot");
      });
      scheduleTimeout("snapshot");
    };

    if (mode === "mp4") {
      void tryMp4();
    } else if (mode === "hls") {
      tryHls();
    } else if (mode === "flv") {
      requestAnimationFrame(() => {
        if (!cancelled) tryFlv();
      });
    }

    return () => {
      cancelled = true;
      destroyPlayers();
    };
  }, [paused, playInfo, mode]);

  if (paused || !equipmentId) return null;

  if (mode === "webrtc" && playInfo?.stream_key) {
    const src = go2rtcStreamHtmlUrl(playInfo.stream_key);
    return (
      <iframe
        className={className ?? "pf-dev-monitor-live-iframe"}
        src={src}
        title={`${equipmentId} H.265 实时预览`}
        allow="autoplay; fullscreen; microphone; camera"
        onLoad={() => markConnected()}
      />
    );
  }

  const mjpegStreamUrl = normalizeMjpegLiveUrl(
    playInfo?.mjpeg
      ? playInfo.mjpeg.includes("fps=")
        ? playInfo.mjpeg
        : `${playInfo.mjpeg}${playInfo.mjpeg.includes("?") ? "&" : "?"}fps=${MJPEG_FPS}`
      : equipmentLiveMjpegUrl(equipmentId, MJPEG_FPS, { previewRtsp }),
  );

  if (mode === "mjpeg") {
    return (
      <MjpegStreamPlayer
        url={mjpegStreamUrl}
        className={className}
        onFrame={() => markConnected()}
        onError={(msg) => {
          onError?.(msg);
          setPlayMode("snapshot");
        }}
      />
    );
  }

  if (mode === "snapshot") {
    return (
      <SnapshotPollPlayer
        equipmentId={equipmentId}
        stream={stream}
        quality={quality}
        previewRtsp={previewRtsp}
        className={className}
        onFrame={() => markConnected()}
        onError={(msg) => onError?.(msg)}
      />
    );
  }

  if (mode === "flv") {
    return <div ref={containerRef} className={className ?? "pf-dev-monitor-live-player"} />;
  }

  return (
    <video
      ref={videoRef}
      className={className ?? "pf-dev-monitor-live-video"}
      muted
      playsInline
      autoPlay
      controls
    />
  );
}
