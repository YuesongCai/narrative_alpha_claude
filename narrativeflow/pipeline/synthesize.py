"""Stage 4 — Synthesis + heat/lifecycle update + state-change detection.

For each narrative that has new content since its last synthesis run:

  1. Recompute the lexical centroid + heat score.
  2. 🤖 Call `ai.synthesize_narrative` to refresh one_liner, causal_chain,
     ticker_map, catalysts, key_evidence, counter_narrative.
  3. Detect lifecycle stage change → emit a `StateChange` (heat_shift).
  4. Detect ticker-map rotation → emit `ticker_rotation`.
  5. Detect new catalysts → emit `new_catalyst`.

State changes are the only source of user notifications, so anything emitted
here will reach a subscriber's Telegram (or whatever channel they configured).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .. import ai
from ..models import (
    LifecycleStage,
    Narrative,
    StateChange,
    StateChangeType,
    utcnow,
)
from ..store import NarrativeRepo, StateChangeRepo, get_session
from .lifecycle import assign_stage, compute_heat, top_terms

logger = logging.getLogger(__name__)


def synthesize_all(*, max_narratives: int = 25, force: bool = False) -> dict[str, int]:
    synthesized = 0
    state_changes_emitted = 0

    with get_session() as session:
        n_repo = NarrativeRepo(session)
        sc_repo = StateChangeRepo(session)

        for n in n_repo.list_active(limit=max_narratives):
            contents = n_repo.contents_for(n.id, limit=50)
            if not contents:
                continue
            if not force and n.last_synthesized_at and not _has_new_content(n, contents):
                continue

            # 1. Centroid + heat ----------------------------------------------------
            n.centroid_terms = top_terms(contents)
            heat, _ = compute_heat(n, contents)
            old_stage = n.lifecycle_stage
            new_stage = assign_stage(n, heat=heat, contents=contents)
            n.heat_score = heat
            n.lifecycle_stage = new_stage

            # 2. Synthesis (AI or heuristic) ---------------------------------------
            excerpts = [
                {
                    "publisher": c.source_key,
                    "date": c.published_at.date().isoformat(),
                    "title": c.title,
                    "body": c.body,
                }
                for c in contents[:15]
            ]
            old_tickers = _ticker_set(n.ticker_map)
            old_catalysts = _catalyst_set(n.catalysts)

            tracker = ai.synthesize_narrative(
                title=n.title,
                one_liner_hint=n.one_liner or n.title,
                excerpts=excerpts,
            )
            n.one_liner = tracker["one_liner"] or n.one_liner
            n.causal_chain = tracker["causal_chain"]
            n.ticker_map = tracker["ticker_map"]
            n.catalysts = tracker["catalysts"]
            n.key_evidence = tracker["key_evidence"]
            n.counter_narrative = tracker["counter_narrative"]
            n.last_synthesized_at = utcnow()
            n.last_updated = utcnow()
            synthesized += 1

            # 3. Emit state changes ------------------------------------------------
            state_changes_emitted += _emit_state_changes(
                sc_repo,
                narrative=n,
                old_stage=old_stage,
                old_tickers=old_tickers,
                old_catalysts=old_catalysts,
            )

    logger.info("synthesis: synthesized=%d state_changes=%d", synthesized, state_changes_emitted)
    return {"synthesized": synthesized, "state_changes": state_changes_emitted}


# ----------------------------------------------------------- helpers
def _has_new_content(narrative: Narrative, contents: list) -> bool:
    """Skip resyn if no item arrived since the last run."""
    last = narrative.last_synthesized_at
    if not last:
        return True
    most_recent = max(c.published_at for c in contents)
    return most_recent > last


def _ticker_set(ticker_map: dict) -> set[str]:
    out: set[str] = set()
    for bucket in ("main_trade", "second_derivative", "etf_proxy", "hk_mirror"):
        for t in ticker_map.get(bucket, []) or []:
            sym = t.get("ticker") if isinstance(t, dict) else None
            if sym:
                out.add(sym.upper())
    return out


def _catalyst_set(catalysts: list) -> set[tuple[str, str]]:
    return {((c.get("date_hint") or ""), (c.get("event") or "")) for c in (catalysts or []) if isinstance(c, dict)}


def _emit_state_changes(
    sc_repo: StateChangeRepo,
    *,
    narrative: Narrative,
    old_stage: str,
    old_tickers: set[str],
    old_catalysts: set[tuple[str, str]],
) -> int:
    emitted = 0
    if narrative.lifecycle_stage != old_stage:
        sc_repo.add(StateChange(
            narrative_id=narrative.id,
            change_type=StateChangeType.HEAT_SHIFT.value,
            description=f"{old_stage} → {narrative.lifecycle_stage} (heat {narrative.heat_score:.2f})",
            payload={"from": old_stage, "to": narrative.lifecycle_stage, "heat": narrative.heat_score},
        ))
        emitted += 1

        # Map crowded/fading to an explicit exit signal so it's easy to filter on.
        if narrative.lifecycle_stage in (LifecycleStage.CROWDED.value, LifecycleStage.FADING.value):
            sc_repo.add(StateChange(
                narrative_id=narrative.id,
                change_type=StateChangeType.EXIT_SIGNAL.value,
                description=f"Lifecycle entered {narrative.lifecycle_stage} — alpha window closing.",
                payload={"stage": narrative.lifecycle_stage},
            ))
            emitted += 1

    new_tickers = _ticker_set(narrative.ticker_map)
    rotated_in = new_tickers - old_tickers
    rotated_out = old_tickers - new_tickers
    if old_tickers and (rotated_in or rotated_out):
        sc_repo.add(StateChange(
            narrative_id=narrative.id,
            change_type=StateChangeType.TICKER_ROTATION.value,
            description=f"+{sorted(rotated_in)} -{sorted(rotated_out)}",
            payload={"added": sorted(rotated_in), "removed": sorted(rotated_out)},
        ))
        emitted += 1

    new_catalysts = _catalyst_set(narrative.catalysts) - old_catalysts
    for date_hint, event in new_catalysts:
        if not event:
            continue
        sc_repo.add(StateChange(
            narrative_id=narrative.id,
            change_type=StateChangeType.NEW_CATALYST.value,
            description=f"New catalyst — {event} ({date_hint or 'TBD'})",
            payload={"date_hint": date_hint, "event": event},
        ))
        emitted += 1

    return emitted
