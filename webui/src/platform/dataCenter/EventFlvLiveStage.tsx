import { GO2RTC_LIVE_DEFAULTS } from "../equipmentApi";
import { RtspLivePreview } from "../admin/RtspLivePreview";

/** 事件详情内 RTSP 实时画面（go2rtc WebRTC H.265 1080p）。 */
export function EventFlvLiveStage({
  equipmentId,
  paused = false,
  embedded = false,
}: {
  equipmentId: string;
  /** 非当前 tab 时暂停并销毁播放器，避免多路拉流 */
  paused?: boolean;
  embedded?: boolean;
}) {
  if (!equipmentId.trim()) return null;
  return (
    <div className="pf-usr-event-flv-stage">
      <RtspLivePreview
        equipmentId={equipmentId}
        paused={paused}
        embedded={embedded}
        large={!embedded}
        stream={GO2RTC_LIVE_DEFAULTS.stream}
        quality={GO2RTC_LIVE_DEFAULTS.quality}
      />
    </div>
  );
}
