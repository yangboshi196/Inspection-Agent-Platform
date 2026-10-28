#!/usr/bin/env python3
"""Generate docs/排期.xls with node-level WBS breakdown."""
from __future__ import annotations

from pathlib import Path

import xlwt

REPO = Path(__file__).resolve().parents[1]
XLS_PATH = REPO / "docs" / "排期.xls"
PROJECT = "物盟智能巡检 Agent 平台（SIA_agent）"
DOC_DATE = "2026-06-09"


def build_xls():
    wb = xlwt.Workbook(encoding="utf-8")

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

    headers = [
        "序号",
        "阶段",
        "一级节点",
        "二级节点",
        "任务名称",
        "优先级",
        "状态",
        "负责人",
        "开始日期",
        "结束日期",
        "工时(人天)",
        "前置依赖",
        "交付物",
    ]
    widths = [2000, 3200, 3800, 3800, 14000, 2200, 2500, 2800, 3200, 3200, 2800, 3200, 10000]

    def write_sheet(ws, rows):
        for c, h in enumerate(headers):
            ws.write(0, c, h, header_style)
        for r, row in enumerate(rows, start=1):
            for c, val in enumerate(row):
                st = cell_center if c in (0, 5, 6, 7, 8, 9, 10) else cell_style
                ws.write(r, c, val, st)
        for i, w in enumerate(widths):
            ws.col(i).width = w
        ws.row(0).height_mismatch = True
        ws.row(0).height = 500

    # ── Sheet 1: 项目总览 ──
    ws0 = wb.add_sheet("项目总览")
    ws0.write_merge(0, 0, 0, 6, "物盟智能巡检 Agent 平台 — 节点排期总览", title_style)
    overview = [
        ("项目名称", PROJECT),
        ("文档版本", "V1.1（节点细分 WBS）"),
        ("排期基准日", DOC_DATE),
        ("计划周期", "2026-06-09 ~ 2026-08-29（约 12 周）"),
        ("WBS 子任务", "74 项 / 8 阶段 / 8 张阶段子表"),
        ("里程碑 M1", "2026-06-20 — 基线文档 + OpenAPI + 环境稳定"),
        ("里程碑 M2", "2026-07-04 — VAIO 任务查询 + 事件入库"),
        ("里程碑 M3", "2026-07-25 — 触发任务后端 + 前端闭环"),
        ("里程碑 M4", "2026-08-29 — 集成测试 + UAT 试运行"),
    ]
    for i, (k, v) in enumerate(overview, start=2):
        ws0.write(i, 0, k, header_style)
        ws0.write(i, 1, v, cell_style)
    ws0.col(0).width = 5500
    ws0.col(1).width = 22000

    # ── Sheet 2: 阶段节点汇总 ──
    ws_phase = wb.add_sheet("阶段节点汇总")
    ph_headers = ["阶段", "一级节点", "子任务数", "计划开始", "计划结束", "工期(天)", "里程碑", "关键交付"]
    for c, h in enumerate(ph_headers):
        ws_phase.write(0, c, h, header_style)
    phase_summary = [
        ("阶段一", "基线与文档", 8, "2026-06-09", "2026-06-20", 10, "M1", "接口设计文档、openapi 补全、EIO 修复"),
        ("阶段二", "VAIO 集成闭环", 16, "2026-06-16", "2026-07-04", 14, "M2", "v1/tasks、invoke、ingest、Worker"),
        ("阶段三", "触发任务", 12, "2026-07-07", "2026-07-25", 15, "M3", "trigger_task CRUD、execute、前端对接"),
        ("阶段四", "巡检调度与报告", 8, "2026-07-21", "2026-08-01", 10, "—", "work/run、generate persist、报告联动"),
        ("阶段五", "规范知识库加固", 10, "2026-07-28", "2026-08-08", 10, "—", "SPEC-KNOW 修复、重新向量化 UI"),
        ("阶段六", "设备与传感", 6, "2026-08-04", "2026-08-15", 8, "—", "readings 写入、stream、传感事件"),
        ("阶段七", "Hermes 协同", 5, "2026-08-11", "2026-08-18", 6, "—", "MCP 注册、SSO 方案"),
        ("阶段八", "测试与上线", 9, "2026-08-18", "2026-08-29", 10, "M4", "集成/E2E、压测、UAT、部署"),
    ]
    for r, row in enumerate(phase_summary, start=1):
        for c, val in enumerate(row):
            ws_phase.write(r, c, val, cell_center if c != 7 else cell_style)
    for i, w in enumerate([3200, 4500, 2500, 3200, 3200, 2500, 2200, 14000]):
        ws_phase.col(i).width = w

    # ── Build WBS ──
    wbs: list[tuple] = []

    def add(phase, l1, l2, name, pri, owner, start, end, days, dep="", deliver="", status="待开始"):
        wbs.append(
            (
                f"{len(wbs)+1:03d}",
                phase,
                l1,
                l2,
                name,
                pri,
                status,
                owner,
                start,
                end,
                days,
                dep,
                deliver,
            )
        )

    # 阶段一
    P1 = "阶段一"
    add(P1, "文档", "需求", "编制需求接口设计文档（业务域+现状+规划）", "P0", "产品", "2026-06-09", "2026-06-10", 2, "", "需求接口设计文档.doc", "进行中")
    add(P1, "文档", "需求", "评审接口文档并确认 P0/P1 接口清单", "P0", "产品", "2026-06-11", "2026-06-11", 1, "001", "评审纪要")
    add(P1, "文档", "OpenAPI", "补全 /api/algorithm/vaio/* 到 openapi.json", "P0", "后端", "2026-06-09", "2026-06-11", 2, "", "openapi.json")
    add(P1, "文档", "OpenAPI", "补全 knowledge/region/inspection seed 路由", "P1", "后端", "2026-06-12", "2026-06-13", 2, "003", "openapi.json")
    add(P1, "文档", "实体", "entities-and-database 对齐 inspection-events POST", "P1", "后端", "2026-06-12", "2026-06-13", 2, "", "entities-and-database.md")
    add(P1, "文档", "审计", "project-issues-audit P0/P1 条目排期确认", "P1", "产品", "2026-06-14", "2026-06-14", 1, "002", "审计排期表")
    add(P1, "环境", "DevOps", "webui Vite EIO 崩溃修复（nohup/CI=1）", "P1", "前端", "2026-06-15", "2026-06-17", 3, "", "sia-dev.sh")
    add(P1, "环境", "DevOps", "一键启动验证清单（5173/8001/9200）", "P1", "运维", "2026-06-18", "2026-06-20", 2, "007", "启动检查文档")

    # 阶段二
    P2 = "阶段二"
    add(P2, "VAIO C++", "任务列表", "TaskManager 暴露运行中任务枚举接口", "P0", "算法", "2026-06-16", "2026-06-18", 3, "", "TaskManager API")
    add(P2, "VAIO C++", "任务列表", "AnalysisHttpServer 实现 GET /v1/tasks", "P0", "算法", "2026-06-19", "2026-06-22", 3, "009", "AnalysisHttpServer.cpp")
    add(P2, "VAIO C++", "任务详情", "设计任务状态 JSON（进度/帧率/算法）", "P0", "算法", "2026-06-19", "2026-06-20", 2, "009", "接口字段说明")
    add(P2, "VAIO C++", "任务详情", "实现 GET /v1/tasks/{task_id}", "P0", "算法", "2026-06-23", "2026-06-25", 3, "011", "REST 接口")
    add(P2, "VAIO C++", "构建", "重编 vaio-analysis-core 并 rsync 部署", "P0", "算法", "2026-06-26", "2026-06-26", 1, "012", "二进制")
    add(P2, "VAIO Python", "薄层", "api_app 同步 tasks 路由", "P1", "后端", "2026-06-27", "2026-06-27", 1, "013", "api_app.py")
    add(P2, "VAIO Python", "MCP", "MCP 增加 vaio_list_tasks / vaio_get_task", "P2", "后端", "2026-06-27", "2026-06-28", 2, "013", "mcp_server.py")
    add(P2, "平台", "客户端", "vaio_client 封装 list_tasks / get_task", "P0", "后端", "2026-06-23", "2026-06-24", 2, "012", "vaio_client.py")
    add(P2, "平台", "invoke", "algorithm invoke 抽象（vaio/mock/http 策略）", "P0", "后端", "2026-06-23", "2026-06-25", 3, "", "invoke 设计")
    add(P2, "平台", "invoke", "invoke 对接 vaio POST/DELETE /v1/tasks", "P0", "后端", "2026-06-26", "2026-06-30", 4, "017,018", "algorithm/service.py")
    add(P2, "平台", "invoke", "invoke 单元测试 + test-ship-algo 脚本", "P0", "测试", "2026-07-01", "2026-07-02", 2, "019", "tests/")
    add(P2, "平台", "事件", "VAIO event → inspection_event 字段映射设计", "P0", "后端", "2026-06-26", "2026-06-27", 2, "", "映射表")
    add(P2, "平台", "事件", "POST /api/inspection-events/ingest/vaio 实现", "P0", "后端", "2026-06-28", "2026-07-01", 3, "021", "routes + service")
    add(P2, "平台", "事件", "ingest 幂等去重（task_id+timestamp+detecttype）", "P0", "后端", "2026-07-02", "2026-07-03", 2, "022", "去重逻辑")
    add(P2, "平台", "Worker", "后台 Worker 轮询 vaio /v1/events", "P0", "后端", "2026-07-02", "2026-07-04", 3, "022", "worker 模块")
    add(P2, "平台", "Worker", "Worker 启停脚本与环境变量配置", "P1", "运维", "2026-07-03", "2026-07-04", 2, "024", "scripts/")

    # 阶段三
    P3 = "阶段三"
    add(P3, "数据", "实体", "trigger_task 表结构与状态机设计", "P0", "后端", "2026-07-07", "2026-07-08", 2, "008", "设计文档")
    add(P3, "数据", "实体", "trigger_task db.py + config.py + init_db", "P0", "后端", "2026-07-09", "2026-07-10", 2, "026", "db.py")
    add(P3, "数据", "实体", "trigger_task service CRUD", "P0", "后端", "2026-07-11", "2026-07-13", 3, "027", "service.py")
    add(P3, "API", "路由", "routes/trigger_task.py + app 挂载", "P0", "后端", "2026-07-14", "2026-07-15", 2, "028", "routes")
    add(P3, "API", "路由", "guard 权限 p-trigger-task 映射", "P0", "后端", "2026-07-14", "2026-07-14", 1, "029", "guard.py")
    add(P3, "API", "路由", "POST/GET/PATCH/DELETE /api/trigger-tasks", "P0", "后端", "2026-07-16", "2026-07-18", 3, "030", "CRUD API")
    add(P3, "执行", "引擎", "execute：解析自然语言/参数 → work 草案", "P0", "后端", "2026-07-16", "2026-07-19", 3, "031", "execute 模块")
    add(P3, "执行", "引擎", "execute：调用 algorithm/invoke 启动 VAIO", "P0", "后端", "2026-07-20", "2026-07-22", 3, "019,032", "execute 模块")
    add(P3, "执行", "引擎", "execute：状态回写 + 失败重试策略", "P1", "后端", "2026-07-23", "2026-07-24", 2, "033", "状态机")
    add(P3, "前端", "看板", "triggerTaskApi.ts 封装", "P0", "前端", "2026-07-18", "2026-07-19", 2, "031", "api.ts")
    add(P3, "前端", "看板", "TriggerTaskPage 替换 triggerTaskMock", "P0", "前端", "2026-07-20", "2026-07-23", 4, "033", "TriggerTaskPage.tsx")
    add(P3, "前端", "看板", "执行进度与结果展示（轮询 trigger 状态）", "P1", "前端", "2026-07-24", "2026-07-25", 2, "035", "UI")

    # 阶段四
    P4 = "阶段四"
    add(P4, "巡检业务", "调度", "inspection-work run 调度器设计（cron/interval）", "P1", "后端", "2026-07-21", "2026-07-22", 2, "019", "设计文档")
    add(P4, "巡检业务", "调度", "POST /api/inspection-work/{id}/run 实现", "P1", "后端", "2026-07-23", "2026-07-26", 4, "038", "routes + scheduler")
    add(P4, "巡检业务", "调度", "run 与 VAIO task_id 关联存储", "P1", "后端", "2026-07-27", "2026-07-28", 2, "039", "work 扩展字段")
    add(P4, "巡检业务", "Agent", "恢复 POST /generate persist=true（校验后）", "P1", "后端", "2026-07-23", "2026-07-25", 3, "031", "inspection_work route")
    add(P4, "巡检业务", "Agent", "build_inspection_works tool persist 可选参数", "P1", "后端", "2026-07-26", "2026-07-27", 2, "041", "tool.py")
    add(P4, "报告", "联动", "事件入库 → adhoc 报告触发规则", "P1", "后端", "2026-07-28", "2026-07-30", 3, "022", "report service")
    add(P4, "报告", "联动", "看板 stats 接 Worker 真实运行态", "P1", "前端", "2026-07-31", "2026-08-01", 2, "024", "DashboardPage")
    add(P4, "报告", "联动", "报告详情展示关联 VAIO 事件快照", "P2", "前端", "2026-07-31", "2026-08-01", 2, "043", "ReportDetail")

    # 阶段五
    P5 = "阶段五"
    add(P5, "规范", "SPEC-001", "PATCH doc_id 同步 source_trace", "P1", "后端", "2026-07-28", "2026-07-29", 2, "", "specification/service.py")
    add(P5, "规范", "SPEC-002", "publish 最终校验失败回滚 draft", "P1", "后端", "2026-07-28", "2026-07-30", 3, "", "publish_rule")
    add(P5, "规范", "SPEC-003", "抽取 persist 拒绝空 doc_id", "P1", "后端", "2026-07-31", "2026-08-01", 2, "", "extractor.py")
    add(P5, "规范", "SPEC-004", "删文档/规范 doc_id 引用检查统一", "P1", "后端", "2026-07-31", "2026-08-02", 3, "046", "document + spec")
    add(P5, "规范", "SPEC-005", "文档改名遍历全 kb metadata 同步", "P1", "后端", "2026-08-03", "2026-08-04", 2, "", "document/service.py")
    add(P5, "规范", "SPEC-008", "cleanup-orphans 定时/管理端触发", "P1", "后端", "2026-08-03", "2026-08-05", 3, "", "knowledge route")
    add(P5, "前端", "知识库", "选中文档「重新向量化」按钮", "P2", "前端", "2026-08-04", "2026-08-06", 3, "050", "KnowledgePage.tsx")
    add(P5, "前端", "知识库", "抽取 preflight UI 接线", "P2", "前端", "2026-08-05", "2026-08-07", 3, "", "KnowledgePage.tsx")
    add(P5, "前端", "规范", "删文档/删规范引用拦截提示", "P1", "前端", "2026-08-06", "2026-08-08", 3, "048", "KnowledgePage + Spec")
    add(P5, "测试", "回归", "规范流程端到端回归（抽取→发布→业务）", "P1", "测试", "2026-08-07", "2026-08-08", 2, "052", "测试用例")

    # 阶段六
    P6 = "阶段六"
    add(P6, "设备", "传感", "POST /api/equipment/{id}/readings 设计", "P1", "后端", "2026-08-04", "2026-08-05", 2, "", "API 设计")
    add(P6, "设备", "传感", "readings 写入 service + 批量导入", "P1", "后端", "2026-08-06", "2026-08-08", 3, "055", "equipment/service.py")
    add(P6, "设备", "传感", "传感阈值 → inspection_event 规则", "P1", "后端", "2026-08-09", "2026-08-11", 3, "056", "event ingest")
    add(P6, "设备", "视频", "GET /equipment/{id}/stream URL 解析", "P2", "后端", "2026-08-09", "2026-08-11", 3, "", "equipment route")
    add(P6, "设备", "视频", "RTSP 地址与 VAIO video_url 对接文档", "P2", "算法", "2026-08-12", "2026-08-13", 2, "058", "运维文档")
    add(P6, "前端", "设备", "设备页展示实时读数（接真实 API）", "P2", "前端", "2026-08-12", "2026-08-15", 4, "056", "DevicesPage")

    # 阶段七
    P7 = "阶段七"
    add(P7, "Hermes", "MCP", "vaio MCP config 模板与校验脚本", "P1", "后端", "2026-08-11", "2026-08-12", 2, "008", "config 模板")
    add(P7, "Hermes", "MCP", "算法管理页一键 register + reload 指引", "P2", "前端", "2026-08-13", "2026-08-14", 2, "061", "AlgorithmsPage")
    add(P7, "Hermes", "SSO", "平台 Bearer 与 Hermes session 方案评审", "P2", "架构", "2026-08-11", "2026-08-12", 2, "", "方案文档")
    add(P7, "Hermes", "SSO", "POST /api/auth/sso/hermes 实现（可选）", "P2", "后端", "2026-08-15", "2026-08-17", 3, "063", "auth 扩展")
    add(P7, "Hermes", "文档", "Hermes+VAIO 联调运维手册", "P2", "全栈", "2026-08-15", "2026-08-18", 2, "061", "docs/")

    # 阶段八
    P8 = "阶段八"
    add(P8, "测试", "单元", "trigger_task / ingest / invoke 单元测试", "P0", "测试", "2026-08-18", "2026-08-20", 3, "031,022,019", "tests/")
    add(P8, "测试", "集成", "VAIO+平台集成测试（启动→任务→事件）", "P0", "测试", "2026-08-18", "2026-08-22", 5, "024", "tests/integration/")
    add(P8, "测试", "E2E", "E2E：触发任务→VAIO→事件→看板", "P0", "测试", "2026-08-21", "2026-08-24", 4, "067", "E2E 脚本")
    add(P8, "测试", "E2E", "E2E：巡检业务 run→报告生成", "P1", "测试", "2026-08-23", "2026-08-25", 3, "039,043", "E2E 脚本")
    add(P8, "测试", "性能", "VAIO 多路通道压测（≤16 路）", "P1", "算法", "2026-08-22", "2026-08-24", 3, "013", "压测报告")
    add(P8, "上线", "部署", "生产 docker-compose / systemd 部署文档", "P0", "运维", "2026-08-25", "2026-08-26", 2, "", "部署文档")
    add(P8, "上线", "部署", "探活告警（8001/9200/5173）", "P0", "运维", "2026-08-26", "2026-08-27", 2, "071", "监控配置")
    add(P8, "上线", "UAT", "UAT 用例执行与缺陷修复窗口", "P0", "全员", "2026-08-25", "2026-08-28", 4, "068", "UAT 报告")
    add(P8, "上线", "发布", "v1.0 试运行发布与回滚预案", "P0", "运维", "2026-08-29", "2026-08-29", 1, "073", "发布说明")

    # ── Sheet 3: 详细排期 WBS ──
    ws = wb.add_sheet("详细排期WBS")
    write_sheet(ws, wbs)

    # ── Per-phase sheets ──
    phase_map: dict[str, list] = {}
    for row in wbs:
        phase_map.setdefault(row[1], []).append(row)
    for phase_name, rows in phase_map.items():
        ws_p = wb.add_sheet(phase_name[:31])
        write_sheet(ws_p, rows)

    # ── 接口交付对照 ──
    ws2 = wb.add_sheet("接口交付对照")
    h2 = ["优先级", "接口", "阶段", "负责", "计划完成", "WBS序号", "子任务"]
    for c, h in enumerate(h2):
        ws2.write(0, c, h, header_style)
    api_rows = [
        ("P0", "GET /v1/tasks", "阶段二", "算法", "2026-06-22", "010", "任务列表 HTTP"),
        ("P0", "GET /v1/tasks/{id}", "阶段二", "算法", "2026-06-25", "012", "任务详情 HTTP"),
        ("P0", "POST /api/algorithm/invoke/{id}", "阶段二", "后端", "2026-06-30", "019", "invoke 对接 VAIO"),
        ("P0", "POST /api/inspection-events/ingest/vaio", "阶段二", "后端", "2026-07-01", "022", "事件批量入库"),
        ("P0", "POST /api/trigger-tasks", "阶段三", "后端", "2026-07-18", "031", "触发任务 CRUD"),
        ("P0", "POST /api/trigger-tasks/{id}/execute", "阶段三", "后端", "2026-07-22", "033", "执行引擎"),
        ("P1", "POST /api/inspection-work/{id}/run", "阶段四", "后端", "2026-07-26", "039", "业务调度"),
        ("P1", "POST /api/equipment/{id}/readings", "阶段六", "后端", "2026-08-08", "056", "传感写入"),
        ("P2", "POST /api/auth/sso/hermes", "阶段七", "后端", "2026-08-17", "064", "SSO 可选"),
    ]
    for r, row in enumerate(api_rows, start=1):
        for c, val in enumerate(row):
            ws2.write(r, c, val, cell_style)
    for i, w in enumerate([2000, 12000, 3200, 2500, 3200, 2500, 8000]):
        ws2.col(i).width = w

    # ── 人力投入（按阶段×角色）──
    ws3 = wb.add_sheet("人力投入")
    ws3.write_merge(0, 0, 0, 7, "人力投入估算（按阶段 × 角色，人天）", title_style)
    role_headers = ["阶段", "后端", "前端", "算法", "测试", "运维", "产品/架构", "合计"]
    for c, h in enumerate(role_headers):
        ws3.write(2, c, h, header_style)
    effort = [
        ("阶段一", 4, 3, 0, 0, 2, 3, 12),
        ("阶段二", 18, 0, 12, 2, 2, 0, 34),
        ("阶段三", 16, 8, 0, 0, 0, 0, 24),
        ("阶段四", 12, 4, 0, 0, 0, 0, 16),
        ("阶段五", 12, 8, 0, 2, 0, 0, 22),
        ("阶段六", 8, 4, 2, 0, 0, 0, 14),
        ("阶段七", 3, 2, 0, 0, 0, 3, 8),
        ("阶段八", 0, 0, 3, 18, 5, 4, 30),
    ]
    tot = [0] * 6
    for i, row in enumerate(effort, start=3):
        for c, val in enumerate(row):
            ws3.write(i, c, val, cell_center if c > 0 else cell_style)
            if 1 <= c <= 6:
                tot[c - 1] += val
    tr = len(effort) + 3
    ws3.write(tr, 0, "合计", header_style)
    grand = 0
    for c, v in enumerate(tot, start=1):
        ws3.write(tr, c, v, cell_center)
        grand += v
    ws3.write(tr, 7, grand, cell_center)
    for i, w in enumerate([3500] + [2800] * 7):
        ws3.col(i).width = w

    # ── 关键依赖链 ──
    ws4 = wb.add_sheet("关键依赖链")
    ws4.write_merge(0, 0, 0, 1, "关键路径依赖链", title_style)
    chains = [
        ("主链路", "008 环境就绪 → 010 v1/tasks → 019 invoke → 022 ingest → 024 Worker → 033 execute → 035 前端 → 068 E2E"),
        ("触发任务", "026 表设计 → 031 CRUD → 032 execute草案 → 033 invoke → 035 前端Mock替换"),
        ("规范加固", "046 PATCH trace → 047 publish回滚 → 048 doc_id检查 → 052 回归"),
        ("VAIO构建", "009 TaskManager → 010 GET tasks → 013 重编部署 → 020 invoke测试"),
    ]
    ws4.write(2, 0, "链路", header_style)
    ws4.write(2, 1, "依赖序列（WBS 序号）", header_style)
    for i, (name, chain) in enumerate(chains, start=3):
        ws4.write(i, 0, name, cell_style)
        ws4.write(i, 1, chain, cell_style)
    ws4.col(0).width = 4000
    ws4.col(1).width = 25000

    XLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(XLS_PATH))
    print(f"WBS tasks: {len(wbs)}")
    print(f"Generated: {XLS_PATH}")


if __name__ == "__main__":
    build_xls()
