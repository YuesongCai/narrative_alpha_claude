"""Hacker News front-page adapter via the public Firebase API.

Fully public, no auth required. We pull the top ~30 stories on each fetch.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from .base import FetchedItem, SourceAdapter

logger = logging.getLogger(__name__)

TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
HN_PERMALINK = "https://news.ycombinator.com/item?id={id}"


class HackerNewsSource(SourceAdapter):
    key = "hackernews"
    name = "Hacker News (front page)"

    def __init__(self, *, top_n: int = 30, timeout: float = 15.0) -> None:
        self.top_n = top_n
        self.timeout = timeout

    def fetch(self) -> Iterable[FetchedItem]:
        items: list[FetchedItem] = []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                ids = client.get(TOP_STORIES_URL).json()[: self.top_n]
                for sid in ids:
                    try:
                        data = client.get(ITEM_URL.format(id=sid)).json() or {}
                    except Exception as e:  # pragma: no cover - network
                        logger.debug("HN item %s fetch failed: %s", sid, e)
                        continue
                    if data.get("type") != "story" or not data.get("title"):
                        continue
                    body = data.get("text") or ""
                    items.append(
                        FetchedItem(
                            external_id=str(sid),
                            title=str(data["title"])[:1024],
                            body=body,
                            url=data.get("url") or HN_PERMALINK.format(id=sid),
                            author=data.get("by"),
                            language="en",
                            published_at=datetime.utcfromtimestamp(int(data.get("time", 0))) if data.get("time") else datetime.utcnow(),
                        )
                    )
        except Exception as e:  # pragma: no cover - network
            logger.warning("HN fetch failed: %s", e)
        return items
