"""SQLAlchemy declarative base + tiny shared helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All ORM models inherit from this base."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
