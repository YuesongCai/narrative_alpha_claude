"""Stage 2 — Noise filtering.

🤖 Calls `ai.classify_noise` for each unprocessed item; falls back to a rules-
based classifier when the AI client is disabled. Items flagged as noise have
`is_noise=True` set so they're excluded from downstream stages, but stay in
the table for audit / re-processing.
"""

from __future__ import annotations

import logging
from typing import Iterable

from .. import ai
from ..models import RawContent
from ..store import ContentRepo, get_session

logger = logging.getLogger(__name__)


def filter_noise(*, batch_size: int = 200) -> dict[str, int]:
    """Process every unfiltered item. Returns counts of {kept, filtered}."""
    kept = 0
    filtered = 0
    with get_session() as session:
        repo = ContentRepo(session)
        unprocessed = repo.unprocessed(limit=batch_size)
        # We treat noise_score=0 as "never classified". Re-runs are idempotent.
        for item in unprocessed:
            if item.noise_score > 0 or item.noise_reason:
                continue
            verdict = ai.classify_noise(title=item.title, body=item.body)
            item.is_noise = bool(verdict["is_noise"])
            item.noise_score = float(verdict["noise_score"])
            item.noise_reason = str(verdict.get("reason") or "")
            if item.is_noise:
                filtered += 1
            else:
                kept += 1
    logger.info("noise filter: kept=%d filtered=%d", kept, filtered)
    return {"kept": kept, "filtered": filtered}
