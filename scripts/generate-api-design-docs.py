#!/usr/bin/env python3
"""Generate 需求接口设计文档.doc and 排期.xls under docs/."""
from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Cm
from docx.oxml.ns import qn
import xlwt

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
DOCX_PATH = DOCS / "需求接口设计文档.docx"
DOC_PATH = DOCS / "需求接口设计文档.doc"
XLS_PATH = DOCS / "排期.xls"

VERSION = "V1.0"
DOC_DATE = date(2026, 6, 9)
PROJECT = "物盟智能巡检 Agent 平台（SIA_agent）"


def set_cell_font(cell, name="宋体", size=10):
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.name = name
            r._element.rPr.rFonts.set(qn("w:eastAsia"), name)
            r.font.size = Pt(size)


def add_cover(doc: Document):
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("\n\n\n物盟智能巡检 Agent 平台\n")
    r.bold = True
    r.font.size = Pt(22)
    r.font.name = "黑体"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    t2 = doc.add_paragraph()
    t2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = t2.add_run("需求与接口设计文档")
    r2.bold = True
    r2.font.size = Pt(18)
    r2.font.name = "黑体"
    r2._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"\n\n版本：{VERSION}\n日期：{DOC_DATE.isoformat()}\n项目：{PROJECT}\n")
    doc.add_page_break()


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for r in h.runs:
        r.font.name = "黑体"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    return h


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.bold = True
    for ri, row in enumerate(rows):
        cells = table.rows[ri + 1].cells
        for ci, val in enumerate(row):
            cells[ci].text = str(val)
    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph("")
    return table


def build_word():
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(2.5)
    sec.bottom_margin = Cm(2.5)
    sec.left_margin = Cm(2.8)
    sec.right_margin = Cm(2.8)

    add_cover(doc)

    add_heading(doc, "1. 文档说明", 1)
    doc.add_paragraph(
        "本文档基于 SIA_agent 仓库当前实现（inspection_platform :8001、webui :5173、"
        "vaio-analysis-core :9200、Hermes /hermes-agent）梳理核心业务域、HTTP/MCP 接口现状，"
        "并给出待建设接口的需求设计与统一约定。权威实体说明见 docs/entities-and-database.md。"
    )
    add_table(
        doc,
        ["项", "说明"],
        [
            ["文档版本", VERSION],
            ["编制日期", DOC_DATE.isoformat()],
            ["适用范围", "平台 REST、VAIO 视频 AI、Agent SSE/MCP、Hermes 控制台"],
            ["读者", "产品、后端、前端、算法、测试"],
            ["OpenAPI", "根目录 openapi.json（部分 vaio 路由未收录，以本文 §4 为准）"],
        ],
        [3, 12],
    )

    add_heading(doc, "1.1 术语", 2)
    add_table(
        doc,
        ["术语", "含义"],
        [
            ["巡检业务", "inspection_work，设备+算法+规范编组与调度"],
            ["巡检事件", "inspection_event，视频/传感告警及处置"],
            ["VAIO", "视频分析推理服务，C++ 核心 + Python MCP/REST 薄层"],
            ["detecttype", "VAIO 算法配方 ID，对应 Algorithm_<id>.json"],
            ["权限点", "p-* ACL，如 p-dash、p-inspection、p-algo"],
        ],
        [4, 11],
    )

    add_heading(doc, "2. 系统架构", 1)
    doc.add_paragraph(
        "三层架构：webui（React/Vite）→ inspection_platform（FastAPI + SQLite/Chroma）"
        "→ 外部能力（vaio-analysis-core、LLM、Hermes Agent）。"
        "视频分析任务由 VAIO 在内存中运行，事件经 MemoryEventSink 暴露；"
        "平台业务数据持久化在 data/ 分域 SQLite。"
    )
    add_table(
        doc,
        ["组件", "端口/路径", "职责"],
        [
            ["webui", "5173", "用户看板 /user/*、管理台 /admin/*"],
            ["inspection_platform", "8001 /api/*", "业务 REST、鉴权、Agent SSE"],
            ["Hermes Dashboard", "/hermes-agent/*", "Agent 控制台、Cron、MCP 管理"],
            ["vaio-analysis-core", "9200 /v1/*", "视频任务、算法配方、实时事件"],
            ["vaio Python REST", "9201（可选）", "REST 薄层，自动补全防区"],
            ["vaio MCP", "stdio", "Hermes/Cursor 工具：vaio_start_task 等"],
        ],
        [4, 4, 8],
    )

    add_heading(doc, "3. 接口设计原则", 1)
    add_heading(doc, "3.1 通用约定", 2)
    bullets = [
        "REST 前缀：平台 /api/{domain}；VAIO /v1/{resource}；Hermes /hermes-agent/api/*。",
        "鉴权：平台 Bearer Token（auth_session）；公开：login、health、seed/builtin。",
        "实体 CRUD：列表 + 按 id 读 + 创建 + PATCH 更新 + DELETE；冲突 409，不存在 404。",
        "响应：JSON；Agent 对话使用 SSE（POST /api/chat/stream）。",
        "错误体建议：{ \"detail\": \"...\" }（FastAPI 默认）或业务 code + message。",
        "分页：列表接口逐步统一 limit/offset 或 cursor（当前多数全量/轻量分页）。",
    ]
    for b in bullets:
        doc.add_paragraph(b, style="List Bullet")

    add_heading(doc, "3.2 权限映射（摘要）", 2)
    add_table(
        doc,
        ["API 前缀", "读权限", "写权限"],
        [
            ["/api/inspection-events/stats", "p-dash", "—"],
            ["/api/inspection-events", "p-events", "p-events"],
            ["/api/inspection-work", "p-inspection-view", "p-inspection"],
            ["/api/inspection-reports、report-*", "p-reports", "p-reports"],
            ["/api/equipment、/api/region", "p-inspection-view", "p-device"],
            ["/api/algorithm、/vaio/*", "p-algo", "p-algo"],
            ["/api/knowledge、/api/spec", "p-knowledge", "p-knowledge"],
            ["/api/document", "p-docs", "p-docs"],
            ["/api/chat/stream", "—", "p-workflow"],
        ],
        [5, 4, 4],
    )

    add_heading(doc, "4. 平台业务接口（现状）", 1)

    domains = [
        ("4.1 认证 /api/auth", [
            ("POST", "/login", "已实现", "登录，返回 Bearer token"),
            ("POST", "/logout", "已实现", "注销会话"),
            ("GET", "/me", "已实现", "当前用户与权限"),
            ("GET", "/permissions", "已实现", "权限字典"),
            ("GET/POST/PATCH/DELETE", "/users/*", "已实现", "用户管理 p-perm"),
            ("POST", "/seed/builtin", "已实现", "演示账号种子"),
        ]),
        ("4.2 区域 /api/region", [
            ("GET/POST", "/", "已实现", "区域树 CRUD"),
            ("GET/PATCH/DELETE", "/{id}", "已实现", "删除有设备则 409"),
            ("POST", "/seed/builtin", "已实现", "内置区域"),
        ]),
        ("4.3 设备 /api/equipment", [
            ("GET/POST/PATCH/DELETE", "/*", "已实现", "设备台账 camera/sensor"),
            ("GET", "/{id}/readings", "部分", "传感读数只读；无数据时演示 seed"),
            ("POST", "/seed/builtin", "已实现", "演示设备"),
        ]),
        ("4.4 文档 /api/document", [
            ("POST", "/", "已实现", "multipart 上传"),
            ("GET/PATCH/DELETE", "/{doc_id}", "已实现", "元数据与下载"),
        ]),
        ("4.5 知识库 /api/knowledge", [
            ("POST", "/ingest", "已实现", "文档向量化入库"),
            ("POST", "/query", "已实现", "向量检索"),
            ("GET/DELETE", "/{kb_id}/documents/*", "已实现", "分片管理"),
            ("POST", "/cleanup-orphans", "已实现", "孤儿向量清理"),
        ]),
        ("4.6 规范 /api/spec", [
            ("GET/POST/PATCH/DELETE", "/rules/*", "已实现", "规范规则 CRUD"),
            ("POST", "/rules/extract", "已实现", "LLM 从文档抽取"),
            ("POST", "/rules/{id}/publish", "已实现", "发布并向量化"),
            ("POST", "/query/rules", "已实现", "规范向量检索"),
        ]),
        ("4.7 算法目录 /api/algorithm", [
            ("GET/POST/PATCH/DELETE", "/*", "已实现", "平台算法元数据"),
            ("POST", "/invoke/{algorithm_id}", "占位", "mock_invoke，未接真实推理"),
            ("GET", "/vaio/health", "已实现", "代理 VAIO 核心健康"),
            ("GET", "/vaio/algorithms", "已实现", "VAIO 配方列表"),
            ("GET", "/vaio/algorithms/{vaio_id}", "已实现", "单条配方"),
            ("POST", "/vaio/sync", "已实现", "同步为 vaio-{id} 平台记录"),
            ("GET", "/vaio/mcp-tools", "已实现", "MCP 工具清单"),
            ("POST", "/vaio/mcp/register", "已实现", "写入 Hermes config"),
        ]),
        ("4.8 巡检业务 /api/inspection-work", [
            ("GET/POST/PATCH/DELETE", "/*", "已实现", "业务编组与调度配置"),
            ("POST", "/generate", "部分", "LLM 编组；persist 已禁用"),
            ("POST", "/seed/builtin", "已实现", "演示业务"),
        ]),
        ("4.9 巡检事件 /api/inspection-events", [
            ("GET", "/stats", "已实现", "看板 KPI/趋势"),
            ("GET", "/runtime/works", "已实现", "运行态业务"),
            ("GET/POST/PATCH/DELETE", "/*", "已实现", "事件 CRUD 与处置"),
            ("POST", "/seed/builtin", "已实现", "演示事件"),
        ]),
        ("4.10 报告 /api/report-*", [
            ("CRUD", "report-templates", "已实现", "报告模板"),
            ("CRUD", "report-plans", "已实现", "计划与 toggle/generate"),
            ("CRUD", "inspection-reports", "已实现", "报告 publish/adhoc/seed"),
        ]),
        ("4.11 Agent /api/chat", [
            ("POST", "/stream", "已实现", "SSE ReAct；工具含 build_inspection_works"),
        ]),
        ("4.12 健康", [
            ("GET", "/health", "已实现", "平台探活"),
        ]),
    ]

    for title, rows in domains:
        add_heading(doc, title, 2)
        add_table(doc, ["方法", "路径", "状态", "说明"], rows, [2.5, 5, 2, 7])

    add_heading(doc, "5. VAIO 视频分析接口", 1)
    add_heading(doc, "5.1 C++ 核心 (:9200)", 2)
    add_table(
        doc,
        ["方法", "路径", "状态", "说明"],
        [
            ["GET", "/health", "已实现", "服务探活"],
            ["GET", "/v1/algorithms", "已实现", "扫描 Algorithm_*.json"],
            ["GET", "/v1/algorithms/{id}", "已实现", "单条配方"],
            ["POST", "/v1/tasks", "已实现", "启动任务；defence 必填"],
            ["DELETE", "/v1/tasks/{task_id}", "已实现", "停止任务"],
            ["GET", "/v1/events", "已实现", "task_id、limit 查询事件"],
            ["GET", "/v1/tasks", "占位", "固定空列表，待实现"],
        ],
        [2, 5, 2, 7],
    )

    add_heading(doc, "5.2 Python REST (:9201，可选)", 2)
    doc.add_paragraph("与核心同路径；POST /v1/tasks 在 defence 缺失时自动补全屏防区。")

    add_heading(doc, "5.3 MCP 工具（vaio_analysis）", 2)
    add_table(
        doc,
        ["工具名", "状态", "说明"],
        [
            ["vaio_health", "已实现", "核心健康"],
            ["vaio_list_algorithms", "已实现", "算法列表"],
            ["vaio_get_algorithm", "已实现", "算法详情"],
            ["vaio_start_task", "已实现", "启动视频分析"],
            ["vaio_stop_task", "已实现", "停止任务"],
            ["vaio_list_events", "已实现", "轮询检测事件"],
        ],
        [4, 2, 9],
    )

    add_heading(doc, "5.4 VAIO 任务请求体（POST /v1/tasks）", 2)
    doc.add_paragraph(
        "字段：task_id, video_url, src_data_type(2=文件), algorithms[].detecttype, "
        "algorithms[].config.defence（四点 0–100 百分比多边形）, holddowntime, sensitivity 等。"
        "modelid 在 Algorithm JSON 与 AlgModelConf.xml 映射（+1000）。"
    )

    add_heading(doc, "6. Hermes Agent 接口（摘要）", 1)
    doc.add_paragraph(
        "挂载于 /hermes-agent，与平台独立鉴权。核心类别：/api/status、/api/sessions、"
        "/api/config、/api/cron/jobs、/api/skills、/api/tools/toolsets、WebSocket /api/ws。"
        "Dashboard 插件含 Kanban（任务看板）、Achievements 等。"
        "原生 MCP：conversations_list、messages_send、events_poll 等。"
    )

    add_heading(doc, "7. 需求接口设计（待建设）", 1)
    doc.add_paragraph("以下接口为打通「触发任务 → 视频推理 → 事件入库 → 报告」闭环所必需。")

    add_heading(doc, "7.1 P0 — 核心业务闭环", 2)
    add_table(
        doc,
        ["优先级", "方法", "路径", "需求说明"],
        [
            ["P0", "POST", "/api/trigger-tasks", "自然语言/表单创建触发任务，替代前端 Mock"],
            ["P0", "GET", "/api/trigger-tasks", "触发任务列表与状态"],
            ["P0", "POST", "/api/trigger-tasks/{id}/execute", "执行：调度 VAIO 任务或 Agent 工作流"],
            ["P0", "POST", "/api/algorithm/invoke/{id}", "统一算法调用：接 VAIO 或外部 HTTP"],
            ["P0", "POST", "/api/inspection-events/ingest/vaio", "VAIO 事件批量/流式入库"],
            ["P0", "GET", "/v1/tasks", "VAIO 运行中任务列表（C++ 实现）"],
            ["P0", "GET", "/v1/tasks/{task_id}", "VAIO 单任务状态与指标"],
        ],
        [1.5, 2, 5.5, 7],
    )

    add_heading(doc, "7.2 P1 — 编排与设备", 2)
    add_table(
        doc,
        ["优先级", "方法", "路径", "需求说明"],
        [
            ["P1", "POST", "/api/inspection-work/generate", "恢复 persist=true，校验后落库"],
            ["P1", "POST", "/api/inspection-work/{id}/run", "按 schedule 启动关联 VAIO 任务"],
            ["P1", "POST", "/api/equipment/{id}/readings", "传感数据写入（IoT 接入）"],
            ["P1", "GET", "/api/equipment/{id}/stream", "摄像头流地址解析/代理"],
            ["P1", "POST", "/api/webhooks/vaio/events", "VAIO 推送事件到平台（可选替代轮询）"],
            ["P1", "PATCH", "/api/algorithm/{id}/health", "探活结果回写算法目录"],
        ],
        [1.5, 2, 5.5, 7],
    )

    add_heading(doc, "7.3 P2 — 体验与治理", 2)
    add_table(
        doc,
        ["优先级", "方法", "路径", "需求说明"],
        [
            ["P2", "GET", "/api/openapi/vaio", "VAIO 代理路由 OpenAPI 子集"],
            ["P2", "POST", "/api/auth/sso/hermes", "Hermes 与平台 SSO 票据交换"],
            ["P2", "GET", "/api/audit/logs", "关键写操作审计"],
            ["P2", "POST", "/api/knowledge/reindex", "全库重建向量（管理端一键）"],
            ["P2", "GET", "/api/inspection-events/export", "事件 CSV/Excel 导出"],
        ],
        [1.5, 2, 5.5, 7],
    )

    add_heading(doc, "7.4 触发任务执行流程（目标）", 2)
    doc.add_paragraph(
        "1) 用户在看板 /user/trigger-tasks 提交描述 → POST /api/trigger-tasks；"
        "2) Agent 或规则引擎生成 inspection_work 草案 → 用户确认；"
        "3) execute 调用 POST /api/algorithm/invoke 或 vaio /v1/tasks；"
        "4) 后台轮询 vaio /v1/events 或 webhook → POST ingest/vaio 写入 inspection_event；"
        "5) 报告计划自动关联 → POST /api/inspection-reports/generate-adhoc。"
    )

    add_heading(doc, "8. 数据实体与接口映射", 1)
    add_table(
        doc,
        ["实体", "主键", "主要 API"],
        [
            ["auth_user", "user_id", "/api/auth/users"],
            ["region", "id", "/api/region"],
            ["equipment", "id", "/api/equipment"],
            ["document", "id", "/api/document"],
            ["spec_rule", "rule_id", "/api/spec/rules"],
            ["algorithm", "algorithm_id", "/api/algorithm"],
            ["inspection_work", "work_id", "/api/inspection-work"],
            ["inspection_event", "event_id", "/api/inspection-events"],
            ["inspection_report", "report_id", "/api/inspection-reports"],
            ["VAIO task/event", "task_id", "/v1/tasks、/v1/events（内存）"],
        ],
        [4, 3, 8],
    )

    add_heading(doc, "9. 非功能需求", 1)
    nfr = [
        "可用性：平台 /api/health、VAIO /health 用于探活；关键服务独立重启。",
        "性能：VAIO 单节点建议 ≤16 路分析通道（VLAISvrConf）；事件 ingest 批量 ≤100 条/次。",
        "安全：生产环境禁用 seed/builtin；HTTPS；Hermes OAuth 按需启用。",
        "兼容：OpenAPI 与代码同步发布；VAIO engine TRT 版本与 GPU SM 一致。",
        "可观测：统一 request_id；VAIO logLevel 可配置。",
    ]
    for n in nfr:
        doc.add_paragraph(n, style="List Bullet")

    add_heading(doc, "10. 附录", 1)
    doc.add_paragraph("A. 参考文档：README.md、docs/entities-and-database.md、docs/auth-and-permissions.md、vaio-analysis-service/README.md")
    doc.add_paragraph("B. 启动命令：scripts/sia-dev.sh start all；vaio-analysis-service/scripts/run-core.sh")
    doc.add_paragraph("C. 文档维护：接口变更须同步 openapi.json 与本文档版本号。")

    DOCS.mkdir(parents=True, exist_ok=True)
    doc.save(DOCX_PATH)

    # Convert to .doc via LibreOffice
    subprocess.run(
        [
            "libreoffice",
            "--headless",
            "--convert-to",
            "doc",
            "--outdir",
            str(DOCS),
            str(DOCX_PATH),
        ],
        check=True,
        capture_output=True,
    )
    if DOC_PATH.exists():
        DOCX_PATH.unlink(missing_ok=True)


def build_xls():
    wb = xlwt.Workbook(encoding="utf-8")

    # Styles
    title_style = xlwt.easyxf(
        "font: bold on, height 280; align: horiz center, vert center;"
    )
    header_style = xlwt.easyxf(
        "font: bold on; pattern: pattern solid, fore_colour gray25; "
        "align: horiz center, vert center; borders: left thin, right thin, top thin, bottom thin;"
    )
    cell_style = xlwt.easyxf(
        "align: vert top, wrap on; borders: left thin, right thin, top thin, bottom thin;"
    )
    cell_center = xlwt.easyxf(
        "align: horiz center, vert center; borders: left thin, right thin, top thin, bottom thin;"
    )

    # Sheet 1: 总览
    ws0 = wb.add_sheet("项目总览")
    ws0.write_merge(0, 0, 0, 5, "物盟智能巡检 Agent 平台 — 项目排期总览", title_style)
    overview = [
        ("项目名称", PROJECT),
        ("文档版本", VERSION),
        ("排期基准日", DOC_DATE.isoformat()),
        ("计划周期", "2026-06-09 ~ 2026-08-29（约 12 周）"),
        ("里程碑 M1", "2026-06-27 — 接口文档与 OpenAPI 同步"),
        ("里程碑 M2", "2026-07-18 — VAIO 闭环 + 触发任务后端"),
        ("里程碑 M3", "2026-08-08 — 事件入库 + 报告联动"),
        ("里程碑 M4", "2026-08-29 — 集成测试与试运行"),
    ]
    for i, (k, v) in enumerate(overview, start=2):
        ws0.write(i, 0, k, header_style)
        ws0.write(i, 1, v, cell_style)
    ws0.col(0).width = 5000
    ws0.col(1).width = 20000

    # Sheet 2: 详细排期
    ws = wb.add_sheet("详细排期")
    headers = [
        "序号",
        "阶段",
        "模块",
        "任务",
        "优先级",
        "状态",
        "负责人",
        "开始日期",
        "结束日期",
        "工时(人天)",
        "依赖",
        "交付物",
    ]
    for c, h in enumerate(headers):
        ws.write(0, c, h, header_style)

    start = date(2026, 6, 9)
    tasks = [
        ("1", "阶段一", "文档", "梳理并发布需求接口设计文档、更新 openapi.json", "P0", "进行中", "后端", 0, 3, "", "本文档、openapi.json"),
        ("2", "阶段一", "规范", "实体文档与 inspection-events POST 描述对齐", "P1", "待开始", "后端", 3, 2, "1", "entities-and-database.md"),
        ("3", "阶段一", "前端", "webui 5173 稳定启动脚本（EIO 修复）", "P1", "待开始", "前端", 3, 2, "", "sia-dev.sh 增强"),
        ("4", "阶段二", "VAIO", "C++ 实现 GET /v1/tasks 任务列表", "P0", "待开始", "算法", 5, 5, "", "vaio-analysis-core"),
        ("5", "阶段二", "VAIO", "GET /v1/tasks/{id} 任务状态与指标", "P0", "待开始", "算法", 8, 4, "4", "REST 接口"),
        ("6", "阶段二", "平台", "POST /api/algorithm/invoke 对接 VAIO", "P0", "待开始", "后端", 5, 8, "4", "algorithm/service.py"),
        ("7", "阶段二", "平台", "VAIO 代理路由写入 openapi.json", "P1", "待开始", "后端", 5, 2, "1", "openapi.json"),
        ("8", "阶段二", "平台", "POST /api/inspection-events/ingest/vaio", "P0", "待开始", "后端", 10, 8, "6", "事件入库服务"),
        ("9", "阶段二", "平台", "VAIO 事件轮询/推送 Worker", "P0", "待开始", "后端", 12, 6, "8", "后台任务模块"),
        ("10", "阶段三", "触发任务", "设计 trigger_task 实体与 SQLite", "P0", "待开始", "后端", 15, 3, "1", "db.py + service"),
        ("11", "阶段三", "触发任务", "POST/GET /api/trigger-tasks CRUD", "P0", "待开始", "后端", 18, 5, "10", "routes/trigger_task.py"),
        ("12", "阶段三", "触发任务", "POST .../execute 编排 VAIO+Agent", "P0", "待开始", "后端", 23, 8, "6,11", "执行引擎"),
        ("13", "阶段三", "前端", "TriggerTaskPage 接真实 API", "P0", "待开始", "前端", 23, 5, "11", "替换 triggerTaskMock"),
        ("14", "阶段三", "Agent", "build_inspection_works 支持 persist 可选", "P1", "待开始", "后端", 28, 4, "11", "inspection_work/tool.py"),
        ("15", "阶段四", "巡检业务", "POST /inspection-work/{id}/run 调度", "P1", "待开始", "后端", 31, 6, "6,12", "调度器"),
        ("16", "阶段四", "巡检业务", "恢复 /generate persist=true（校验后）", "P1", "待开始", "后端", 31, 4, "14", "inspection_work route"),
        ("17", "阶段四", "报告", "事件→报告 adhoc 自动关联", "P1", "待开始", "后端", 35, 5, "8", "report service"),
        ("18", "阶段五", "规范知识库", "规范 PATCH doc_id 原子性（SPEC-KNOW-001）", "P1", "待开始", "后端", 38, 4, "", "specification/service"),
        ("19", "阶段五", "规范知识库", "发布/删文档一致性（P1 审计项）", "P1", "待开始", "后端", 42, 5, "18", "事务与清理"),
        ("20", "阶段五", "前端", "知识库 preflight/重新向量化 UI", "P2", "待开始", "前端", 42, 5, "19", "KnowledgePage"),
        ("21", "阶段六", "设备", "POST /equipment/{id}/readings 写入", "P1", "待开始", "后端", 47, 5, "", "equipment service"),
        ("22", "阶段六", "设备", "摄像头 stream URL 解析 API", "P2", "待开始", "后端", 52, 4, "21", "equipment route"),
        ("23", "阶段七", "Hermes", "平台与 Hermes SSO 票据（可选）", "P2", "待开始", "后端", 52, 5, "", "auth 扩展"),
        ("24", "阶段七", "Hermes", "vaio MCP 注册一键化文档", "P2", "待开始", "全栈", 52, 2, "7", "运维手册"),
        ("25", "阶段八", "测试", "VAIO+平台集成测试用例", "P0", "待开始", "测试", 57, 8, "8,12", "tests/integration"),
        ("26", "阶段八", "测试", "E2E：触发任务→事件→报告", "P0", "待开始", "测试", 65, 6, "25", "E2E 脚本"),
        ("27", "阶段八", "上线", "生产部署与监控探活", "P0", "待开始", "运维", 71, 5, "26", "部署文档"),
    ]

    for r, row in enumerate(tasks, start=1):
        seq, phase, module, name, pri, status, owner, off_start, days, dep, deliver = row
        d_start = start + timedelta(days=off_start)
        d_end = d_start + timedelta(days=days - 1)
        values = [
            seq,
            phase,
            module,
            name,
            pri,
            status,
            owner,
            d_start.isoformat(),
            d_end.isoformat(),
            days,
            dep,
            deliver,
        ]
        for c, val in enumerate(values):
            st = cell_center if c in (0, 4, 5, 6, 7, 8, 9) else cell_style
            ws.write(r, c, val, st)

    widths = [1800, 3500, 3500, 12000, 2200, 2500, 2500, 3200, 3200, 2800, 3500, 8000]
    for i, w in enumerate(widths):
        ws.col(i).width = w
    ws.row(0).height_mismatch = True
    ws.row(0).height = 500

    # Sheet 3: 接口交付对照
    ws2 = wb.add_sheet("接口交付对照")
    h2 = ["优先级", "接口", "负责模块", "计划完成", "关联任务序号"]
    for c, h in enumerate(h2):
        ws2.write(0, c, h, header_style)
    api_rows = [
        ("P0", "GET /v1/tasks", "VAIO C++", "2026-06-20", "4"),
        ("P0", "GET /v1/tasks/{id}", "VAIO C++", "2026-06-24", "5"),
        ("P0", "POST /api/algorithm/invoke/{id}", "平台", "2026-06-27", "6"),
        ("P0", "POST /api/inspection-events/ingest/vaio", "平台", "2026-07-04", "8"),
        ("P0", "POST /api/trigger-tasks", "平台", "2026-07-11", "11"),
        ("P0", "POST /api/trigger-tasks/{id}/execute", "平台", "2026-07-18", "12"),
        ("P1", "POST /api/inspection-work/{id}/run", "平台", "2026-07-25", "15"),
        ("P1", "POST /api/equipment/{id}/readings", "平台", "2026-08-01", "21"),
        ("P2", "POST /api/auth/sso/hermes", "平台", "2026-08-08", "23"),
    ]
    for r, row in enumerate(api_rows, start=1):
        for c, val in enumerate(row):
            ws2.write(r, c, val, cell_style)
    for i, w in enumerate([2000, 12000, 3500, 3500, 3500]):
        ws2.col(i).width = w

    # Sheet 4: 人力
    ws3 = wb.add_sheet("人力投入")
    ws3.write_merge(0, 0, 0, 3, "人力投入估算（人天）", title_style)
    roles = [
        ("后端", 45, "平台 API、事件入库、触发任务"),
        ("前端", 18, "看板、触发任务、知识库 UI"),
        ("算法/C++", 15, "VAIO 任务列表、engine 维护"),
        ("测试", 14, "集成与 E2E"),
        ("运维", 5, "部署与监控"),
    ]
    ws3.write(2, 0, "角色", header_style)
    ws3.write(2, 1, "人天", header_style)
    ws3.write(2, 2, "说明", header_style)
    ws3.write(2, 3, "备注", header_style)
    total = 0
    for i, (role, days, note) in enumerate(roles, start=3):
        ws3.write(i, 0, role, cell_style)
        ws3.write(i, 1, days, cell_center)
        ws3.write(i, 2, note, cell_style)
        ws3.write(i, 3, "可并行", cell_style)
        total += days
    ws3.write(len(roles) + 3, 0, "合计", header_style)
    ws3.write(len(roles) + 3, 1, total, cell_center)
    ws3.col(0).width = 4000
    ws3.col(1).width = 2500
    ws3.col(2).width = 12000
    ws3.col(3).width = 4000

    wb.save(str(XLS_PATH))


def main():
    build_word()
    build_xls()
    print(f"Generated: {DOC_PATH}")
    print(f"Generated: {XLS_PATH}")


if __name__ == "__main__":
    main()
