"""Stage 1 — Ingestion + dedupe.

Pulls items from configured source adapters, normalizes them into RawContent
rows, and deduplicates on (source_key, external_id). A secondary cross-source
hash dedupes obvious re-publications of the same story.
"""

from __future__ import annotations

import logging
from typing import Iterable

from ..models import RawContent, utcnow
from ..sources import SourceAdapter
from ..store import ContentRepo, get_session

logger = logging.getLogger(__name__)


def ingest_from(adapters: Iterable[SourceAdapter]) -> dict[str, int]:
    """Run each adapter once. Returns {source_key: items_inserted}.

    Multiple adapters may share a `source_key` (e.g. seed loaders); counts
    accumulate per key so the total reflects every successful insert.
    """
    counts: dict[str, int] = {}
    for adapter in adapters:
        try:
            items = list(adapter.fetch())
        except Exception as e:  # pragma: no cover
            logger.exception("source %s failed: %s", adapter.key, e)
            counts.setdefault(adapter.key, 0)
            continue
        new_count = 0
        with get_session() as session:
            repo = ContentRepo(session)
            for item in items:
                row = RawContent(
                    source_key=adapter.key,
                    external_id=item.external_id,
                    title=item.title,
                    url=item.url,
                    body=item.body or "",
                    author=item.author,
                    language=item.language,
                    published_at=item.published_at,
                    fetched_at=utcnow(),
                    content_hash=RawContent.hash_payload(item.title, item.body or ""),
                )
                _, inserted = repo.upsert(row)
                if inserted:
                    new_count += 1
        counts[adapter.key] = counts.get(adapter.key, 0) + new_count
        logger.info("ingest %s: +%d new of %d fetched", adapter.key, new_count, len(items))
    return counts
