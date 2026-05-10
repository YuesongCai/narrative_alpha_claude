"""Narrative tracker — the atomic unit of NarrativeFlow.

Schema mirrors §4.2 of the PRD. JSON columns hold structured data
(causal_chain, ticker_map, catalysts, evidence) so the schema can evolve
without migrations during V1; once the model stabilizes we can normalize.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


def _new_id() -> str:
    return uuid.uuid4().hex


class SourceType(str, Enum):
    """Origin channel for a narrative — §4.4 of the PRD."""

    USER_CREATED = "user_created"
    EDITOR_PICK = "editor_pick"
    MARKET_DERIVED = "market_derived"
    COMMUNITY_SURFACED = "community_surfaced"


class LifecycleStage(str, Enum):
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    CONSENSUS = "consensus"
    CROWDED = "crowded"
    FADING = "fading"

    @classmethod
    def order_index(cls, stage: str) -> int:
        order = [cls.EMERGING, cls.ACCELERATING, cls.CONSENSUS, cls.CROWDED, cls.FADING]
        try:
            return order.index(cls(stage))
        except ValueError:
            return 99


class StateChangeType(str, Enum):
    HEAT_SHIFT = "heat_shift"
    NEW_CATALYST = "new_catalyst"
    TICKER_ROTATION = "ticker_rotation"
    CONVERGENCE = "narrative_convergence"
    EXIT_SIGNAL = "exit_signal"


class Narrative(Base):
    __tablename__ = "narratives"
    __table_args__ = (
        Index("ix_narratives_lifecycle", "lifecycle_stage"),
        Index("ix_narratives_heat", "heat_score"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default=SourceType.MARKET_DERIVED.value)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    one_liner: Mapped[str] = mapped_column(Text, default="", nullable=False)

    causal_chain: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    lifecycle_stage: Mapped[str] = mapped_column(String(32), default=LifecycleStage.EMERGING.value, nullable=False)
    heat_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    ticker_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    catalysts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    key_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    counter_narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)

    centroid_terms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    related_narrative_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    last_synthesized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    contents: Mapped[list["NarrativeContent"]] = relationship(
        back_populates="narrative",
        cascade="all, delete-orphan",
    )
    state_changes: Mapped[list["StateChange"]] = relationship(
        back_populates="narrative",
        cascade="all, delete-orphan",
        order_by="StateChange.occurred_at.desc()",
    )


class NarrativeContent(Base):
    """M2M between narratives and raw content with a tagging confidence."""

    __tablename__ = "narrative_content"
    __table_args__ = (UniqueConstraint("narrative_id", "content_id", name="uq_narrative_content"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    narrative_id: Mapped[str] = mapped_column(String(32), ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("raw_content.id", ondelete="CASCADE"), nullable=False)
    relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tagged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    tagged_by: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)  # auto | llm | user

    narrative: Mapped[Narrative] = relationship(back_populates="contents")


class StateChange(Base):
    """Audit log of meaningful narrative state changes — drives notifications."""

    __tablename__ = "state_changes"
    __table_args__ = (Index("ix_state_changes_occurred", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    narrative_id: Mapped[str] = mapped_column(String(32), ForeignKey("narratives.id", ondelete="CASCADE"), nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    narrative: Mapped[Narrative] = relationship(back_populates="state_changes")
