from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    platform_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    platform_address: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    thumbnail: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    data_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    online: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    simulate_video_relpath: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("idx_equipment_kind", "kind"),
        Index("idx_equipment_region", "region_id"),
    )


class SensorReading(Base):
    __tablename__ = "sensor_reading"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (Index("idx_sensor_reading_equipment", "equipment_id", "recorded_at"),)
