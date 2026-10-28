#!/usr/bin/env python3
"""下载 Qwen/Qwen3-Embedding-0.6B 到 sia/models（供平台本地 embedding 使用）。"""

from __future__ import annotations

import argparse
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="下载 Qwen/Qwen3-Embedding-0.6B 到 sia/models/qwen3-embedding-0.6b"
    )
    parser.add_argument(
        "--hub-id",
        default="Qwen/Qwen3-Embedding-0.6B",
        help="HuggingFace 模型 id",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="SentenceTransformer save 目录（默认 <repo>/models/qwen3-embedding-0.6b）",
    )
    args = parser.parse_args()
    out = (args.out or (repo_root() / "models" / "qwen3-embedding-0.6b")).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise SystemExit(
            "请先安装依赖: pip install sentence-transformers\n"
            f"详情: {e}"
        ) from e

    cache = repo_root() / "models"
    print(f"正在从 HuggingFace 加载 {args.hub_id}（cache={cache}）…")
    model = SentenceTransformer(args.hub_id, cache_folder=str(cache))
    print(f"保存 SentenceTransformer 格式到 {out} …")
    model.save(str(out))
    dim = model.get_sentence_embedding_dimension()
    print(f"完成。向量维度={dim}，路径={out}")


if __name__ == "__main__":
    main()
