"""与 LLM 输入相关的轻量媒体类型推断（避免各处复制魔数）。"""


def guess_image_mime_from_bytes(head: bytes) -> str:
    """根据文件头猜测常见图片 mime，用于 data URL 等场景。"""
    b = head or b""
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"):
        return "image/gif"
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"
