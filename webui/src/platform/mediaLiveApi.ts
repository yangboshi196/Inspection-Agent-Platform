import { apiBase, apiFetch } from "../api";
import { mainHdLiveQueryParams, type EquipmentLiveStreamOptions } from "./equipmentApi";

export type MediaBackendStatus = {
  backend: string;
  go2rtc_api: string;
  go2rtc_alive: boolean;
};

export type MediaPlayInfo = {
  backend: "go2rtc" | "legacy" | string;
  stream_key?: string;
  stream_mode?: string;
  quality?: string;
  webrtc?: string | null;
  hls?: string | null;
  flv?: string | null;
  mp4?: string | null;
  mjpeg?: string | null;
  snapshot?: string | null;
  rtsp_internal?: string | null;
  rtsp_source?: string;
  producer_ready?: boolean;
  producer_hint?: string;
};

function appendLiveAuth(params: URLSearchParams) {
  try {
    const token = localStorage.getItem("SIA_auth_token");
    if (token) params.set("access_token", token);
  } catch {
    /* ignore */
  }
}

export function equipmentLivePlayPath(
  equipmentId: string,
  options?: EquipmentLiveStreamOptions,
): string {
  const params = mainHdLiveQueryParams();
  if (options?.previewRtsp?.trim()) params.set("preview_rtsp", options.previewRtsp.trim());
  appendLiveAuth(params);
  const qs = params.toString();
  return `${apiBase()}/api/equipment/${encodeURIComponent(equipmentId)}/live/play${qs ? `?${qs}` : ""}`;
}

/** MJPEG 播放地址强制主码流 1080p（忽略 stream=sub / quality=preview）。 */
export function normalizeMjpegLiveUrl(path: string): string {
  if (!path) return "";
  const resolved = resolvePlatformMediaUrl(path);
  try {
    const u = new URL(resolved, typeof window !== "undefined" ? window.location.origin : "http://localhost");
    u.searchParams.set("stream", "main");
    u.searchParams.set("quality", "hd");
    return u.toString();
  } catch {
    const sep = resolved.includes("?") ? "&" : "?";
    return `${resolved}${sep}stream=main&quality=hd`;
  }
}

export function resolvePlatformMediaUrl(path: string): string {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const base = apiBase().replace(/\/$/, "");
  const rel = path.startsWith("/") ? path : `/${path}`;
  const url = `${base}${rel}`;
  try {
    const token = localStorage.getItem("SIA_auth_token");
    if (!token) return url;
    const u = new URL(url, window.location.origin);
    if (!u.searchParams.has("access_token")) {
      u.searchParams.set("access_token", token);
    }
    return u.toString();
  } catch {
    return url;
  }
}

export async function fetchMediaStatus(): Promise<MediaBackendStatus> {
  const res = await apiFetch(`${apiBase()}/api/media/status`);
  if (!res.ok) throw new Error(`媒体服务状态 ${res.status}`);
  return (await res.json()) as MediaBackendStatus;
}

export async function fetchEquipmentLivePlay(
  equipmentId: string,
  options?: EquipmentLiveStreamOptions,
  signal?: AbortSignal,
): Promise<MediaPlayInfo> {
  const res = await apiFetch(equipmentLivePlayPath(equipmentId, options), { signal });
  if (!res.ok) throw new Error(`直播信息 ${res.status}`);
  return (await res.json()) as MediaPlayInfo;
}

export function go2rtcStreamHtmlUrl(streamKey: string): string {
  // H.265 主码流优先 WebRTC；MSE(fMP4) 易触发 RTSP SETUP 冲突与 wrong response on SETUP
  const params = new URLSearchParams({ src: streamKey, mode: "webrtc" });
  appendLiveAuth(params);
  return `${apiBase()}/api/media/go2rtc/stream.html?${params}`;
}
