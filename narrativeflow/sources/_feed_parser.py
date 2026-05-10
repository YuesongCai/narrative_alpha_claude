"""Tiny RSS / Atom parser using stdlib only.

Replaces the `feedparser` dependency. We only need a handful of fields per
entry (id, title, link, summary, published_at) so a 60-line parser is plenty.
Robust against the common shapes; on weirdness it skips the entry rather than
crashing the ingest run.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


_RSS_DATE_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S %z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.utcnow()
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        pass
    for fmt in _RSS_DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            continue
    return datetime.utcnow()


def _local(tag: str) -> str:
    """Strip XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).replace("\xa0", " ").strip()


def parse(content: bytes | str) -> list[dict]:
    """Parse RSS or Atom XML and return a list of normalized entry dicts.

    Entry dict keys: id, title, link, summary, author, published.
    """
    if isinstance(content, str):
        content_bytes = content.encode("utf-8", errors="replace")
    else:
        content_bytes = content

    try:
        root = ET.fromstring(content_bytes)
    except ET.ParseError as e:
        logger.warning("XML parse failed: %s", e)
        return []

    root_tag = _local(root.tag)
    if root_tag == "rss":
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        return [_entry_from_rss(it) for it in items]
    if root_tag == "feed":
        # Atom
        entries = [child for child in root if _local(child.tag) == "entry"]
        return [_entry_from_atom(e) for e in entries]
    # Fallback: try to find any 'item' or 'entry' anywhere.
    items = root.findall(".//item") + root.findall(".//{*}entry")
    return [_entry_from_rss(it) if _local(it.tag) == "item" else _entry_from_atom(it) for it in items]


def _text_of(parent, name: str) -> str | None:
    for child in parent:
        if _local(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def _entry_from_rss(item) -> dict:
    title = _text_of(item, "title") or ""
    link = _text_of(item, "link") or ""
    guid = _text_of(item, "guid") or link or title
    desc = _text_of(item, "description") or ""
    pub = _text_of(item, "pubDate") or _text_of(item, "date")
    author = _text_of(item, "author") or _text_of(item, "creator")
    return {
        "id": guid,
        "title": title,
        "link": link,
        "summary": _strip_html(desc),
        "author": author,
        "published": _parse_dt(pub),
    }


def _entry_from_atom(entry) -> dict:
    title = _text_of(entry, "title") or ""
    link = ""
    for child in entry:
        if _local(child.tag) == "link":
            href = child.attrib.get("href")
            rel = child.attrib.get("rel", "alternate")
            if href and rel == "alternate":
                link = href
                break
    if not link:
        for child in entry:
            if _local(child.tag) == "link" and child.attrib.get("href"):
                link = child.attrib["href"]
                break
    guid = _text_of(entry, "id") or link or title
    summary = _text_of(entry, "summary") or _text_of(entry, "content") or ""
    published = _text_of(entry, "published") or _text_of(entry, "updated")
    author = None
    for child in entry:
        if _local(child.tag) == "author":
            author = _text_of(child, "name")
            break
    return {
        "id": guid,
        "title": title,
        "link": link,
        "summary": _strip_html(summary),
        "author": author,
        "published": _parse_dt(published),
    }
