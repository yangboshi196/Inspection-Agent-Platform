---
name: sia-algorithm-test
description: >-
  Use when the user wants to test vaio video algorithms: collect a local/URL
  video path, let them pick a detection target type, run vaio MCP tools, and
  return detection events. Triggers: 算法测试, 视频解析, 视频检测, 跑一下算法,
  测试船只/人员/安全帽检测.
version: 1.0.0
author: sia
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [video, ai, analysis, vaio, algorithm-test, sia]
    related_skills: [sia-video-ai, native-mcp]
---

# sia 算法测试（视频解析）

在 Hermes 中引导用户完成 **视频源 → 检测类型 → 自动推理 → 事件结果** 的闭环测试。依赖 MCP toolset **`mcp-vaio_analysis`**（6 个 `vaio_*` 工具）。

## 何时启用

- 用户说：算法测试、视频解析、跑检测、验证某类目标（船、人、安全帽等）
- 用户已在算法管理页同步过 vaio 算法，想在 Chat 里直接试

**不要用于：** 训练模型、改 C++ 配方、批量离线评测（应走专用脚本/平台任务）。

## 前置检查（静默执行，失败再告知用户）

1. 调用 **`vaio_health`** — 核心须 `status: ok`（`:9200`）
2. 若无 vaio MCP 工具：提示用户 `/reload-mcp`，并确认 `~/.hermes/config.yaml` 中 `mcp_servers.vaio_analysis` 使用 **Python ≥3.10** 且已 `pip install mcp httpx` + `vaio-analysis-service`
3. 可选：`vaio_list_algorithms` 与下方目录交叉校验

## 交互流程（必须按序）

### Step 1 — 收集视频地址

用 **`clarify`** 向用户说明并收集 **一条** 视频源（三选一）：

| 类型 | 示例 | 说明 |
|------|------|------|
| **绝对路径** | `/data/videos/dock.mp4` | 推荐；核心进程可直接读文件 |
| **相对路径** | `./clips/test.mp4` | 提交前用 `terminal`/`read_file` 转为绝对路径（相对 Hermes 当前工作目录） |
| **URL 流** | `rtsp://...` 或 `http://.../stream` | 使用 `src_data_type: 1`（实时流） |

**提示文案（可原文使用）：**

> 请提供待分析视频：**本地绝对路径**、**相对路径**（我会帮你转成绝对路径），或 **RTSP/HTTP URL**。  
> 仓库内测试样例：`/home/sia/tzb/WMAutoTrainPlat/sia/vaio-analysis-service/x86_64/test.mp4`（内容可能无目标，仅用于连通性）。

校验：

- 本地文件：用 `terminal` 执行 `test -f '<path>' && echo OK`
- URL：以 `rtsp://`、`http://`、`https://` 开头即可

### Step 2 — 选择检测目标类型

用 **`clarify`** 展示分组菜单（编号选择）。完整列表见 [algorithms.md](algorithms.md)。

**快捷菜单（展示给用户）：**

```
请选择检测目标（回复编号或算法名）：

【水域 / 码头】
  1. 船只检测 (1003)
  2. 码头捡螺入侵 (1007)

【人员 / 行为】
  3. 打架检测 (1001)
  4. 玩手机检测 (1004)
  5. 识别交通道路人员安全隐患行为 (1006)
  6. 人脸识别-编排 (1019)

【工业 / 作业安全】
  7. 五临边-未戴安全带检查 (1000)
  8. 探伤作业禁止进入 (1002)
  9. 动火作业火光检测 (1017)
 10. 动火无监护人检查 (1010)
 11. 焊接作业-跌倒摔倒 (1005)
 12. 卸货作业禁止进入 (1013)
 13. 吊车作业禁止进入 (1014)
 14. 深基坑-未戴安全带检查 (1015)
 15. 非工作时段禁止进入 (1012)
 16. 消火栓隐患检查 (1011)

【环境 / 场景】
 17. 裸土检测 (1008)
 18. 石头裸露识别 (1009)

【密集区域 / 跌倒】
 19. 卧倒摔倒识别 (1018)
 20. 人员密集区-跌倒摔倒 (1016)

其他：回复「列表」查看全部，或「自定义 ID」直接输入 detecttype（如 1003）。
```

用户选定后记录 **`detecttype`**（整数，如 `1003`）。

### Step 3 — 解析视频源类型

| 条件 | `src_data_type` | `video_url` |
|------|-----------------|-------------|
| 本地文件（绝对路径） | **2** | 绝对路径 |
| RTSP/HTTP(S) URL | **1** | 完整 URL |

生成唯一 **`task_id`**：`algo-test-{detecttype}-{unix_ts}`（例如 `algo-test-1003-1717234567`）。

### Step 4 — 构造任务配置并启动

调用 **`vaio_get_algorithm`**（`algorithm_id = detecttype`）查看配方。  
`config` 至少包含 `holddowntime`、`sensitivity`。**`defence`（检测防区）可省略**——MCP 层会自动注入全屏默认防区；若直连 `:9200` 须手动提供（见 [algorithms.md](algorithms.md)）。

示例 `config`（船只 1003，显式指定防区）：

```json
{
  "holddowntime": 60,
  "sensitivity": 50,
  "defence": [{
    "areaattr": 0,
    "points": [
      {"x": 0, "y": 0},
      {"x": 100, "y": 0},
      {"x": 100, "y": 100},
      {"x": 0, "y": 100}
    ]
  }]
}
```

旧版通用参数（仍可用，MCP 会补 `defence`）：

```json
{
  "detecttype": 1003,
  "activerec": 0,
  "config": {
    "holddowntime": 60,
    "detection/person/threshold": 0.5,
    "person/minlength": 50,
    "person/maxlength": 1000,
    "sensitivity": 50
  }
}
```

调用 **`vaio_start_task`**：

```json
{
  "task_id": "algo-test-1003-1717234567",
  "video_url": "/abs/path/to/video.mp4",
  "src_data_type": 2,
  "task_name": "Hermes算法测试-船只检测",
  "algorithms": [
    {
      "detecttype": 1003,
      "activerec": 0,
      "config": {
        "holddowntime": 60,
        "sensitivity": 50,
        "defence": [{
          "areaattr": 0,
          "points": [
            {"x": 0, "y": 0},
            {"x": 100, "y": 0},
            {"x": 100, "y": 100},
            {"x": 0, "y": 100}
          ]
        }]
      }
    }
  ]
}
```

**启动结果解读：**

| 返回 | 含义 |
|------|------|
| `"result": 0` | 任务启动成功 |
| `"error"` / 非 0 | 启动失败 — 见下方故障处理 |
| `"status": "accepted"` | 已受理，继续轮询事件 |

### Step 5 — 轮询事件并汇总

1. 每 **3–5 秒** 调用 **`vaio_list_events`**，`task_id` 填 Step 3 的 id，`limit` 50
2. 轮询 **60–120 秒** 或直到事件数量稳定 / 用户叫停
3. 结束后调用 **`vaio_stop_task`**（同一 `task_id`）

**向用户呈现的结果模板：**

```markdown
## 算法测试结果

- **任务 ID**：algo-test-1003-...
- **算法**：船只检测 (detecttype=1003)
- **视频**：/path/to/video.mp4
- **启动**：成功 (result=0) / 失败 (原因)

### 检测事件（共 N 条）

| 时间/序号 | 类型 | 置信度 | 摘要 |
|-----------|------|--------|------|
| ... | boat | 0.82 | bbox/描述 |

### 说明

- 无事件：视频中可能无目标、阈值过高、或样例视频过短
- 核心日志：vaio-analysis-service/x86_64/*.log
```

若 `vaio_list_events` 返回空数组，明确告知「任务已跑通但未产生告警事件」，不要伪造结果。

## 故障处理

| 现象 | 处理 |
|------|------|
| 无 `vaio_*` 工具 | `/reload-mcp`；检查 MCP Python 与 `mcp` 包 |
| `vaio_health` 失败 | 启动 `vaio-analysis-service/scripts/run-core.sh` |
| `ReqStartTask failed` / CreateGraph fail / `tool init fail` | 多为 **`config.defence` 缺失**（直连 `:9200`）；MCP 调用应已自动补全。含 **tracker** 的算法还可能缺 `labels` 或运行期崩溃 |
| 视频打不开 (8043) | 检查路径是否为绝对路径、`src_data_type` 是否正确 |
| 核心崩溃 (139) | 重启核心；避免同时启人脸 1019 与复杂 tracker 任务 |

## 工具调用清单（Agent 自检）

```
vaio_health
clarify          → 视频地址
clarify          → 检测类型
vaio_get_algorithm(detecttype)   [可选]
vaio_start_task(...)
vaio_list_events(task_id=..., limit=50)  × 多次
vaio_stop_task(task_id=...)
```

## 参考

- 算法 ID 全表：[algorithms.md](algorithms.md)
- MCP 注册与架构：[sia-video-ai](../sia-video-ai/SKILL.md)
- HTTP 直连：`POST http://127.0.0.1:9200/v1/tasks`（与 MCP 参数一致）
