"""Users and follow graph.

V1 has no auth — `User` exists so the schema and API contracts are stable
once we add auth in V2. The web UI uses a single seeded user identified by
the `local` username.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    follows: Mapped[list["UserFollow"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserFollow(Base):
    __tablename__ = "user_follows"
    __table_args__ = (UniqueConstraint("user_id", "narrative_id", name="uq_user_follow"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    narrative_id: Mapped[str] = mapped_column(String(32), ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False)
    notify_heat: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_catalysts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_exit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="follows")
