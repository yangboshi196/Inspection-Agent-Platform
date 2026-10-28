#!/usr/bin/env python3
"""OpenCV RTSP 拉流测试：单帧抓图 / 多线程实时渲染（需 opencv-python 带 GUI 时 --display）。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from inspection_platform.equipment.rtsp_opencv import (  # noqa: E402
    RtspFrameReader,
    capture_jpeg_opencv,
    opencv_available,
)
from inspection_platform.equipment.rtsp_live import grab_rtsp_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCV RTSP 拉流测试")
    parser.add_argument(
        "url",
        nargs="?",
        default="rtsp://admin:sia123@192.168.1.47:554/Streaming/Channels/101",
    )
    parser.add_argument("--display", action="store_true", help="cv2.imshow 窗口预览（需非 headless OpenCV）")
    parser.add_argument("--stream", action="store_true", help="多线程持续读帧")
    parser.add_argument("--out", type=Path, help="单帧保存路径")
    args = parser.parse_args()

    if not opencv_available():
        print("OpenCV 未安装: pip install opencv-python-headless")
        return 1

    import cv2  # noqa: PLC0415

    if args.stream or args.display:
        reader = RtspFrameReader(args.url).start()
        print("多线程拉流已启动，按 q 退出…")
        try:
            while True:
                frame = reader.read()
                if frame is None:
                    time.sleep(0.01)
                    continue
                if args.display:
                    cv2.imshow("RTSP OpenCV Stream", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                else:
                    print("frame", frame.shape, time.strftime("%H:%M:%S"))
                    time.sleep(0.5)
        finally:
            reader.stop()
            if args.display:
                cv2.destroyAllWindows()
        return 0

    t0 = time.time()
    jpeg = capture_jpeg_opencv(args.url)
    print(f"OpenCV 单帧: {len(jpeg)} bytes, {time.time() - t0:.2f}s")

    t1 = time.time()
    snap = grab_rtsp_snapshot(args.url)
    print(f"Platform grab_rtsp_snapshot: {len(snap)} bytes, {time.time() - t1:.2f}s")

    if args.out:
        args.out.write_bytes(jpeg)
        print(f"已保存: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
