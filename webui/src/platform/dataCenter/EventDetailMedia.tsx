import { useState } from "react";
import type { DataCenterEvent } from "./dataCenterMock";
import { AiSnapshotViewer } from "./AiSnapshotViewer";
import { EventFlvLiveStage } from "./EventFlvLiveStage";

type MediaTab = "snapshot" | "live";

const TABS: Array<{ id: MediaTab; label: string }> = [
  { id: "snapshot", label: "AI 抓拍" },
  { id: "live", label: "实时视频" },
];

type Props = {
  event: DataCenterEvent;
};

export function EventDetailMedia({ event }: Props) {
  const [tab, setTab] = useState<MediaTab>("snapshot");
  const snap = event.snapshot;
  const equipmentId = event.cameraId?.trim() || "";
  const hasRtsp = Boolean(event.hasRtsp && equipmentId);
  const showLive = tab === "live" && hasRtsp && event.live?.online;

  return (
    <section className="pf-usr-event-media">
      <div className="pf-usr-event-media-head">
        <h3 className="pf-usr-section-title">现场取证</h3>
        {event.type === "video" && event.algorithmName ? (
          <span className="pf-usr-event-ai-tag">AI · {event.algorithmName}</span>
        ) : (
          <span className="pf-usr-event-ai-tag pf-usr-event-ai-tag-sensor">传感分析</span>
        )}
      </div>

      <div className="pf-usr-event-tabs" role="tablist" aria-label="现场媒体">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`pf-usr-event-tab${tab === item.id ? " is-active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "snapshot" ? (
        snap.imageUrl ? (
          <AiSnapshotViewer
            eventId={event.id}
            videoUrl=""
            snapshotUrl={snap.imageUrl}
            capturedAt={snap.capturedAt}
            aiLabel={snap.aiLabel}
            confidence={snap.confidence}
            detection={snap.detection ?? null}
          />
        ) : (
          <div className="pf-usr-event-snapshots">
            <div className="pf-usr-event-snap-main" style={{ background: snap.gradient }}>
              {snap.aiLabel ? (
                <div className="pf-usr-event-snap-ai">
                  <span className="pf-usr-event-snap-ai-label">AI 分析</span>
                  <strong>{snap.aiLabel}</strong>
                  {snap.confidence != null ? (
                    <em>{Math.round(snap.confidence * 100)}% 置信度</em>
                  ) : null}
                </div>
              ) : null}
              <span className="pf-usr-event-snap-time">{snap.capturedAt}</span>
            </div>
            {event.type === "video" ? (
              <p className="pf-usr-event-media-hint">
                {hasRtsp
                  ? "设备已配置 RTSP，请确认平台地址可用"
                  : "设备未配置 RTSP 地址，请在设备接入中填写"}
              </p>
            ) : null}
          </div>
        )
      ) : null}

      {tab === "live" ? (
        event.live ? (
          <div className="pf-usr-event-live">
            <div
              className="pf-usr-event-video-stage pf-usr-event-video-stage-live"
              style={showLive ? undefined : { background: event.live.gradient }}
            >
              {showLive ? (
                <EventFlvLiveStage equipmentId={equipmentId} paused={false} />
              ) : null}
              <span className={`pf-usr-event-live-badge${event.live.online ? "" : " is-offline"}`}>
                {event.live.online ? "LIVE" : "OFFLINE"}
              </span>
              <span className="pf-usr-event-live-grid" aria-hidden />
              <span className="pf-usr-event-live-hint">{event.live.cameraName}</span>
            </div>
            <div className="pf-usr-event-live-meta">
              <span>设备 {event.live.cameraId}</span>
              <span>
                {event.live.online
                  ? showLive
                    ? `延迟 ${event.live.latencyMs} ms · go2rtc WebRTC 1080p`
                    : hasRtsp
                      ? "设备在线，RTSP 流暂不可用"
                      : "未配置 RTSP"
                  : "设备离线"}
              </span>
              {showLive && event.live.online ? (
                <span className="pf-usr-event-live-flv-hint">使用画面右上角放大</span>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="pf-usr-event-media-empty">
            <p>暂无可用实时视频流</p>
          </div>
        )
      ) : null}
    </section>
  );
}
