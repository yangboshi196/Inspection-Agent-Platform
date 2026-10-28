"""FastAPI 路由注册：聚合各业务 APIRouter。"""

from __future__ import annotations

from fastapi import FastAPI

from inspection_platform.routes.algorithm import router as algorithm_router
from inspection_platform.routes.api import router as api_router
from inspection_platform.routes.auth import router as auth_router
from inspection_platform.routes.document import router as document_router
from inspection_platform.routes.embedding import router as embedding_router
from inspection_platform.routes.equipment import router as equipment_router
from inspection_platform.routes.inspection_event import router as inspection_event_router
from inspection_platform.routes.inspection_work import router as inspection_work_router
from inspection_platform.routes.knowledge import router as knowledge_router
from inspection_platform.routes.logs import router as logs_router
from inspection_platform.routes.media import router as media_router
from inspection_platform.routes.platform import router as platform_router
from inspection_platform.routes.region import router as region_router
from inspection_platform.routes.report import router as report_router
from inspection_platform.routes.report_push import router as report_push_router
from inspection_platform.routes.work_report_template import router as work_report_template_router
from inspection_platform.routes.specification import router as specification_router


def register_routers(app: FastAPI) -> None:
    app.include_router(api_router)
    app.include_router(document_router)
    app.include_router(embedding_router)
    app.include_router(region_router)
    app.include_router(knowledge_router)
    app.include_router(specification_router)
    app.include_router(algorithm_router)
    app.include_router(equipment_router)
    app.include_router(media_router)
    app.include_router(platform_router)
    app.include_router(inspection_work_router)
    app.include_router(inspection_event_router)
    app.include_router(report_router)
    app.include_router(report_push_router)
    app.include_router(work_report_template_router)
    app.include_router(logs_router)
    app.include_router(auth_router)
