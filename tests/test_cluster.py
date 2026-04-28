"""Clustering — claims about the same theme should land in the same narrative."""

from datetime import datetime

from narrative_alpha.cluster import cluster_claims
from narrative_alpha.extract import extract_claim
from narrative_alpha.models import Source, Tier


def _src(sid: str, title: str, body: str, *, tier=Tier.T2_QUALITY_MEDIA) -> Source:
    return Source(
        source_id=sid,
        title=title,
        org="org-" + sid,
        tier=tier,
        published_at=datetime.utcnow(),
        body=body,
    )


def test_two_claims_about_same_theme_cluster_together():
    sources = [
        _src(
            "a",
            "AI inference cost is collapsing",
            "Inference cost per token is falling rapidly thanks to networking and memory improvements. "
            "Connectivity silicon CRDO and Arista ANET benefit. AMD becomes a credible second-source GPU. "
            "Inference cost deflation expands TAM rather than compressing margins.",
        ),
        _src(
            "b",
            "Inference deflation reshapes the AI stack",
            "Inference cost per token has dropped 4x. Connectivity overhead is being engineered out. "
            "Networking fabric vendors and second-tier GPU makers see asymmetric upside as inference scales out laterally.",
        ),
    ]
    by_id = {s.source_id: s for s in sources}
    claims = [extract_claim(s) for s in sources]

    narratives, assignments = cluster_claims(claims, by_id, existing=[])
    assert len(narratives) == 1
    assert len(set(assignments.values())) == 1


def test_unrelated_claims_seed_separate_narratives():
    sources = [
        _src(
            "a",
            "AI inference cost deflation",
            "Inference cost per token is falling. Networking and connectivity silicon benefit. CRDO ANET AMD inference deflation.",
        ),
        _src(
            "b",
            "GLP-1 second-line entrants gain share",
            "Viking Therapeutics VKTX dual-agonist Phase 2 obesity drug data shows competitive efficacy and tolerability "
            "as second-line GLP-1 supply remains constrained at LLY and NVO.",
        ),
        _src(
            "c",
            "Japan reindustrialization second leg",
            "Tokyo Electron Advantest Shin-Etsu wafer fab Japan semiconductor reindustrialization Rapidus Kumamoto.",
        ),
    ]
    by_id = {s.source_id: s for s in sources}
    claims = [extract_claim(s) for s in sources]

    narratives, assignments = cluster_claims(claims, by_id, existing=[])
    assert len(narratives) == 3
    assert len(set(assignments.values())) == 3


def test_new_claim_joins_existing_narrative():
    seed = _src(
        "a",
        "AI inference cost deflation",
        "Inference cost is collapsing. Connectivity silicon and networking fabric benefit. CRDO ANET inference deflation.",
    )
    by_id = {seed.source_id: seed}
    claim_a = extract_claim(seed)
    narratives, _ = cluster_claims([claim_a], by_id, existing=[])
    assert len(narratives) == 1
    nid = narratives[0].narrative_id

    follow_up = _src(
        "b",
        "Networking fabrics ride the inference wave",
        "Arista's leaf-spine fabric becomes the inference standard as cost per token deflates further. CRDO connectivity inference.",
    )
    by_id[follow_up.source_id] = follow_up
    claim_b = extract_claim(follow_up)
    narratives_2, assignments_2 = cluster_claims([claim_b], by_id, existing=narratives)

    assert len(narratives_2) == 1
    assert assignments_2[claim_b.claim_id] == nid
