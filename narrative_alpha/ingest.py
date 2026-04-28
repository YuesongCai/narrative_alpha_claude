"""Source ingestion.

Three entry points cover everything in the PRD's Section 6:

* `ingest_rss(url)`   — pull a feed, normalize each entry into a `Source`.
* `submit_manual(...)`— user-contributed source (PDF text, pasted URL, etc.).
* `load_seed_file()`  — bootstrap from the bundled JSON seed corpus.

All three converge on `Store.add_source` and apply the same tier classification.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import Source, Tier
from .store import Store
from .tiers import classify_tier, org_from_url

try:  # optional — only needed for live RSS ingestion
    import feedparser  # type: ignore
except ImportError:  # pragma: no cover
    feedparser = None  # type: ignore


def _stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).replace("\xa0", " ").strip()


# --------------------------------------------------------------------- RSS
def ingest_rss(store: Store, feed_url: str, default_org: str | None = None) -> list[Source]:
    """Fetch an RSS feed and add each entry as a Source. Idempotent on `source_id`."""
    if feedparser is None:
        raise RuntimeError("feedparser is not installed; run `pip install feedparser`")

    parsed = feedparser.parse(feed_url)
    feed_org = default_org or parsed.feed.get("title") or org_from_url(feed_url) or feed_url
    added: list[Source] = []
    for entry in parsed.entries:
        url = entry.get("link") or ""
        title = entry.get("title") or "(untitled)"
        body = _strip_html(entry.get("summary") or entry.get("description") or "")
        org = org_from_url(url) or feed_org
        published_at = _entry_dt(entry)
        source = Source(
            source_id=_stable_id("src", url or title, org),
            title=title.strip(),
            org=org,
            tier=classify_tier(org),
            published_at=published_at,
            body=body,
            url=url or None,
        )
        if store.add_source(source):
            added.append(source)
    return added


def _entry_dt(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                continue
    return datetime.utcnow()


# ----------------------------------------------------------- Manual submit
def submit_manual(
    store: Store,
    *,
    title: str,
    body: str,
    org: str,
    url: str | None = None,
    submitted_by: str | None = None,
    tier: int | None = None,
    published_at: datetime | None = None,
) -> Source:
    """User-contributed source. Honors an explicit tier if provided (e.g. user
    knows this is a sell-side note that wouldn't be auto-classified).
    """
    resolved_tier = tier if tier is not None else classify_tier(org)
    source = Source(
        source_id=_stable_id("usr", url or title, org, submitted_by or ""),
        title=title.strip(),
        org=org,
        tier=int(resolved_tier),
        published_at=published_at or datetime.utcnow(),
        body=body.strip(),
        url=url,
        submitted_by=submitted_by,
    )
    store.add_source(source)
    return source


# ------------------------------------------------------------------- Seed
def load_seed_file(store: Store, path: str | Path) -> list[Source]:
    """Load the bundled seed corpus or any other JSON list of source dicts."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return _ingest_dicts(store, data)


def _ingest_dicts(store: Store, items: Iterable[dict]) -> list[Source]:
    added: list[Source] = []
    for d in items:
        org = d["org"]
        url = d.get("url")
        published_at = d.get("published_at")
        if isinstance(published_at, str):
            published_at = datetime.fromisoformat(published_at)
        source = Source(
            source_id=d.get("source_id") or _stable_id("seed", d["title"], org),
            title=d["title"],
            org=org,
            tier=int(d.get("tier") or classify_tier(org)),
            published_at=published_at or datetime.utcnow(),
            body=d["body"],
            url=url,
            submitted_by=d.get("submitted_by"),
            cites=list(d.get("cites") or []),
        )
        if store.add_source(source):
            added.append(source)
    return added
