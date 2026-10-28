"""主智能体可调用的「生成巡检业务」工具。"""

from __future__ import annotations

from typing import Any

from agent_base.tools.base import Tool, ToolSpec
from agent_base.tools.types import ToolError, ToolResult

from inspection_platform.deps import get_model_manager, get_specification_service
from inspection_platform.inspection_work.matcher import generate_inspection_works


class BuildInspectionWorksTool(Tool):
    """根据区域设备与已发布规范、算法目录匹配生成巡检业务草案（须人工确认后手动入库）。"""

    def __init__(self) -> None:
        super().__init__(
            ToolSpec(
                name="build_inspection_works",
                description=(
                    "根据参考区域设备、已发布规范与平台算法目录做语义编组，生成巡检业务草案："
                    "每条含名称、说明、规则集 rule_set（rule_id）、算法集 algorithm_set（algorithm_id）、设备集 equipment_set。"
                    "结果仅返回草案，须人工确认后通过 POST /api/inspection-work/ 手动入库。"
                ),
                category="algorithm",
                input_schema={
                    "region_id": "string (required)",
                    "max_works": "int (optional, default 10)",
                    "topic": "string (optional, 用户巡检诉求)",
                    "model_name": "string (optional)",
                    "algorithm_limit": "int (optional, default 120, max 400)",
                },
                timeout_ms=120000,
                side_effect=False,
                idempotent=True,
                display_name="巡检业务编排",
                ui_agent_label="巡检业务",
                ui_agent_hint="规则与算法匹配后生成 work（含设备建议）",
            )
        )

    def invoke(self, arguments: dict[str, Any], *, request_id: str | None = None) -> ToolResult:
        region_id = arguments.get("region_id")
        if not isinstance(region_id, str) or not region_id.strip():
            return ToolResult(
                ok=False,
                tool_name=self.spec.name,
                request_id=request_id,
                error=ToolError(
                    code="INVALID_ARGUMENT",
                    message="缺少 region_id（非空字符串）",
                    request_id=request_id,
                    tool_name=self.spec.name,
                    retryable=False,
                ),
            )
        if bool(arguments.get("persist", False)):
            return ToolResult(
                ok=False,
                tool_name=self.spec.name,
                request_id=request_id,
                error=ToolError(
                    code="INVALID_ARGUMENT",
                    message="persist 已停用；请使用返回草案后人工确认，再通过 POST /api/inspection-work/ 手动入库",
                    request_id=request_id,
                    tool_name=self.spec.name,
                    retryable=False,
                ),
            )
        max_works = arguments.get("max_works", 10)
        try:
            mw = int(max_works) if max_works is not None else 10
        except (TypeError, ValueError):
            mw = 10
        model_name = arguments.get("model_name")
        if model_name is not None and not isinstance(model_name, str):
            model_name = None
        topic = arguments.get("topic")
        if topic is not None and not isinstance(topic, str):
            topic = None
        alim = arguments.get("algorithm_limit", 120)
        try:
            algorithm_limit = int(alim) if alim is not None else 120
        except (TypeError, ValueError):
            algorithm_limit = 120

        mm = get_model_manager()
        spec_svc = get_specification_service()
        try:
            result = generate_inspection_works(
                spec_svc=spec_svc,
                mm=mm,
                region_id=region_id.strip(),
                model_name=model_name,
                max_works=mw,
                topic=topic,
                algorithm_limit=algorithm_limit,
            )
            drafts = result.get("works") or []
        except ValueError as e:
            return ToolResult(
                ok=False,
                tool_name=self.spec.name,
                request_id=request_id,
                error=ToolError(
                    code="INVALID_ARGUMENT",
                    message=str(e),
                    request_id=request_id,
                    tool_name=self.spec.name,
                    retryable=False,
                ),
            )
        except RuntimeError as e:
            return ToolResult(
                ok=False,
                tool_name=self.spec.name,
                request_id=request_id,
                error=ToolError(
                    code="UPSTREAM_ERROR",
                    message=str(e),
                    request_id=request_id,
                    tool_name=self.spec.name,
                    retryable=True,
                ),
            )

        return ToolResult(
            ok=True,
            tool_name=self.spec.name,
            request_id=request_id,
            data={
                "region_id": region_id.strip(),
                "count": len(drafts),
                "works": drafts,
            },
        )
