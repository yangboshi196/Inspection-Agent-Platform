from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SpecRule(Base):
    __tablename__ = "spec_rule"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    desc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    level: Mapped[str] = mapped_column(String(32), nullable=False, default="common")
    requirements: Mapped[str] = mapped_column(Text, nullable=False, default="")
    doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    recommended_algorithms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recommended_regions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    algorithm_reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommended_regions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    region_reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_trace_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("idx_spec_rule_status", "status"),
        Index("idx_spec_rule_doc", "doc_id"),
    )
