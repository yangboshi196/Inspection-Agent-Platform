---
name: sia-video-ai
description: "Video AI analysis via vaio-analysis-core MCP (start/stop tasks, list algorithms, poll events)."
version: 0.1.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [video, ai, analysis, vaio]
    related_skills: [native-mcp, sia-algorithm-test]
---

# sia Video AI (vaio-analysis)

通过 MCP 调用独立算法服务 `vaio-analysis-core`，替代原 VAIGateway ControllerSvr 通道。

## 前置条件

1. 编译并启动 C++ 核心（端口 9200）
2. 在 `~/.hermes/config.yaml` 注册 MCP：

```yaml
mcp_servers:
  vaio_analysis:
    command: python3
    args: ["-m", "vaio_analysis.mcp_server"]
    cwd: /home/sia/tzb/WMAutoTrainPlat/sia/vaio-analysis-service
    env:
      VAIO_CORE_BASE: "http://127.0.0.1:9200"
    timeout: 120
```

## 典型流程

1. `vaio_list_algorithms` — 查看可用算法（Algorithm_*.json）
2. `vaio_get_algorithm` — 读取配方细节
3. `vaio_start_task` — 传入 `task_id`、`video_url`、`algorithms`（`config.defence` 可省略，MCP 层自动补全屏防区）
4. `vaio_list_events` — 轮询检测事件
5. `vaio_stop_task` — 结束任务

## 任务 config 要点

- **`detecttype`**：算法 ID（如 1003），不是 `algorithm_id`
- **`config.defence`**：检测防区；MCP 缺失时自动注入全屏矩形；直连 `:9200` 须手动提供
- **`src_data_type`**：本地文件 `2`，RTSP/HTTP `1`

## 架构

Hermes Agent → Python MCP（薄层）→ HTTP → vaio-analysis-core（TaskManager / AlgorithmGraph / IComponent）

详见仓库 `vaio-analysis-service/README.md`。
