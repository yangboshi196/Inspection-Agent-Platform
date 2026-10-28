# `model_manager` — 模型配置与实例管理

读取 JSON 配置，按 `impl` 创建 chat/embedding/visual/voice 实例，并提供重试、fallback、并发限流等调用策略。

## 架构概览

```
ModelManager（manager.py）
  ├── 加载：provider-first JSON 配置
  ├── 实例化：按 impl 选择 HttpApi* / OpenAICompat* 客户端
  ├── 限流：threading.Semaphore per (provider, model_name, purpose)
  └── 调用入口：call_chat / call_embedding / call_visual / call_voice

配置解析（config.py）
  ├── ModelSpec：name/provider/impl/source/tags/timeout_ms 等
  └── parse_model_spec()：校验必填字段

密钥解析（secrets.py）
  └── SecretResolver：env:XXX / secret:XXX / 明文 三种 key_ref
```

## 配置格式（provider-first）

```json
{
  "siliconflow": {
    "chat": [
      {
        "name": "Qwen/Qwen2.5-72B-Instruct",
        "provider": "siliconflow",
        "impl": "openai_compat",
        "source": { "type": "api", "url": "https://api.siliconflow.cn/v1", "key_ref": "env:SILICONFLOW_KEY" },
        "timeout_ms": 120000,
        "tags": ["default", "chat"]
      }
    ],
    "embedding": [...],
    "visual": [...],
    "voice": [...]
  }
}
```

**字段说明**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 模型名称（最终透传给 provider）|
| `provider` | ✅ | 提供商标识 |
| `impl` | ✅ | 实现类型：`http_api` / `openai_compat` / `openai` / `vllm` |
| `source.type` | ✅ | `api`（有 key_ref）或 `local`（无 key_ref）|
| `source.url` | ✅ | 端点地址 |
| `source.key_ref` | 看 impl | `env:XXX` / `secret:XXX` / 明文 |
| `timeout_ms` | ✅ | 请求超时（毫秒）|
| `connect_timeout_ms` | | 建连超时，默认 5000ms |
| `tags` | | 标签列表，`["default"]` 优先选中 |
| `concurrency_limit` | | 并发限制，`<=0` 表示不限 |

## ModelManager 核心接口

### 构造

```python
# 方式一：从 JSON dict 直接构建
mm = ModelManager(config={"siliconflow": {"chat": [...]}})

# 方式二：从 JSON 文件路径构建
mm = ModelManager.from_file("SIA_agent/model_manager/models.json", secret_resolver=resolver)
```

### 调用入口

| 方法 | 说明 |
|------|------|
| `call_chat(request, model_name=None)` | chat 模型调用，支持自动选择/重试/降级 |
| `call_embedding(texts, model_name=None)` | embedding 向量化 |
| `call_visual(request, model_name=None)` | 视觉/多模态模型调用 |
| `call_voice(request, model_name=None)` | 语音识别调用 |

### 模型选择策略（`_choose_candidate_entries`）

1. 若指定 `model_name`，优先匹配同名模型
2. 否则从 `tags` 含 `"default"` 的模型中选第一个
3. 若无 default tag，选列表第一个

### 重试与降级（`_call_with_retries`）

```
调用模型A
  ↓
失败？
  ├─ retryable=True → 重试（单模型级别）
  ├─ MODEL_UNAVAILABLE / RATE_LIMITED → 降级到下一个模型（跨模型级别）
  └─ 其他错误 → 直接抛出
```

**降级顺序**：按 `models.json` 中配置的顺序遍历同用途的所有模型，直到成功或全部失败。

### 并发限流

按 `(provider, model_name, purpose)` 维度创建 `threading.Semaphore`：

```python
semaphore = semaphore_or_none  # concurrency_limit > 0 时生效
with semaphore:
    result = instance.call(request)
```

## SecretResolver（`secrets.py`）

解析三种 `key_ref`：

| 格式 | 来源 |
|------|------|
| `env:VAR_NAME` | `os.environ[VAR_NAME]` 或 `local_env[VAR_NAME]` |
| `secret:NAME` | 预留扩展（当前同 env）|
| 明文 | 直接使用 |

```python
resolver = SecretResolver(local_env={"VAR": "debug_value"})
api_key = resolver.resolve("env:VAR_NAME")
```

**注意**：不要把真实 key 写入仓库，`local_env` 仅用于本地调试。

## ModelSpec（`config.py`）

```python
@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    impl: str | None          # http_api / openai_compat / ...
    source: ModelSource        # type + url + key_ref
    timeout_ms: int
    tags: list[str] | None
    connect_timeout_ms: int
    concurrency_limit: int     # <= 0 表示不限流
    capabilities: ModelCapabilities | None
```

## 开发注意事项

1. **provider-first**：配置结构必须为 `{provider: {purpose: [...]}}`，不支持平铺列表
2. **tag 优先级**：`["default"]` tag 的模型优先被 `model_name=None` 时选中
3. **降级触发**：`MODEL_UNAVAILABLE`（503）和 `RATE_LIMITED`（429）触发跨模型降级；其他错误直接抛出
4. **并发限流**：`concurrency_limit=0` 或负数表示不限流，不创建 semaphore
5. **impl 映射**：`"openai"` / `"vllm"` 等同 `"openai_compat"` 处理
6. **mock 已移除**：不能使用 `impl="mock"` 或 `source.url="mock://"`，必须配置真实后端
