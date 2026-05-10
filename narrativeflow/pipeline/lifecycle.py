"""Lifecycle staging — Emerging → Accelerating → Consensus → Crowded → Fading.

Heat score is a 0..1 composite of three signals (purposely simple for V1):

  * mention_velocity  — count of fresh content tagged in the last 7 days,
                        normalized against an asymptote.
  * source_diversity  — distinct publishers in the source trail.
  * recency           — days since the most recent tag, exponential decay.

Stage thresholds map heat to one of five buckets, plus a "fading" flag when
the velocity falls off after a recent peak. The thresholds are calibrated to
the V1 source list — we'll tune them once we have ground-truth data.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable

from ..models import LifecycleStage, Narrative, RawContent


# Tunable knobs. Names mirror the readout the digest exposes for debugging.
VELOCITY_ASYMPTOTE = 12      # mentions/week to saturate the velocity signal
DIVERSITY_ASYMPTOTE = 6      # distinct publishers to saturate diversity
RECENCY_HALF_LIFE_DAYS = 5

STAGE_THRESHOLDS = (
    (LifecycleStage.EMERGING, 0.20),
    (LifecycleStage.ACCELERATING, 0.45),
    (LifecycleStage.CONSENSUS, 0.70),
    (LifecycleStage.CROWDED, 0.85),
)


def compute_heat(narrative: Narrative, contents: Iterable[RawContent], *, now: datetime | None = None) -> tuple[float, dict]:
    """Returns (heat_score, breakdown_dict). Breakdown is for debugging/UI."""
    now = now or datetime.utcnow()
    contents = list(contents)
    if not contents:
        return 0.0, {"mention_velocity": 0.0, "source_diversity": 0.0, "recency": 0.0}

    # 1) Mention velocity: items in the last 7 days, scaled to [0,1].
    week_ago = now - timedelta(days=7)
    fresh = sum(1 for c in contents if c.published_at >= week_ago)
    velocity = min(1.0, fresh / VELOCITY_ASYMPTOTE)

    # 2) Source diversity: distinct source_keys.
    diversity = min(1.0, len({c.source_key for c in contents}) / DIVERSITY_ASYMPTOTE)

    # 3) Recency: half-life decay from the most recent tag.
    last = max(c.published_at for c in contents)
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    recency = 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)

    heat = round(0.45 * velocity + 0.25 * diversity + 0.30 * recency, 4)
    return heat, {
        "mention_velocity": round(velocity, 3),
        "source_diversity": round(diversity, 3),
        "recency": round(recency, 3),
        "fresh_7d": fresh,
        "distinct_sources": len({c.source_key for c in contents}),
        "days_since_last": round(days, 2),
    }


def assign_stage(narrative: Narrative, *, heat: float, contents: list[RawContent], now: datetime | None = None) -> str:
    """Map heat → stage, with a "fading" override when momentum reverses."""
    now = now or datetime.utcnow()
    stage = LifecycleStage.EMERGING.value
    for s, threshold in STAGE_THRESHOLDS:
        if heat >= threshold:
            stage = s.value

    # Fading override: if previously Crowded/Consensus and last week's velocity
    # has collapsed (no new mentions in 14d), classify as Fading.
    last = max((c.published_at for c in contents), default=None)
    days_silent = (now - last).total_seconds() / 86400.0 if last else 999
    if narrative.lifecycle_stage in (LifecycleStage.CONSENSUS.value, LifecycleStage.CROWDED.value):
        if days_silent > 14 or heat < 0.35:
            stage = LifecycleStage.FADING.value
    return stage


def top_terms(contents: Iterable[RawContent], *, k: int = 25) -> list[str]:
    """Cheap centroid: most common 4+ char tokens across the source titles +
    bodies, minus stopwords. Used as the lexical fingerprint for fallback
    tagging when AI is disabled.
    """
    bag: Counter[str] = Counter()
    for c in contents:
        for tok in _tokens(c.title + " " + c.body[:1500]):
            bag[tok] += 1
    return [t for t, _ in bag.most_common(k)]


_STOP = {
    "the", "and", "of", "in", "to", "a", "is", "for", "on", "with", "as", "by",
    "at", "from", "that", "this", "an", "be", "are", "was", "were", "or",
    "it", "its", "has", "have", "had", "but", "not", "will", "would",
    "their", "they", "them", "we", "you", "i", "into", "than", "more", "less",
}


def _tokens(text: str) -> list[str]:
    import re

    return [
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", text or "")
        if len(t) >= 4 and t.lower() not in _STOP
    ]
