"""Repositories — thin facades over the ORM.

Why the indirection: the rest of the codebase only depends on the repository
interface, not on SQLAlchemy queries scattered across modules. When we swap
SQLite for Postgres, or add caching / read replicas, the change lives here.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import (
    Narrative,
    NarrativeContent,
    RawContent,
    StateChange,
    User,
    UserFollow,
)


# ---------------------------------------------------------- raw content
class ContentRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, item: RawContent) -> tuple[RawContent, bool]:
        """Insert if (source_key, external_id) is new; otherwise return existing."""
        existing = self.session.execute(
            select(RawContent).where(
                RawContent.source_key == item.source_key,
                RawContent.external_id == item.external_id,
            )
        ).scalar_one_or_none()
        if existing:
            return existing, False
        self.session.add(item)
        self.session.flush()
        return item, True

    def get(self, content_id: int) -> Optional[RawContent]:
        return self.session.get(RawContent, content_id)

    def find_by_hash(self, content_hash: str) -> list[RawContent]:
        return list(
            self.session.execute(
                select(RawContent).where(RawContent.content_hash == content_hash)
            ).scalars()
        )

    def unprocessed(self, *, limit: int = 500) -> list[RawContent]:
        """Items needing pipeline processing (not flagged noise yet)."""
        return list(
            self.session.execute(
                select(RawContent)
                .where(RawContent.is_noise == False)  # noqa: E712 - SA needs ==
                .order_by(desc(RawContent.published_at))
                .limit(limit)
            ).scalars()
        )

    def recent(self, *, since: datetime, limit: int = 1000) -> list[RawContent]:
        return list(
            self.session.execute(
                select(RawContent)
                .where(RawContent.published_at >= since, RawContent.is_noise == False)  # noqa: E712
                .order_by(desc(RawContent.published_at))
                .limit(limit)
            ).scalars()
        )

    def count(self) -> int:
        return self.session.query(RawContent).count()


# ------------------------------------------------------------ narratives
class NarrativeRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active(self, *, limit: int = 100) -> list[Narrative]:
        return list(
            self.session.execute(
                select(Narrative).order_by(desc(Narrative.heat_score)).limit(limit)
            ).scalars()
        )

    def list_by_lifecycle(self, stage: str, *, limit: int = 100) -> list[Narrative]:
        return list(
            self.session.execute(
                select(Narrative)
                .where(Narrative.lifecycle_stage == stage)
                .order_by(desc(Narrative.heat_score))
                .limit(limit)
            ).scalars()
        )

    def get(self, narrative_id: str) -> Optional[Narrative]:
        return self.session.get(Narrative, narrative_id)

    def get_by_slug(self, slug: str) -> Optional[Narrative]:
        return self.session.execute(select(Narrative).where(Narrative.slug == slug)).scalar_one_or_none()

    def search(self, query: str, *, limit: int = 10) -> list[Narrative]:
        """Lexical search over title + one_liner. SQLite-friendly LIKE; swap
        for Postgres `tsvector` or pgvector embeddings in V3."""
        like = f"%{query.strip()}%"
        return list(
            self.session.execute(
                select(Narrative)
                .where((Narrative.title.ilike(like)) | (Narrative.one_liner.ilike(like)))
                .order_by(desc(Narrative.heat_score))
                .limit(limit)
            ).scalars()
        )

    def upsert(self, narrative: Narrative) -> Narrative:
        if narrative.id and self.get(narrative.id):
            self.session.merge(narrative)
        else:
            self.session.add(narrative)
        self.session.flush()
        return narrative

    @staticmethod
    def slugify(title: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return s[:120] or "narrative"

    def attach_content(self, narrative: Narrative, content: RawContent, *, relevance: float, tagged_by: str = "auto") -> None:
        existing = self.session.execute(
            select(NarrativeContent).where(
                NarrativeContent.narrative_id == narrative.id,
                NarrativeContent.content_id == content.id,
            )
        ).scalar_one_or_none()
        if existing:
            existing.relevance = max(existing.relevance, relevance)
            return
        link = NarrativeContent(
            narrative_id=narrative.id,
            content_id=content.id,
            relevance=relevance,
            tagged_by=tagged_by,
        )
        self.session.add(link)

    def contents_for(self, narrative_id: str, *, limit: int = 50) -> list[RawContent]:
        rows = self.session.execute(
            select(RawContent)
            .join(NarrativeContent, NarrativeContent.content_id == RawContent.id)
            .where(NarrativeContent.narrative_id == narrative_id)
            .order_by(desc(RawContent.published_at))
            .limit(limit)
        ).scalars()
        return list(rows)


# --------------------------------------------------------- state changes
class StateChangeRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, change: StateChange) -> StateChange:
        self.session.add(change)
        self.session.flush()
        return change

    def pending_notifications(self) -> list[StateChange]:
        return list(
            self.session.execute(
                select(StateChange).where(StateChange.notified_at.is_(None))
            ).scalars()
        )

    def recent_for(self, narrative_id: str, *, limit: int = 20) -> list[StateChange]:
        return list(
            self.session.execute(
                select(StateChange)
                .where(StateChange.narrative_id == narrative_id)
                .order_by(desc(StateChange.occurred_at))
                .limit(limit)
            ).scalars()
        )


# ------------------------------------------------------------------ users
class UserRepo:
    DEFAULT_USERNAME = "local"

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_local(self) -> User:
        existing = self.session.execute(
            select(User).where(User.username == self.DEFAULT_USERNAME)
        ).scalar_one_or_none()
        if existing:
            return existing
        u = User(username=self.DEFAULT_USERNAME, display_name="Local")
        self.session.add(u)
        self.session.flush()
        return u

    def follow(self, user: User, narrative: Narrative) -> UserFollow:
        existing = self.session.execute(
            select(UserFollow).where(
                UserFollow.user_id == user.id,
                UserFollow.narrative_id == narrative.id,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        f = UserFollow(user_id=user.id, narrative_id=narrative.id)
        self.session.add(f)
        self.session.flush()
        return f

    def unfollow(self, user: User, narrative: Narrative) -> bool:
        existing = self.session.execute(
            select(UserFollow).where(
                UserFollow.user_id == user.id,
                UserFollow.narrative_id == narrative.id,
            )
        ).scalar_one_or_none()
        if not existing:
            return False
        self.session.delete(existing)
        return True

    def followed_narratives(self, user: User) -> list[Narrative]:
        rows = self.session.execute(
            select(Narrative)
            .join(UserFollow, UserFollow.narrative_id == Narrative.id)
            .where(UserFollow.user_id == user.id)
            .order_by(desc(Narrative.heat_score))
        ).scalars()
        return list(rows)
