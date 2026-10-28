"""向 report_template 表追加常用报告模版（可重复执行，已存在 id 则跳过）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inspection_platform.report.service import ReportService

EXTRA_TEMPLATES: list[dict] = [
    {
        "template_id": "tpl-pm-weekly",
        "name": "物业运营周报模版",
        "description": "周报汇总：规范对照、业务覆盖、区域执行与告警闭环",
        "filename": "pm-weekly-template.md",
        "content": """# 报告摘要
本周巡检总体情况、重点告警与待办事项一览。

# 规范
## 对照条款清单
列出本周对照的安全/服务规范条款及符合情况。

# 巡检业务
## 关联巡检业务执行情况
各在线巡检业务的执行次数、覆盖率与异常项。

# 区域
## 覆盖区域范围
本周实际覆盖的区域/点位及未覆盖说明。

# 巡检结果
## 执行与告警汇总
按告警等级统计事件数量、处置进度与复发项。
## 服务品质结论
综合合规率变化、业主关注项与改进建议。""",
        "size_label": "2.1 KB",
    },
    {
        "template_id": "tpl-daily-ops",
        "name": "物业服务日报模版",
        "description": "晨会/日清用：当日执行摘要",
        "filename": "daily-ops-template.md",
        "content": """# 报告摘要
{date} 各区域日常巡检与服务执行情况摘要。

# 规范
## 当日对照重点
当日需重点关注的规范条款与检查项。

# 巡检业务
## 业务执行概况
各巡检业务今日执行次数、完成率与未完成原因。

# 区域
## 区域覆盖
今日覆盖区域、遗漏区域及补检安排。

# 巡检结果
## 告警与处置
新增告警、已处置、待跟进事项清单。
## 明日关注
需次日优先跟进的风险点与作业安排。""",
        "size_label": "1.4 KB",
    },
    {
        "template_id": "tpl-monthly-compliance",
        "name": "月度合规报告模版",
        "description": "正式归档：月度合规率与整改闭环",
        "filename": "monthly-compliance-template.md",
        "content": """# 报告摘要
{period} 月度合规与服务品质总体评价。

# 规范
## 规范对照总览
本月对照规范条目、符合率及较上月变化。

# 巡检业务
## 各业务合规表现
分业务列出合规率、主要不合规项与根因分析。

# 区域
## 区域风险分布
高风险区域、重复问题区域及治理措施。

# 巡检结果
## 重大事件回顾
本月重大告警/事件、处置结果与经验总结。
## 整改闭环
整改项完成率、超时项与下月计划。""",
        "size_label": "1.8 KB",
    },
    {
        "template_id": "tpl-work-execution",
        "name": "单次业务执行报告模版",
        "description": "某条巡检业务执行完成后自动生成",
        "filename": "work-execution-template.md",
        "content": """# 报告摘要
本次巡检业务执行的时间、范围与总体结论。

# 规范
## 对照条款与结果
本次执行对照的规范条款及逐项结论。

# 巡检业务
## 业务配置快照
业务名称、关联算法/设备/规范说明。

# 区域
## 本次覆盖区域
实际巡检区域、点位与采样说明。

# 巡检结果
## 检测与告警明细
算法识别结果、传感器读数、截图/证据摘要。
## 结论与建议
是否通过、待整改项与建议措施。""",
        "size_label": "1.5 KB",
    },
    {
        "template_id": "tpl-adhoc-special",
        "name": "专项排查报告模版",
        "description": "活动前/节假日/上级检查等临时专项",
        "filename": "adhoc-special-template.md",
        "content": """# 报告摘要
专项排查背景、范围与总体结论。

# 规范
## 排查依据
本次专项所依据的规范、标准或检查表。

# 巡检业务
## 参与排查业务
纳入本次专项的巡检业务及分工。

# 区域
## 排查范围
重点部位、抽样规则与覆盖说明。

# 巡检结果
## 发现问题
问题描述、等级、证据与责任区域。
## 处置建议
立即整改项、限期整改项与复查安排。""",
        "size_label": "1.3 KB",
    },
    {
        "template_id": "tpl-hse-incident",
        "name": "安全事件通报模版",
        "description": "重大告警或安全事件专题通报",
        "filename": "hse-incident-template.md",
        "content": """# 报告摘要
事件概要：时间、地点、等级与当前状态。

# 规范
## 相关规范条款
与事件相关的规范要求及符合性初判。

# 巡检业务
## 关联业务与设备
触发事件的巡检业务、摄像头/传感器信息。

# 区域
## 事发区域
区域定位、影响范围与人员活动情况。

# 巡检结果
## 事件经过
时间线、检测记录、人工复核情况。
## 处置与后续
已采取措施、责任人、复查与预防建议。""",
        "size_label": "1.2 KB",
    },
]


def main() -> None:
    svc = ReportService()
    created = 0
    skipped = 0
    for item in EXTRA_TEMPLATES:
        tid = item["template_id"]
        if svc.get_template(tid):
            skipped += 1
            print(f"skip  {tid}  {item['name']}")
            continue
        svc.create_template(
            template_id=tid,
            name=item["name"],
            description=item.get("description", ""),
            filename=item.get("filename", ""),
            content=item["content"],
            size_label=item.get("size_label", ""),
        )
        created += 1
        print(f"add   {tid}  {item['name']}")
    items, total = svc.list_templates()
    print(f"\ndone: created={created} skipped={skipped} total={total}")


if __name__ == "__main__":
    main()
