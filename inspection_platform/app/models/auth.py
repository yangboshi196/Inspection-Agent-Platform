from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class AuthRole(Base):
    __tablename__ = "auth_role"

    role_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    users: Mapped[list["AuthUser"]] = relationship(back_populates="role")

    __table_args__ = (Index("idx_auth_role_name", "name"),)


class AuthUser(Base):
    __tablename__ = "auth_user"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    password: Mapped[str] = mapped_column(String(256), nullable=False)
    role_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("auth_role.role_id"), nullable=True)
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    role: Mapped[AuthRole | None] = relationship(back_populates="users")
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user")

    __table_args__ = (
        Index("idx_auth_user_account", "account"),
        Index("idx_auth_user_role", "role_id"),
    )


class AuthSession(Base):
    __tablename__ = "auth_session"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("auth_user.user_id"), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)

    user: Mapped[AuthUser] = relationship(back_populates="sessions")

    __table_args__ = (Index("idx_auth_session_user", "user_id"),)
