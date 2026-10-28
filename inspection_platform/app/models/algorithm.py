from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Algorithm(Base):
    __tablename__ = "algorithm"

    algorithm_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    desc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    health: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("idx_algorithm_health", "health"),
        Index("idx_algorithm_name", "name"),
    )
