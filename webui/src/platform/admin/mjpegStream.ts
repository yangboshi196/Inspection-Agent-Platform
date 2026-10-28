/**
 * 解析 multipart/x-mixed-replace MJPEG 流（go2rtc / legacy 后端）。
 */

export function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  if (a.length === 0) return b;
  if (b.length === 0) return a;
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/** 从缓冲中提取完整 JPEG 帧（FF D8 … FF D9） */
export function extractJpegFrames(buffer: Uint8Array): {
  frames: Uint8Array[];
  remaining: Uint8Array;
} {
  const frames: Uint8Array[] = [];
  let i = 0;
  while (i < buffer.length - 1) {
    let start = -1;
    for (let j = i; j < buffer.length - 1; j++) {
      if (buffer[j] === 0xff && buffer[j + 1] === 0xd8) {
        start = j;
        break;
      }
    }
    if (start < 0) break;
    let end = -1;
    for (let j = start + 2; j < buffer.length - 1; j++) {
      if (buffer[j] === 0xff && buffer[j + 1] === 0xd9) {
        end = j + 2;
        break;
      }
    }
    if (end < 0) {
      i = start;
      break;
    }
    frames.push(buffer.slice(start, end));
    i = end;
  }
  return { frames, remaining: buffer.slice(i) };
}

export async function consumeMultipartMjpeg(
  url: string,
  options: {
    signal?: AbortSignal;
    headers?: HeadersInit;
    onFrame: (blob: Blob) => void;
  },
): Promise<void> {
  const res = await fetch(url, { signal: options.signal, headers: options.headers });
  if (!res.ok) {
    throw new Error(`MJPEG ${res.status}`);
  }
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("MJPEG 无响应体");
  }
  let pending = new Uint8Array(0);
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value?.length) continue;
    pending = concatBytes(pending, value);
    const { frames, remaining } = extractJpegFrames(pending);
    pending = remaining;
    for (const frame of frames) {
      if (frame.length < 256) continue;
      options.onFrame(new Blob([frame], { type: "image/jpeg" }));
    }
  }
}
