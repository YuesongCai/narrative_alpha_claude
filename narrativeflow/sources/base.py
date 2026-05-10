"""SourceAdapter — the only contract every public-feed integration implements.

Adding a new source means writing a `fetch()` that yields `FetchedItem`s.
Everything downstream (dedup, noise filtering, tagging, synthesis) is shared.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional


@dataclass
class FetchedItem:
    """Normalized output of any source adapter, before persistence."""

    external_id: str               # stable per-source identifier (URL, GUID, story id)
    title: str
    body: str
    url: Optional[str] = None
    author: Optional[str] = None
    language: str = "en"
    published_at: datetime = field(default_factory=datetime.utcnow)


class SourceAdapter(abc.ABC):
    """Subclasses must set `key` and implement `fetch()`."""

    #: Stable short slug used in DB rows + logs. Must be unique across adapters.
    key: str

    #: Human-readable name (e.g., "Hacker News front page").
    name: str

    @abc.abstractmethod
    def fetch(self) -> Iterable[FetchedItem]:
        """Yield items from the source. Must be safe to call repeatedly —
        the upsert layer dedupes on (key, external_id).
        """
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} key={self.key!r}>"
