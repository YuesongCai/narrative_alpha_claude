"""Lifecycle staging — heat composition + stage thresholds."""

from datetime import datetime, timedelta

from narrativeflow.models import LifecycleStage, Narrative, RawContent
from narrativeflow.pipeline.lifecycle import assign_stage, compute_heat, top_terms


def _content(*, days_ago: int, source_key: str = "feed1", title: str = "x", body: str = "x") -> RawContent:
    return RawContent(
        source_key=source_key,
        external_id=f"{source_key}-{days_ago}-{title}",
        title=title,
        body=body,
        content_hash="h",
        published_at=datetime.utcnow() - timedelta(days=days_ago),
    )


def _narrative(stage: str = LifecycleStage.EMERGING.value) -> Narrative:
    return Narrative(id="n1", title="t", slug="t", lifecycle_stage=stage)


def test_empty_narrative_zero_heat():
    heat, _ = compute_heat(_narrative(), [])
    assert heat == 0.0


def test_recent_burst_drives_heat():
    fresh = [_content(days_ago=1, source_key=f"s{i}") for i in range(8)]
    heat, breakdown = compute_heat(_narrative(), fresh)
    assert heat > 0.6
    assert breakdown["fresh_7d"] == 8


def test_stale_narrative_low_heat():
    stale = [_content(days_ago=60) for _ in range(5)]
    heat, _ = compute_heat(_narrative(), stale)
    assert heat < 0.2


def test_stage_thresholds():
    """Stage progression should follow the documented thresholds (0.20 / 0.45 / 0.70 / 0.85)."""
    n = _narrative()
    assert assign_stage(n, heat=0.10, contents=[_content(days_ago=1)]) == LifecycleStage.EMERGING.value
    assert assign_stage(n, heat=0.50, contents=[_content(days_ago=1)]) == LifecycleStage.ACCELERATING.value
    assert assign_stage(n, heat=0.75, contents=[_content(days_ago=1)]) == LifecycleStage.CONSENSUS.value
    assert assign_stage(n, heat=0.90, contents=[_content(days_ago=1)]) == LifecycleStage.CROWDED.value


def test_fading_override_when_silent_after_consensus():
    n = _narrative(stage=LifecycleStage.CONSENSUS.value)
    silent = [_content(days_ago=20)]  # nothing recent
    stage = assign_stage(n, heat=0.55, contents=silent)
    assert stage == LifecycleStage.FADING.value


def test_top_terms_extracts_meaningful_tokens():
    contents = [
        _content(days_ago=1, title="Nuclear renaissance accelerates",
                 body="SMR commercialization timelines compress as hyperscalers sign nuclear PPAs."),
        _content(days_ago=2, title="Hyperscaler PPAs cite nuclear",
                 body="Amazon and Microsoft sign multi-year nuclear power purchase agreements for AI workloads."),
    ]
    terms = top_terms(contents, k=10)
    assert "nuclear" in terms
    assert "hyperscalers" in terms or "hyperscaler" in terms
    assert "the" not in terms  # stopwords removed
