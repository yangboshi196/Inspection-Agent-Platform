"""流媒体中台：go2rtc 单路拉流、多协议分发（WebRTC / HLS / FLV / MP4 录像）。"""

from .service import MediaStreamService, get_media_service

__all__ = ["MediaStreamService", "get_media_service"]
