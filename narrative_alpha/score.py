"""Strength score & stage transitions — Section 4.3.

The composite is the four factors specified in the PRD, no more:

    strength = source_count(25) + tier_mix(30) + recency(25) + reinforcement(20)

Each factor is implemented as a self-contained function so it can be tuned or
unit-tested in isolation. `score_narrative` is the only public surface.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

from .models import Narrative, Source, Stage, StageTransition, Tier
from .tiers import tier_weight


SOURCE_COUNT_CAP = 8       # diminishing returns kick in past this
RECENCY_HALF_LIFE_DAYS = 14
SOURCE_COUNT_WEIGHT = 25.0
TIER_MIX_WEIGHT = 30.0
RECENCY_WEIGHT = 25.0
REINFORCEMENT_WEIGHT = 20.0


def score_narrative(narrative: Narrative, sources: Iterable[Source], *, now: datetime | None = None) -> float:
    """Compute the 0–100 composite score for a narrative."""
    src_list = [s for s in sources if s.source_id in narrative.source_trail]
    now = now or datetime.utcnow()

    s1 = _source_count_score(src_list)
    s2 = _tier_mix_score(src_list)
    s3 = _recency_score(src_list, now=now)
    s4 = _reinforcement_score(src_list)

    return round(s1 + s2 + s3 + s4, 2)


def factor_breakdown(narrative: Narrative, sources: Iterable[Source], *, now: datetime | None = None) -> dict[str, float]:
    """Useful for debugging / digest tooltips."""
    src_list = [s for s in sources if s.source_id in narrative.source_trail]
    now = now or datetime.utcnow()
    return {
        "source_count": _source_count_score(src_list),
        "tier_mix": _tier_mix_score(src_list),
        "recency": _recency_score(src_list, now=now),
        "reinforcement": _reinforcement_score(src_list),
    }


# ------------------------------------------------------------- factors
def _source_count_score(sources: list[Source]) -> float:
    n = len(sources)
    if n <= 0:
        return 0.0
    # log curve that hits the weight at N = SOURCE_COUNT_CAP, mild past it.
    return SOURCE_COUNT_WEIGHT * min(1.0, math.log(1 + n) / math.log(1 + SOURCE_COUNT_CAP))


def _tier_mix_score(sources: list[Source]) -> float:
    if not sources:
        return 0.0
    weights = [tier_weight(s.tier) for s in sources]
    avg = sum(weights) / len(weights)  # 1.0 (all T3) … 3.0 (all T1)
    # Map avg from [1.0, 3.0] → [0, TIER_MIX_WEIGHT].
    normalized = max(0.0, (avg - 1.0) / 2.0)
    return TIER_MIX_WEIGHT * normalized


def _recency_score(sources: list[Source], *, now: datetime) -> float:
    """Exponential decay weighted by tier so a fresh T1 dominates an old T3.

    The score is the sum of per-source decay terms, capped at 1.0 then scaled
    to RECENCY_WEIGHT. This naturally captures "acceleration": a burst of new
    mentions piles up exponentially while old ones decay out.
    """
    if not sources:
        return 0.0
    total = 0.0
    for s in sources:
        days = max(0.0, (now - s.published_at).total_seconds() / 86400.0)
        decay = 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)
        total += decay * tier_weight(s.tier) / 3.0  # normalize tier weight to [0,1]
    return RECENCY_WEIGHT * min(1.0, total / 4.0)  # 4 fresh T1s → max score


def _reinforcement_score(sources: list[Source]) -> float:
    """Independent convergence at tier-weighted quality > citation chains.

    Two safeguards beyond simple distinct-org counting:
      * Quality multiplier — 10 distinct T3 publishers is not the same signal as
        2 distinct T1 desks. The PRD treats T3 saturation as a closing window,
        not strengthening, so reinforcement scales by the average per-org tier
        weight.
      * Citation penalty — if sources in the set cite each other (citation
        chain) the score is halved at worst.
    """
    if not sources:
        return 0.0
    org_best_tier: dict[str, int] = {}
    for s in sources:
        org = s.org.lower()
        if org not in org_best_tier or s.tier < org_best_tier[org]:
            org_best_tier[org] = s.tier

    diversity = min(1.0, len(org_best_tier) / 5.0)
    avg_quality = sum(tier_weight(t) for t in org_best_tier.values()) / len(org_best_tier)
    quality_factor = avg_quality / 3.0  # T1 → 1.0, T2 → 0.67, T3 → 0.33

    cited_ids = {sid for s in sources for sid in s.cites}
    cited_in_set = sum(1 for s in sources if s.source_id in cited_ids)
    citation_penalty = cited_in_set / len(sources) * 0.5

    return REINFORCEMENT_WEIGHT * diversity * quality_factor * (1.0 - citation_penalty)


# --------------------------------------------------- stage transitions
def update_stage(narrative: Narrative, *, score: float, now: datetime | None = None) -> StageTransition | None:
    """Apply the new score and record a transition if the stage flipped."""
    new_stage = Stage.from_score(score)
    narrative.strength_score = score
    if new_stage == narrative.stage:
        return None

    now = now or datetime.utcnow()
    transition = StageTransition(
        from_stage=narrative.stage,
        to_stage=new_stage,
        at=now,
        score=score,
    )
    narrative.stage = new_stage
    narrative.transitions.append(transition)
    narrative.last_updated = now
    return transition
