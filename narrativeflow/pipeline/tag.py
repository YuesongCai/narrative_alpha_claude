"""Stage 3 — Narrative tagging.

🤖 Each non-noise item is offered to the AI tagger together with the current
list of active narratives. The tagger returns either matches against existing
narratives or a "new narrative" suggestion. We keep the bookkeeping here:
attach matches, optionally seed a new narrative, refresh `last_updated`.

Centroid terms are recomputed lazily (when synthesis runs) so this stage stays
fast and never blocks on TF-IDF math.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from .. import ai
from ..models import LifecycleStage, Narrative, NarrativeContent, RawContent, SourceType, utcnow
from ..store import ContentRepo, NarrativeRepo, get_session

logger = logging.getLogger(__name__)

# Limit of narratives presented as candidates to the tagger; the highest-heat
# narratives win the slot. Beyond this we'd risk confusing the model.
MAX_CANDIDATES = 25


def tag_content(*, batch_size: int = 200) -> dict[str, int]:
    """Tag every untagged, non-noise item. Returns event counts."""
    matched = 0
    new_narratives = 0
    skipped = 0

    with get_session() as session:
        c_repo = ContentRepo(session)
        n_repo = NarrativeRepo(session)

        # Fast lookup of (id → already tagged) to skip done items.
        already_tagged = _already_tagged_ids(session)

        candidates = _candidate_payload(n_repo.list_active(limit=MAX_CANDIDATES))
        items = c_repo.unprocessed(limit=batch_size)
        for item in items:
            if item.id in already_tagged:
                skipped += 1
                continue
            result = ai.tag_to_narratives(
                title=item.title,
                body=item.body,
                candidate_narratives=candidates,
            )
            for m in result["matches"]:
                target = n_repo.get(m["narrative_id"])
                if not target:
                    continue
                n_repo.attach_content(target, item, relevance=m["relevance"], tagged_by="auto")
                target.last_updated = utcnow()
                matched += 1

            if result.get("new_narrative") and not result["matches"]:
                new = _seed_narrative(
                    n_repo,
                    title=result["new_narrative"]["title"],
                    one_liner=result["new_narrative"]["one_liner"],
                )
                n_repo.attach_content(new, item, relevance=0.95, tagged_by="auto")
                new_narratives += 1
                # Add the freshly seeded narrative to the candidate set so the
                # next item in this batch can match it.
                candidates.append({
                    "id": new.id,
                    "title": new.title,
                    "one_liner": new.one_liner,
                    "centroid_terms": new.centroid_terms,
                })

    logger.info("tag: matched=%d new=%d skipped=%d", matched, new_narratives, skipped)
    return {"matched": matched, "new_narratives": new_narratives, "skipped": skipped}


def _already_tagged_ids(session: Session) -> set[int]:
    rows = session.query(NarrativeContent.content_id).distinct().all()
    return {r[0] for r in rows}


def _candidate_payload(narratives: list[Narrative]) -> list[dict]:
    return [
        {
            "id": n.id,
            "title": n.title,
            "one_liner": n.one_liner,
            "centroid_terms": list(n.centroid_terms),
        }
        for n in narratives
    ]


def _seed_narrative(repo: NarrativeRepo, *, title: str, one_liner: str) -> Narrative:
    slug = repo.slugify(title)
    n = Narrative(
        title=title[:200],
        slug=slug,
        one_liner=one_liner[:600],
        source_type=SourceType.MARKET_DERIVED.value,
        lifecycle_stage=LifecycleStage.EMERGING.value,
        heat_score=0.0,
    )
    repo.upsert(n)
    return n
