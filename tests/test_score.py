"""Strength score & stage transitions."""

from datetime import datetime, timedelta

from narrative_alpha.models import Narrative, Source, Stage, Tier
from narrative_alpha.score import (
    factor_breakdown,
    score_narrative,
    update_stage,
)


def _make_source(sid: str, *, tier: int, days_ago: int, org: str | None = None, cites=None) -> Source:
    return Source(
        source_id=sid,
        title=f"title-{sid}",
        org=org or f"org-{sid}",
        tier=tier,
        published_at=datetime.utcnow() - timedelta(days=days_ago),
        body=f"body-{sid}",
        cites=list(cites or []),
    )


def _narrative(sources: list[Source]) -> Narrative:
    return Narrative(
        narrative_id="n",
        title="t",
        subtitle="s",
        stage=Stage.EMERGING,
        strength_score=0.0,
        first_seen=min(s.published_at for s in sources) if sources else datetime.utcnow(),
        last_updated=datetime.utcnow(),
        source_trail=[s.source_id for s in sources],
    )


def test_zero_sources_scores_zero():
    assert score_narrative(_narrative([]), []) == 0.0


def test_t1_research_scores_higher_than_t3_chatter():
    t1 = [_make_source(f"a{i}", tier=Tier.T1_PRIMARY_RESEARCH, days_ago=2, org=f"bank-{i}") for i in range(2)]
    t3 = [_make_source(f"b{i}", tier=Tier.T3_SOCIAL_SELF_MEDIA, days_ago=2, org=f"tweet-{i}") for i in range(10)]

    s_t1 = score_narrative(_narrative(t1), t1)
    s_t3 = score_narrative(_narrative(t3), t3)

    assert s_t1 > s_t3, f"expected T1 narrative to outrank T3 chatter (got {s_t1} vs {s_t3})"


def test_recency_acceleration_matters():
    fresh = [_make_source(f"f{i}", tier=Tier.T2_QUALITY_MEDIA, days_ago=1, org=f"o-{i}") for i in range(3)]
    stale = [_make_source(f"s{i}", tier=Tier.T2_QUALITY_MEDIA, days_ago=90, org=f"o-{i}") for i in range(3)]

    f_breakdown = factor_breakdown(_narrative(fresh), fresh)
    s_breakdown = factor_breakdown(_narrative(stale), stale)
    assert f_breakdown["recency"] > s_breakdown["recency"]


def test_diversity_beats_self_referencing_chain():
    one_org = [_make_source(f"x{i}", tier=Tier.T2_QUALITY_MEDIA, days_ago=1, org="same-org") for i in range(5)]
    five_orgs = [_make_source(f"y{i}", tier=Tier.T2_QUALITY_MEDIA, days_ago=1, org=f"unique-{i}") for i in range(5)]

    a = factor_breakdown(_narrative(one_org), one_org)["reinforcement"]
    b = factor_breakdown(_narrative(five_orgs), five_orgs)["reinforcement"]
    assert b > a


def test_stage_thresholds():
    assert Stage.from_score(0) == Stage.EMERGING
    assert Stage.from_score(35) == Stage.EMERGING
    assert Stage.from_score(36) == Stage.STRENGTHENING
    assert Stage.from_score(70) == Stage.STRENGTHENING
    assert Stage.from_score(71) == Stage.CONSENSUS
    assert Stage.from_score(100) == Stage.CONSENSUS


def test_update_stage_records_transition():
    n = _narrative([])
    n.stage = Stage.EMERGING
    transition = update_stage(n, score=72)
    assert n.stage == Stage.CONSENSUS
    assert transition is not None
    assert transition.from_stage == Stage.EMERGING
    assert transition.to_stage == Stage.CONSENSUS
    assert n.transitions[-1] is transition


def test_update_stage_is_noop_when_unchanged():
    n = _narrative([])
    n.stage = Stage.EMERGING
    transition = update_stage(n, score=20)
    assert transition is None
    assert n.stage == Stage.EMERGING
    assert not n.transitions
