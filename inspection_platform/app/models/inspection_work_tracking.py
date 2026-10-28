from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class InspectionWorkTracking(Base):
    """巡检业务在「业务追踪」队列中的发布与执行状态。"""

    __tablename__ = "inspection_work_tracking"

    work_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    published: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    published_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ended_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    estimated_start_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    estimated_end_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("idx_iwt_published_status", "published", "queue_status"),
    )
