#!/usr/bin/env python3
"""一键导入物业主题演示数据（区域、设备、算法、巡检业务、事件、报告）。

用法（仓库根目录）::

    python scripts/seed_property_demo.py

可选：仅打印将执行的操作::

    python scripts/seed_property_demo.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="导入物业主题内置演示数据")
    parser.add_argument("--dry-run", action="store_true", help="仅列出将导入的模块")
    args = parser.parse_args()

    steps = [
        ("区域", "RegionMetaService", "seed_builtin", {"replace_all": True}),
        ("设备", "EquipmentService", "seed_builtin", {"replace_all": True}),
        ("算法", "AlgorithmService", "seed_builtin", {"replace_all": True}),
        ("巡检业务", "InspectionWorkService", "seed_builtin", {"replace_all": True}),
        ("巡检事件", "InspectionEventService", "seed_builtin", {}),
        ("报告", "ReportService", "seed_builtin", {}),
    ]

    if args.dry_run:
        for label, *_ in steps:
            print(f"[dry-run] 将导入: {label}")
        return 0

    from inspection_platform.document.region_meta import RegionMetaService
    from inspection_platform.equipment.service import EquipmentService
    from inspection_platform.algorithm.service import AlgorithmService
    from inspection_platform.inspection_work.service import InspectionWorkService
    from inspection_platform.inspection_event.service import InspectionEventService
    from inspection_platform.inspection_event import db as event_db
    from inspection_platform.report.service import ReportService
    from inspection_platform.report import db as report_db

    event_db.init_db()
    rconn = event_db.get_connection()
    try:
        rconn.execute("DELETE FROM inspection_event")
        rconn.commit()
    finally:
        rconn.close()

    report_db.init_db()
    rpconn = report_db.get_connection()
    try:
        rpconn.execute("DELETE FROM inspection_report")
        rpconn.execute("DELETE FROM report_plan")
        rpconn.execute("DELETE FROM report_template")
        rpconn.commit()
    finally:
        rpconn.close()

    services = {
        "RegionMetaService": RegionMetaService(),
        "EquipmentService": EquipmentService(),
        "AlgorithmService": AlgorithmService(),
        "InspectionWorkService": InspectionWorkService(),
        "InspectionEventService": InspectionEventService(),
        "ReportService": ReportService(),
    }

    for label, svc_name, method, kwargs in steps:
        svc = services[svc_name]
        svc.ensure_ready()
        fn = getattr(svc, method)
        result = fn(**kwargs)
        if isinstance(result, dict):
            print(f"[OK] {label}: {result}")
        else:
            print(f"[OK] {label}: inserted {result}")

    print("\n完成。请刷新浏览器（Ctrl+F5）后访问管理端「区域配置」等页面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
