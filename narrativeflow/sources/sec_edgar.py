"""SEC EDGAR full-text RSS adapter.

Pulls the latest 8-K / 10-Q / 10-K filings from the SEC's public Atom feed.
Filing summaries are short but the metadata (filer, form type, accession) is
high-signal for narrative tagging.

The SEC requires a descriptive User-Agent on programmatic requests.
"""

from __future__ import annotations

import logging
from typing import Iterable

import httpx

from . import _feed_parser
from .base import FetchedItem, SourceAdapter

logger = logging.getLogger(__name__)

EDGAR_FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&output=atom&count=40"
SEC_UA = "NarrativeFlow research aaron@example.com"


class SECEdgarSource(SourceAdapter):
    def __init__(self, *, key: str = "sec_edgar_8k", form_type: str = "8-K") -> None:
        self.key = key
        self.name = f"SEC EDGAR ({form_type})"
        self.form_type = form_type

    def fetch(self) -> Iterable[FetchedItem]:
        url = EDGAR_FEED.format(form_type=self.form_type)
        try:
            with httpx.Client(timeout=20.0, headers={"User-Agent": SEC_UA, "Accept": "application/atom+xml"}) as client:
                resp = client.get(url)
                resp.raise_for_status()
                entries = _feed_parser.parse(resp.content)
        except Exception as e:  # pragma: no cover - network
            logger.warning("SEC EDGAR fetch failed: %s", e)
            return []

        items: list[FetchedItem] = []
        for entry in entries:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or None
            external_id = entry.get("id") or link or title
            body = (entry.get("summary") or "")[:2000]
            items.append(
                FetchedItem(
                    external_id=str(external_id)[:256],
                    title=title[:1024],
                    body=body,
                    url=link,
                    author="SEC EDGAR",
                    language="en",
                    published_at=entry.get("published"),
                )
            )
        return items
