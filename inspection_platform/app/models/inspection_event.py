from __future__ import annotations

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class InspectionEvent(Base):
    __tablename__ = "inspection_event"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    work_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    work_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    region_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    equipment_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    algorithm_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    rule_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold_text: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    snapshot_gradient: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occurred_at: Mapped[str] = mapped_column(String(32), nullable=False)
    reported_at: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    handler: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    handled_at: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    resolution_outcome: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    resolution_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detection_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("idx_ie_kind", "kind"),
        Index("idx_ie_status", "status"),
        Index("idx_ie_work", "work_id"),
        Index("idx_ie_region", "region_id"),
        Index("idx_ie_occurred", "occurred_at"),
    )
