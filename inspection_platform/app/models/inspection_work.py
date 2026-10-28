from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class InspectionWork(Base):
    __tablename__ = "inspection_work"

    work_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False)
    region_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    desc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rule_set_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    algorithm_set_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    equipment_set_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    equipment_algo_params_json: Mapped[str] = mapped_column(
        String(8192), nullable=False, server_default="{}"
    )
    work_status: Mapped[str] = mapped_column(String(32), nullable=False, default="online")
    schedule_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    schedule_interval: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule_times: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("idx_inspection_work_region", "region_id"),
        Index("idx_inspection_work_created", "created_at"),
    )
