"""Manual / paste-in adapter — surfaces a single in-memory item.

Used by the CLI `submit` command so users can drop in a curated piece of
content (a forwarded note, a Twitter thread saved to text, etc.) without
needing a network adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from .base import FetchedItem, SourceAdapter


class ManualSource(SourceAdapter):
    key = "manual"
    name = "Manual paste-in"

    def __init__(
        self,
        *,
        title: str,
        body: str,
        url: Optional[str] = None,
        author: Optional[str] = None,
        external_id: Optional[str] = None,
        published_at: Optional[datetime] = None,
    ) -> None:
        self._item = FetchedItem(
            external_id=external_id or f"{title}|{(published_at or datetime.utcnow()).isoformat()}",
            title=title,
            body=body,
            url=url,
            author=author or "manual",
            language="en",
            published_at=published_at or datetime.utcnow(),
        )

    def fetch(self) -> Iterable[FetchedItem]:
        return [self._item]
