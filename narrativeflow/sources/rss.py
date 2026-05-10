"""Generic RSS / Atom adapter — works for the bulk of public news/blog feeds.

Configure once in the registry by passing a (key, name, url) and it picks up.
We don't try to do site-specific scraping here; the body comes from whatever
the feed publishes (often an excerpt, occasionally the full article).
"""

from __future__ import annotations

import logging
from typing import Iterable

import httpx

from . import _feed_parser
from .base import FetchedItem, SourceAdapter

logger = logging.getLogger(__name__)


class RSSSource(SourceAdapter):
    def __init__(self, *, key: str, name: str, url: str, language: str = "en", timeout: float = 20.0) -> None:
        self.key = key
        self.name = name
        self.url = url
        self.language = language
        self.timeout = timeout

    def fetch(self) -> Iterable[FetchedItem]:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True,
                              headers={"User-Agent": "NarrativeFlow/0.1"}) as client:
                resp = client.get(self.url)
                resp.raise_for_status()
                entries = _feed_parser.parse(resp.content)
        except Exception as e:  # pragma: no cover - network
            logger.warning("RSS fetch failed for %s: %s", self.key, e)
            return []

        items: list[FetchedItem] = []
        for entry in entries:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            link = entry.get("link") or None
            external_id = entry.get("id") or link or title
            items.append(
                FetchedItem(
                    external_id=str(external_id)[:256],
                    title=title[:1024],
                    body=entry.get("summary") or "",
                    url=link,
                    author=entry.get("author"),
                    language=self.language,
                    published_at=entry.get("published"),
                )
            )
        return items
