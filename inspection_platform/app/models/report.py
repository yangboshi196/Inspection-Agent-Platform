from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ReportTemplate(Base):
    __tablename__ = "report_template"

    template_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    outline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    uploaded_at: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    size_label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class ReportPlan(Base):
    __tablename__ = "report_plan"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    work_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generate_time: Mapped[str] = mapped_column(String(16), nullable=False, default="08:00")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (Index("idx_report_plan_frequency", "frequency"),)


class InspectionReport(Base):
    __tablename__ = "inspection_report"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    period: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="weekly")
    work_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    content_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sections_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (Index("idx_inspection_report_status", "status"),)


class WorkReportTemplateBinding(Base):
    """巡检业务 ↔ 执行报告模版绑定（业务自动执行后 Agent 据此生成报告）。"""

    __tablename__ = "work_report_template_binding"

    work_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    template_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    storage_relpath: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class UserReportPushSubscription(Base):
    """用户看板报告推送：用户订阅的巡检业务 work_id 列表。"""

    __tablename__ = "user_report_push_subscription"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
