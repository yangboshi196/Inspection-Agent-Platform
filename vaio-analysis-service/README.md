# vaio-analysis-service

将 VAIOpsSvr_BP 算法内核从 VAIGateway 拆出，用 HTTP 替代 ControllerSvr/CSM 头，并通过 MCP 供 Hermes Agent 调用。

## 架构

```
Hermes Agent
    │ MCP (stdio)
    ▼
Python MCP Server（薄层：参数校验、JSON、鉴权）
    │ HTTP (本地)
    ▼
vaio-analysis-core（C++ 独立进程，端口 9200）
    ├── AnalysisHttpServer   ← 替代 ControllerSvr
    ├── TaskManager / AlgorithmGraph / IComponent
    └── MemoryEventSink      ← 替代 UploadDetectEvent 上报
```

## 目录结构

```
vaio-analysis-service/
├── x86_64/                  # C++ 运行时（二进制、conf、model、label）
│   ├── vaio-analysis-core
│   ├── conf/
│   ├── model/
│   └── label/
├── scripts/
│   ├── run-core.sh          # 启动 C++ 核心（依赖 ../agent_skills/deps）
│   └── start.sh
└── vaio_analysis/           # Python 薄层
```

运行时库（TensorRT、OpenCV、libMNN 等）仍位于 `../agent_skills/deps/`，可通过 `VAIO_SKILLS_ROOT` 覆盖。

## 构建 C++ 核心

在完整 VAIGateway 依赖环境下：

```bash
cd agent_skills/VAIGateway/VAIOpsSvr_BP
make -f Makefile.standalone TARGETPLATFORM=x86_64
# 产物同步到 vaio-analysis-service/x86_64/
rsync -a --exclude='core' --exclude='*.log' \
  ../bin/x86_64/ ../../vaio-analysis-service/x86_64/
```

编译宏 `-DVAIO_STANDALONE` 会排除 `NetWorkProxy` / `ControllerSvr`，并在 `MainFramer` 中启动 `AnalysisHttpServer`。

## 启动

```bash
pip install -r requirements.txt
./scripts/start.sh all
# 或仅 C++ 核心：
./scripts/run-core.sh
```

- C++ 核心：`http://127.0.0.1:9200`
- Python REST（可选）：`http://127.0.0.1:9201`

## C++ HTTP API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/v1/algorithms` | 列出 Algorithm_*.json |
| GET | `/v1/algorithms/{id}` | 获取算法配方 |
| POST | `/v1/tasks` | 启动任务 |
| DELETE | `/v1/tasks/{id}` | 停止任务 |
| GET | `/v1/events?task_id=&limit=` | 拉取检测事件 |

### 启动任务示例

C++ 核心要求每个算法的 `config.defence`（检测防区多边形，坐标 0–100 整数百分比）。  
MCP / Python REST 层会在缺失时自动注入全屏默认防区；直连 `:9200` 须自行带上。

```bash
curl -s -X POST http://127.0.0.1:9200/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "demo-1",
    "video_url": "/path/to/video.mp4",
    "src_data_type": 2,
    "algorithms": [{
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
    }]
  }'
```

一键验证船只检测（含 `defence`）：

```bash
./scripts/test-ship-algo.sh [/path/to/boat.mp4]
```

### config.defence 字段说明

| 字段 | 说明 |
|------|------|
| `defence` | **必填**（直连核心时）；非空数组，缺则 `ParseDetectRegionConf fail` |
| `areaattr` | `0`=检测防区，`8`=布控线（≥2 点），`9`=反向区域 |
| `points[].x/y` | 0–100 整数，画面宽高百分比 |

可选 `config.validarea`（目标有效区域）缺省时核心默认中心点 `(50,50)`。

## Hermes MCP 配置

在 `~/.hermes/config.yaml` 添加：

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

可用工具：`vaio_health`、`vaio_list_algorithms`、`vaio_get_algorithm`、`vaio_start_task`、`vaio_stop_task`、`vaio_list_events`。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `VAIO_HTTP_PORT` | 9200 | C++ HTTP 端口 |
| `VAIO_CORE_BASE` | http://127.0.0.1:9200 | Python 层连接地址 |
| `VAIO_API_PORT` | 9201 | Python REST 端口 |

## 源码位置

- C++ standalone 源码：`../agent_skills/VAIGateway/VAIOpsSvr_BP/standalone/`
- C++ 运行时产物：`vaio-analysis-service/x86_64/`
- Python 薄层：`vaio_analysis/`
