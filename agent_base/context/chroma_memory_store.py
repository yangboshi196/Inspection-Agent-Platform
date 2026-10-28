"""
SIA_agent.context.chroma_memory_store - 会话快照持久化（Chroma）

将「窗口消息 + 两类摘要」以 JSON 文档形式写入 Chroma：
- load()：从 Chroma 读取会话快照，返回 (messages, history_summary, important_summary)
- save()：将会话快照写入 Chroma（upsert，幂等）
- delete()：删除会话快照

技术细节：
- 使用稳定 doc_id（business_id + session_id 的 SHA256 前缀）避免路径冲突
- Chroma metadata 仅支持标量，复杂类型统一转字符串
- 存储介质仅用于持久化，不参与向量检索（embeddings 固定为 [0.0]）

注意：本模块仅负责持久化，不负责加载时机（由 HybridMemoryContextManager 统一调度）。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb

from .models import Message


def _stable_doc_id(business_id: str, session_id: str) -> str:
    raw = f"{business_id}\n{session_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:48]


def _sanitize_collection_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
    return (s or "agent_session_memory")[:60]


def _flatten_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out


def _message_to_dict(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at.isoformat(),
        "token_count": m.token_count,
        "metadata": dict(m.metadata or {}),
    }


def _dict_to_message(d: dict[str, Any], *, default_session_id: str) -> Message:
    created = d.get("created_at")
    if isinstance(created, str):
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
    else:
        created_at = datetime.utcnow()
    return Message(
        id=str(d["id"]),
        session_id=str(d.get("session_id") or default_session_id),
        role=d["role"],  # type: ignore[arg-type]
        content=str(d.get("content") or ""),
        created_at=created_at,
        token_count=d.get("token_count"),
        metadata=dict(d.get("metadata") or {}),
    )


class ChromaSessionMemoryStore:
    """将会话窗口与两类摘要持久化到 Chroma（单条 upsert / session）。"""

    def __init__(self, *, persist_dir: str | Path, collection_name: str = "agent_session_memory") -> None:
        self._persist_dir = Path(persist_dir)
        self._collection_name = _sanitize_collection_name(collection_name)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def load(
        self,
        *,
        business_id: str,
        session_id: str,
    ) -> tuple[list[Message], str, str] | None:
        """返回 `(messages, history_summary, important_summary)`；不存在则 `None`。"""
        doc_id = _stable_doc_id(business_id, session_id)
        got = self._collection.get(ids=[doc_id], include=["documents", "metadatas"])
        ids = got.get("ids") or []
        if not ids:
            return None
        docs = (got.get("documents") or [None])[0]
        if not docs:
            return None
        try:
            payload = json.loads(docs)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        raw_msgs = payload.get("messages") or []
        if not isinstance(raw_msgs, list):
            raw_msgs = []
        messages = [_dict_to_message(x, default_session_id=session_id) for x in raw_msgs if isinstance(x, dict)]
        hist = str(payload.get("history_summary") or "")
        imp = str(payload.get("important_summary") or "")
        return messages, hist, imp

    def save(
        self,
        *,
        business_id: str,
        session_id: str,
        messages: list[Message],
        history_summary: str,
        important_summary: str,
    ) -> None:
        doc_id = _stable_doc_id(business_id, session_id)
        payload = {
            "version": 1,
            "messages": [_message_to_dict(m) for m in messages],
            "history_summary": history_summary,
            "important_summary": important_summary,
        }
        doc = json.dumps(payload, ensure_ascii=False)
        meta = _flatten_metadata(
            {
                "business_id": business_id,
                "session_id": session_id,
                "kind": "session_memory_bundle",
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
        )
        # 该 collection 仅用于“会话记忆快照”持久化，不参与向量检索。
        # 若不显式提供 embeddings，Chroma 可能启用默认 embedding_function 并下载 onnx 模型（如 all-MiniLM-L6-v2）。
        self._collection.upsert(ids=[doc_id], documents=[doc], metadatas=[meta], embeddings=[[0.0]])

    def delete(self, *, business_id: str, session_id: str) -> bool:
        """删除某业务会话的持久化快照；存在则返回 True，不存在返回 False。"""
        doc_id = _stable_doc_id(business_id, session_id)
        got = self._collection.get(ids=[doc_id], include=[])
        ids = got.get("ids") or []
        if not ids:
            return False
        self._collection.delete(ids=[doc_id])
        return True
