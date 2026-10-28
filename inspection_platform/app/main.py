"""
平台应用入口：中间件、API、静态资源、MySQL / Milvus 初始化。

运行（仓库根目录）::

    uvicorn inspection_platform.app.main:app --reload --host 0.0.0.0 --port 8001

配置见仓库根目录 ``.env``（Pydantic Settings）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import os
import sys

from dotenv import load_dotenv

from inspection_platform.app.config import repo_root

load_dotenv(repo_root() / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from inspection_platform.app.api.router import register_routers
from inspection_platform.app.config import get_settings
from inspection_platform.app.database import init_db
from inspection_platform.auth.middleware import AuthMiddleware


def _warmup_embedding_background() -> None:
    try:
        from inspection_platform.deps import warmup_embedding_model

        warmup_embedding_model()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import asyncio
    import os
    from concurrent.futures import ThreadPoolExecutor

    from inspection_platform.app.logging_config import setup_platform_logging
    from inspection_platform.env_bootstrap import bootstrap_platform_env, reset_model_stack

    # 扩大 sync 路由默认线程池，避免持续监控 + 批量 API 占满 worker 后连 health 都无法响应。
    workers = int(os.environ.get("SIA_ASYNC_THREAD_WORKERS", "48"))
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sia-api"))

    setup_platform_logging()
    from inspection_platform.env_bootstrap import (
        apply_project_dotenv,
        bootstrap_platform_env,
        sync_platform_siliconflow_credentials,
    )
    from inspection_platform.deps import _ensure_platform_embedding_env

    apply_project_dotenv(override=True)
    applied = bootstrap_platform_env()
    _ensure_platform_embedding_env()
    sync_platform_siliconflow_credentials()
    if applied:
        reset_model_stack()

    settings = get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.milvus_persist_path.mkdir(parents=True, exist_ok=True)

    init_db()
    from inspection_platform.app.database import warmup_db_pool

    warmup_db_pool()

    try:
        from inspection_platform.report.bootstrap import bootstrap_report_module

        bootstrap_report_module()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("report module bootstrap failed at startup")

    from inspection_platform.auth.service import AuthService

    AuthService().seed_builtin()

    from inspection_platform.document.region_db import init_region_db

    init_region_db()

    from inspection_platform.report.scheduler import report_scheduler

    report_scheduler.start()
    from inspection_platform.inspection_work.scheduler import continuous_work_scheduler

    continuous_work_scheduler.start()
    from inspection_platform.inspection_work.tracking_scheduler import work_tracking_schedule_ticker

    work_tracking_schedule_ticker.start()
    try:
        from inspection_platform.algorithm.vaio_hermes import register_vaio_mcp_in_hermes_config

        register_vaio_mcp_in_hermes_config()
    except Exception:
        pass
    try:
        from inspection_platform.platform_mcp.hermes_register import register_platform_mcp_in_hermes_config

        register_platform_mcp_in_hermes_config()
    except Exception:
        pass
    try:
        from inspection_platform.hermes_bootstrap import (
            ensure_hermes_model_config,
            ensure_hermes_skills_config,
            ensure_SIA_assistant_identity,
        )

        ensure_SIA_assistant_identity()
        ensure_hermes_model_config()
        ensure_hermes_skills_config()
    except Exception:
        pass
    import threading

    threading.Thread(target=_warmup_embedding_background, daemon=True).start()
    yield
    continuous_work_scheduler.stop()
    work_tracking_schedule_ticker.stop()
    report_scheduler.stop()


app = FastAPI(title="inspection_platform", version="0.2.0", lifespan=lifespan, redirect_slashes=True)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_routers(app)


def _mount_hermes_dashboard(target: FastAPI) -> None:
    """将 Hermes Dashboard 作为子应用挂载到 /hermes-agent。"""
    platform_root = Path(__file__).resolve().parents[1]
    vendored_root = platform_root / "hermes_agent"
    configured = os.environ.get("SIA_HERMES_AGENT_ROOT", "").strip()
    candidates = []
    if vendored_root.is_dir():
        candidates.append(vendored_root)
    if configured:
        candidates.append(Path(configured))
    hermes_root = next((p for p in candidates if p.is_dir()), None)
    if not hermes_root:
        return

    if str(hermes_root) not in sys.path:
        sys.path.insert(0, str(hermes_root))

    try:
        import hermes_cli.web_server as hermes_web_server  # type: ignore
    except Exception:
        return

    hermes_web_server._DASHBOARD_EMBEDDED_CHAT_ENABLED = True
    target.mount("/hermes-agent", hermes_web_server.app, name="hermes-dashboard")


try:
    from inspection_platform.hermes_bootstrap import ensure_SIA_assistant_identity

    ensure_SIA_assistant_identity()
except Exception:
    pass

_mount_hermes_dashboard(app)

_settings = get_settings()
_data_dir = _settings.data_path
if _data_dir.is_dir():
    app.mount("/data", StaticFiles(directory=str(_data_dir)), name="data-files")

_static_dir = Path(__file__).resolve().parents[1] / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
