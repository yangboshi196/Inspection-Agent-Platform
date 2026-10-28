"""本地 SentenceTransformer embedding（默认 Qwen/Qwen3-Embedding-0.6B）。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_model: Any = None
_model_source: str | None = None
_model_device: str | None = None

QWEN3_EMBED_HUB_ID = "Qwen/Qwen3-Embedding-0.6B"
QWEN3_EMBED_CACHE_DIRNAME = "models--Qwen--Qwen3-Embedding-0.6B"
QWEN3_EMBED_SAVE_DIRNAME = "qwen3-embedding-0.6b"


def models_root() -> Path:
    from inspection_platform.app.config import repo_root

    return (repo_root() / "models").resolve()


def resolve_embedding_device() -> str:
    """
    解析 embedding 运行设备。

    环境变量 ``SIA_EMBEDDING_DEVICE``：
    - ``cuda`` / ``cuda:0``（默认）：强制 GPU；不可用时报错
    - ``cpu``：CPU
    - ``auto``：有 CUDA 用 GPU，否则 CPU
    """
    from inspection_platform.envutil import env_first

    raw = (env_first("SIA_EMBEDDING_DEVICE") or "cuda").strip().lower()
    if raw == "auto":
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    if raw == "cpu":
        return "cpu"
    if raw.startswith("cuda"):
        import torch

        if not torch.cuda.is_available():
            compiled = getattr(torch.version, "cuda", None) or "unknown"
            raise ValueError(
                f"SIA_EMBEDDING_DEVICE={raw!r} 但当前 PyTorch 无法使用 CUDA "
                f"(compiled_cuda={compiled})。"
                "常见原因：安装的 torch 为 cu130 而驱动仅支持 CUDA 12.x。"
                "请安装匹配驱动版本的 PyTorch，例如："
                " pip install torch --index-url https://download.pytorch.org/whl/cu124"
                " 或设置 SIA_EMBEDDING_DEVICE=cpu"
            )
        if ":" not in raw:
            return "cuda:0"
        return raw
    raise ValueError(
        f"无效的 SIA_EMBEDDING_DEVICE={raw!r}；允许 cuda、cuda:0、cpu、auto"
    )


def embedding_device() -> str:
    """当前已加载模型所在设备（未加载时按配置解析）。"""
    global _model_device
    if _model_device is not None:
        return _model_device
    return resolve_embedding_device()


def _read_hf_snapshot(cache_dir: Path) -> Path | None:
    """从 HuggingFace 缓存目录 ``models--Org--Name`` 解析 snapshots 路径。"""
    refs_main = cache_dir / "refs" / "main"
    if refs_main.is_file():
        rev = refs_main.read_text(encoding="utf-8").strip()
        snap = cache_dir / "snapshots" / rev
        if snap.is_dir() and (snap / "config.json").is_file():
            return snap
    snaps_root = cache_dir / "snapshots"
    if not snaps_root.is_dir():
        return None
    for child in sorted(snaps_root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "config.json").is_file():
            return child
    return None


def resolve_embedding_model_source() -> tuple[str, Path | None]:
    """
    返回 (SentenceTransformer 加载参数, 本地快照目录或 None)。

    优先级：
    1. ``SIA_EMBEDDING_MODEL_PATH`` 显式路径
    2. ``models/qwen3-embedding-0.6b``（``model.save()`` 格式）
    3. ``models/models--Qwen--Qwen3-Embedding-0.6B`` HF 缓存快照
    4. Hub id + ``cache_folder=models``（本地仅有缓存时 ``local_files_only``）
    """
    from inspection_platform.envutil import env_first

    custom = env_first("SIA_EMBEDDING_MODEL_PATH")
    if custom:
        p = Path(custom).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"SIA_EMBEDDING_MODEL_PATH 不是有效目录: {p}")
        return str(p), p

    root = models_root()
    st_save = root / QWEN3_EMBED_SAVE_DIRNAME
    if st_save.is_dir() and (st_save / "config.json").is_file():
        return str(st_save), st_save

    hf_cache = root / QWEN3_EMBED_CACHE_DIRNAME
    snap = _read_hf_snapshot(hf_cache)
    if snap is not None:
        return str(snap), snap

    if not root.is_dir():
        raise ValueError(
            f"本地 models 目录不存在: {root}；"
            f"请下载 {QWEN3_EMBED_HUB_ID} 到该目录，"
            "或运行: python scripts/download_embedding_model.py"
        )
    return QWEN3_EMBED_HUB_ID, root


def embedding_model_path() -> Path:
    """返回用于展示的本地模型目录（Hub 回退时返回 models 根目录）。"""
    _, local = resolve_embedding_model_source()
    return local if local is not None else models_root()


def get_sentence_transformer():
    """进程内单例加载 ``SentenceTransformer``（默认加载到 CUDA）。"""
    global _model, _model_source, _model_device
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ValueError(
                "未安装 sentence-transformers；请执行: pip install sentence-transformers"
            ) from e

        device = resolve_embedding_device()
        source, local_root = resolve_embedding_model_source()
        root = models_root()
        kwargs: dict[str, Any] = {"device": device}
        if source == QWEN3_EMBED_HUB_ID:
            kwargs["cache_folder"] = str(root)
            if (root / QWEN3_EMBED_CACHE_DIRNAME).is_dir():
                kwargs["local_files_only"] = True

        try:
            _model = SentenceTransformer(source, **kwargs)
        except Exception as e:
            raise ValueError(
                f"加载 embedding 模型失败（source={source!r}, device={device!r}）：{e}"
            ) from e
        _model_source = source
        _model_device = device
        if device.startswith("cuda"):
            try:
                name = _model.device
                logger.info("embedding 模型已加载到 %s (%s)", device, name)
            except Exception:
                logger.info("embedding 模型已加载到 %s", device)
        return _model


def embedding_dimension() -> int:
    model = get_sentence_transformer()
    if hasattr(model, "get_embedding_dimension"):
        return int(model.get_embedding_dimension())
    return int(model.get_sentence_embedding_dimension())


def _encode_batch_size(device: str) -> int:
    if device.startswith("cuda"):
        return 32
    return 8


def sentence_transformer_embed_texts(
    texts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> list[list[float]]:
    """批量文本向量化；与 ``platform_embed_texts`` 返回格式一致。"""
    _ = metadata
    if not texts:
        return []
    model = get_sentence_transformer()
    device = _model_device or resolve_embedding_device()
    try:
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=_encode_batch_size(device),
            convert_to_numpy=True,
        )
    except Exception as e:
        raise ValueError(f"SentenceTransformer 向量化失败（device={device}）：{e}") from e
    out: list[list[float]] = []
    for v in vectors:
        out.append(list(map(float, v)))
    if len(out) != len(texts):
        raise ValueError("embedding 返回向量数与输入不一致")
    return out
