"""Raw content fetched from a source adapter, before any AI processing."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class RawContent(Base):
    """A single item ingested from a public source (RSS post, HN story, etc.).

    The source layer normalizes everything into this shape. Pipeline stages
    enrich the row in place (`is_noise`, `noise_score`) but never mutate the
    source-provided fields.
    """

    __tablename__ = "raw_content"
    __table_args__ = (
        UniqueConstraint("source_key", "external_id", name="uq_raw_content_source_external"),
        Index("ix_raw_content_published", "published_at"),
        Index("ix_raw_content_source_published", "source_key", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    noise_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    noise_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    @staticmethod
    def hash_payload(title: str, body: str) -> str:
        """Stable hash used for cross-source dedupe (same story re-syndicated)."""
        canonical = (title.strip().lower() + "||" + body.strip().lower()[:500])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
