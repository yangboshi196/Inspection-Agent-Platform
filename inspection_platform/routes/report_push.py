"""报告推送订阅 HTTP API（管理端配置 / 用户看板读取）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from inspection_platform.auth.service import AuthService
from inspection_platform.report.push_subscription import ReportPushSubscriptionService

router = APIRouter(prefix="/api/report-push", tags=["report-push"])


class ReportPushSubscriptionRow(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    work_ids: list[str] = Field(default_factory=list)


class ReportPushSubscriptionsSaveBody(BaseModel):
    items: list[ReportPushSubscriptionRow] = Field(default_factory=list)


@router.get("/subscriptions", summary="列出全部用户的报告推送订阅（管理端）")
def list_report_push_subscriptions() -> dict[str, Any]:
    auth = AuthService()
    users = auth.list_users()
    subs = ReportPushSubscriptionService().list_subscriptions()
    items = []
    for u in users:
        uid = str(u.get("user_id") or "")
        items.append(
            {
                "user_id": uid,
                "account": str(u.get("account") or ""),
                "name": str(u.get("name") or ""),
                "status": str(u.get("status") or "active"),
                "work_ids": subs.get(uid, []),
            }
        )
    return {"items": items, "total": len(items)}


@router.put("/subscriptions", summary="批量保存报告推送订阅（管理端）")
def save_report_push_subscriptions(body: ReportPushSubscriptionsSaveBody) -> dict[str, Any]:
    svc = ReportPushSubscriptionService()
    try:
        saved = svc.save_subscriptions([row.model_dump() for row in body.items])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"items": saved, "count": len(saved)}


@router.get("/me", summary="当前登录用户的报告推送订阅")
def my_report_push_subscription(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    uid = str(user.get("user_id") or "")
    work_ids = ReportPushSubscriptionService().get_work_ids_for_user(uid)
    return {
        "user_id": uid,
        "work_ids": work_ids,
        "has_subscription": bool(work_ids),
    }
