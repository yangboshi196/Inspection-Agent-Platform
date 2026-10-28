"""
SIA_agent.model_manager.manager - 模型管理器

统一调度层，按用途（chat / embedding / visual / voice）路由到对应模型实例：
- 线程安全（使用锁 + 信号量控制并发）
- 自动重试与降级（单模型故障时自动切换）
- 密钥解析（通过 SecretResolver 支持 env: / secret: / 明文三种模式）

配置格式（provider-first JSON）：
- 一个用途可有多个 provider，按优先级尝试
- 每个 provider 内可有多个 model，按优先级尝试
- 超时与并发限制在各 provider 级别配置

使用示例::

    from SIA_agent.model_manager.manager import ModelManager

    mm = ModelManager.from_json(config_json)
    response = mm.chat([{"role": "user", "content": "hello"}])
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..llm.errors import LLMError
from ..llm.impl.http_api import HttpApiChatModel, HttpApiEmbeddingModel, HttpApiVisualModel, HttpApiVoiceModel
from ..llm.impl.openai_compat import (
    OpenAICompatChatModel,
    OpenAICompatEmbeddingModel,
    OpenAICompatVisualModel,
    OpenAICompatVoiceModel,
)
from .config import ModelSpec, parse_model_spec
from .secrets import SecretResolver


ModelPurpose = Literal["chat", "embedding", "visual", "voice"]


@dataclass(frozen=True)
class ModelEntry:
    """单个用途下的一条模型：规格、可调用实例、可选并发信号量。"""

    spec: ModelSpec
    instance: Any
    semaphore: threading.Semaphore | None = None


class ModelManager:
    """
    读取 provider-first 的模型配置，按 `impl` 装配实例，并提供带重试/降级/限流的统一调用入口。
    """

    def __init__(self, config: dict[str, Any], secret_resolver: SecretResolver | None = None) -> None:
        """`config` 为已解析的 JSON 根对象；`secret_resolver` 用于解析 `key_ref`。"""
        self._secret_resolver = secret_resolver or SecretResolver()
        self._models: dict[ModelPurpose, list[ModelEntry]] = {"chat": [], "embedding": [], "visual": [], "voice": []}
        self._semaphores: dict[tuple[str, str, ModelPurpose], threading.Semaphore] = {}
        self._semaphores_lock = threading.Lock()
        self._load(config)

    @classmethod
    def from_file(cls, path: str | Path, secret_resolver: SecretResolver | None = None) -> "ModelManager":
        """从 JSON 文件路径构建 `ModelManager`。"""
        p = Path(path)
        config = json.loads(p.read_text(encoding="utf-8"))
        return cls(config=config, secret_resolver=secret_resolver)

    def _load(self, config: dict[str, Any]) -> None:
        """入口：按 provider-first 结构装载配置。"""
        purposes = ("chat", "embedding", "visual", "voice")

        # 仅支持 provider-first：
        # {
        #   "<provider>": { "chat": [...], "embedding": [...], "visual": [...], "voice": [...] },
        #   ...
        # }
        self._load_provider_first(config, purposes=purposes)

    def _load_provider_first(self, config: dict[str, Any], *, purposes: tuple[str, ...]) -> None:
        """遍历每个 provider 块，将各用途下的模型条目加入内部表。"""
        if not isinstance(config, dict):
            raise ValueError("models config must be an object")
        for provider, block in config.items():
            if not isinstance(block, dict):
                raise ValueError(f"provider '{provider}' must be an object")
            for purpose in purposes:
                raw = block.get(purpose)
                if not raw:
                    continue
                self._append_models_for_purpose(
                    purpose, raw, ctx_prefix=f"{provider}.{purpose}", default_provider=provider
                )

    def _append_models_for_purpose(
        self,
        purpose: ModelPurpose,
        raw: Any,
        *,
        ctx_prefix: str,
        default_provider: str | None = None,
    ) -> None:
        """将单用途配置（对象或数组）解析为多条 `ModelEntry` 并追加。"""
        specs: list[ModelSpec]
        if isinstance(raw, list):
            specs = [parse_model_spec(x, f"{ctx_prefix}[{i}]") for i, x in enumerate(raw)]
        elif isinstance(raw, dict):
            specs = [parse_model_spec(raw, f"{ctx_prefix}")]
        else:
            raise ValueError(f"invalid config for '{ctx_prefix}'")

        for spec in specs:
            if default_provider:
                if spec.provider != default_provider:
                    raise ValueError(
                        f"{ctx_prefix}: provider mismatch: model.provider='{spec.provider}' "
                        f"but provider key is '{default_provider}'"
                    )
            inst = self._build_instance(purpose, spec)
            sem = self._get_or_create_semaphore(spec.provider, spec.name, purpose, spec.concurrency_limit)
            self._models[purpose].append(ModelEntry(spec=spec, instance=inst, semaphore=sem))

    def _get_or_create_semaphore(
        self, provider: str, model_name: str, purpose: ModelPurpose, limit: int
    ) -> threading.Semaphore | None:
        """按 `(provider, model_name, purpose)` 维度复用信号量；`limit<=0` 表示不限流。"""
        if limit <= 0:
            return None
        key = (provider, model_name, purpose)
        with self._semaphores_lock:
            if key not in self._semaphores:
                self._semaphores[key] = threading.Semaphore(limit)
            return self._semaphores[key]

    def _build_instance(self, purpose: ModelPurpose, spec: ModelSpec):
        """根据 `impl` 与用途构造具体模型客户端实例。"""
        api_key = None
        if spec.source.type == "api" and spec.source.key_ref:
            api_key = self._secret_resolver.resolve(spec.source.key_ref)

        impl = (spec.impl or "").strip().lower()
        if impl in ("mock", "") and str(spec.source.url or "").startswith("mock://"):
            raise ValueError("mock impl has been removed; please configure a real model backend")

        if impl in ("http_api", "http"):
            if purpose == "chat":
                return HttpApiChatModel(
                    model_name=spec.name,
                    source=spec.source.type,
                    url=spec.source.url,
                    api_key=api_key,
                    provider=spec.provider,
                    tags=spec.tags,
                    timeout_ms=spec.timeout_ms,
                    connect_timeout_ms=spec.connect_timeout_ms,
                )
            if purpose == "embedding":
                return HttpApiEmbeddingModel(
                    model_name=spec.name,
                    source=spec.source.type,
                    url=spec.source.url,
                    api_key=api_key,
                    provider=spec.provider,
                    tags=spec.tags,
                    timeout_ms=spec.timeout_ms,
                    connect_timeout_ms=spec.connect_timeout_ms,
                )
            if purpose == "visual":
                return HttpApiVisualModel(
                    model_name=spec.name,
                    source=spec.source.type,
                    url=spec.source.url,
                    api_key=api_key,
                    provider=spec.provider,
                    tags=spec.tags,
                    timeout_ms=spec.timeout_ms,
                    connect_timeout_ms=spec.connect_timeout_ms,
                )
            return HttpApiVoiceModel(
                model_name=spec.name,
                source=spec.source.type,
                url=spec.source.url,
                api_key=api_key,
                provider=spec.provider,
                tags=spec.tags,
                timeout_ms=spec.timeout_ms,
                connect_timeout_ms=spec.connect_timeout_ms,
            )

        if impl in ("openai_compat", "openai", "vllm"):
            if purpose == "chat":
                return OpenAICompatChatModel(
                    model_name=spec.name,
                    source=spec.source.type,
                    url=spec.source.url,
                    api_key=api_key,
                    provider=spec.provider,
                    tags=spec.tags,
                    timeout_ms=spec.timeout_ms,
                    connect_timeout_ms=spec.connect_timeout_ms,
                )
            if purpose == "embedding":
                return OpenAICompatEmbeddingModel(
                    model_name=spec.name,
                    source=spec.source.type,
                    url=spec.source.url,
                    api_key=api_key,
                    provider=spec.provider,
                    tags=spec.tags,
                    timeout_ms=spec.timeout_ms,
                    connect_timeout_ms=spec.connect_timeout_ms,
                )
            if purpose == "visual":
                return OpenAICompatVisualModel(
                    model_name=spec.name,
                    source=spec.source.type,
                    url=spec.source.url,
                    api_key=api_key,
                    provider=spec.provider,
                    tags=spec.tags,
                    timeout_ms=spec.timeout_ms,
                    connect_timeout_ms=spec.connect_timeout_ms,
                )
            return OpenAICompatVoiceModel(
                model_name=spec.name,
                source=spec.source.type,
                url=spec.source.url,
                api_key=api_key,
                provider=spec.provider,
                tags=spec.tags,
                timeout_ms=spec.timeout_ms,
                connect_timeout_ms=spec.connect_timeout_ms,
            )

        raise ValueError(f"unsupported impl '{spec.impl}' for {purpose}:{spec.name}")

    def list_models(self, purpose: ModelPurpose) -> list[str]:
        """列出某用途下已配置的全部模型名（按配置顺序）。"""
        return [e.spec.name for e in self._models[purpose]]

    def list_model_infos(self, purpose: ModelPurpose) -> list[dict[str, Any]]:
        """列出某用途下模型的可展示信息（不含密钥）。"""
        out: list[dict[str, Any]] = []
        for e in self._models[purpose]:
            out.append(
                {
                    "name": e.spec.name,
                    "provider": e.spec.provider,
                    "impl": e.spec.impl,
                    "source_type": e.spec.source.type,
                    "source_url": e.spec.source.url,
                    "tags": list(e.spec.tags),
                }
            )
        return out

    def ping_models(self, purpose: ModelPurpose, *, timeout_ms: int = 800) -> dict[str, dict[str, Any]]:
        """
        轻量探活：对每个模型调用其 `ping(timeout_ms)`（通常是 GET /v1/models），不触发推理。

        返回：{model_name: {"ok": bool, "latency_ms": int|None, "error": str|None}}
        """
        out: dict[str, dict[str, Any]] = {}
        for e in self._models[purpose]:
            name = e.spec.name
            t0 = time.time()
            ok = False
            err: str | None = None
            try:
                if hasattr(e.instance, "ping"):
                    ok = bool(e.instance.ping(timeout_ms=timeout_ms))
                else:
                    err = "ping not supported"
            except Exception as ex:  # noqa: BLE001
                err = str(ex)
            dt_ms = int((time.time() - t0) * 1000)
            out[name] = {"ok": ok, "latency_ms": dt_ms, "error": err}
        return out

    def get_default(self, purpose: ModelPurpose):
        """返回该用途列表中的第一个模型实例（默认主模型）。"""
        if not self._models[purpose]:
            raise KeyError(f"no model configured for purpose '{purpose}'")
        return self._models[purpose][0].instance

    def get_fallbacks(self, purpose: ModelPurpose) -> list[Any]:
        """返回备用模型实例列表：优先带 `backup` tag，其余按配置顺序去重追加。"""
        if not self._models[purpose]:
            return []
        # 优先选择 tags 含 backup 的，其次按配置顺序
        backups = [e.instance for e in self._models[purpose] if "backup" in e.spec.tags]
        ordered = [e.instance for e in self._models[purpose][1:]]
        seen: set[int] = set()
        res: list[Any] = []
        for m in backups + ordered:
            mid = id(m)
            if mid in seen:
                continue
            seen.add(mid)
            res.append(m)
        return res

    def _should_retry(self, err: LLMError) -> bool:
        """是否对当前错误进行同模型重试（受 `max_retries` 与错误码约束）。"""
        return err.code in ("TIMEOUT", "NETWORK_ERROR", "RATE_LIMITED") and err.retryable

    def _should_fallback(self, err: LLMError) -> bool:
        """是否应切换到候选列表中的下一模型（降级）。"""
        if err.code in ("MODEL_UNAVAILABLE", "RATE_LIMITED"):
            return True
        msg = (err.message or "").lower()
        if err.code == "BAD_REQUEST" and ("embedding" in msg or "embeddings api" in msg):
            return True
        return False

    def new_request_id(self) -> str:
        """生成新的请求追踪 id（十六进制字符串）。"""
        return uuid.uuid4().hex

    def call_chat(self, request, *, model_name: str | None = None) -> Any:
        """调用 chat 模型；`model_name` 指定时优先该模型并保留其余候选作降级。"""
        return self._call_with_retries("chat", model_name, lambda m: m.call(request))

    def call_chat_stream(self, request, *, model_name: str | None = None):
        """
        流式调用 chat 模型：返回一个可迭代对象（yield 文本增量）。

        说明：该方法不做跨模型降级与重试（避免流中断造成复杂状态）；若模型不支持流式会抛 `NotImplementedError`。
        """
        entries = self._choose_candidate_entries("chat", model_name)
        entry = entries[0]
        if entry.semaphore is not None:
            entry.semaphore.acquire()
        try:
            return entry.instance.stream_call(request)
        finally:
            if entry.semaphore is not None:
                entry.semaphore.release()

    def call_embedding(self, request, *, model_name: str | None = None) -> Any:
        """调用 embedding 模型。"""
        return self._call_with_retries("embedding", model_name, lambda m: m.call(request))

    def call_visual(self, request, *, model_name: str | None = None) -> Any:
        """调用视觉/多模态 chat 模型。"""
        return self._call_with_retries("visual", model_name, lambda m: m.call(request))

    def call_voice(self, request, *, model_name: str | None = None) -> Any:
        """调用语音（如 ASR）模型。"""
        return self._call_with_retries("voice", model_name, lambda m: m.call(request))

    def _call_with_retries(self, purpose: ModelPurpose, model_name: str | None, fn):
        """
        对候选模型链依次尝试：单模型内按 `LLMError` 可重试则退避重试；
        不可恢复且允许降级时换下一候选。
        """
        entries = self._choose_candidate_entries(purpose, model_name)
        last_err: LLMError | None = None
        for idx, entry in enumerate(entries):
            retries = 0
            max_retries = max(0, int(entry.spec.max_retries))
            while True:
                try:
                    if entry.semaphore is not None:
                        entry.semaphore.acquire()
                    try:
                        return fn(entry.instance)
                    finally:
                        if entry.semaphore is not None:
                            entry.semaphore.release()
                except LLMError as e:
                    last_err = e
                    if retries < max_retries and self._should_retry(e):
                        retries += 1
                        time.sleep(max(0.0, float(entry.spec.retry_backoff_ms) / 1000.0))
                        continue
                    if idx < len(entries) - 1 and self._should_fallback(e):
                        break
                    raise
        if last_err:
            raise last_err
        raise RuntimeError(f"no {purpose} model available")

    def _choose_candidate_entries(self, purpose: ModelPurpose, model_name: str | None) -> list[ModelEntry]:
        """确定本次调用使用的 `ModelEntry` 顺序；指定 `model_name` 时将其置于首位。"""
        entries = self._models[purpose]
        if not entries:
            raise KeyError(f"no model configured for purpose '{purpose}'")
        if model_name:
            for e in entries:
                if e.spec.name == model_name:
                    return [e] + [x for x in entries if x.spec.name != model_name]
            # 配置里写了不存在的模型名时，不要直接 KeyError（会变成 FastAPI 500）。
            # 这里退化为“默认候选链”：优先 tags 含 default 的模型，其次保持原顺序。
            tagged = [e for e in entries if "default" in (e.spec.tags or [])]
            if tagged:
                rest = [e for e in entries if e not in tagged]
                return tagged + rest
            return list(entries)
        tagged = [e for e in entries if "default" in (e.spec.tags or [])]
        if tagged:
            rest = [e for e in entries if e not in tagged]
            return tagged + rest
        return list(entries)

