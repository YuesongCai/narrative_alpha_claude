"""End-to-end pipeline against the bundled seed corpus, with AI disabled."""

from datetime import datetime
from pathlib import Path

import json
import pytest

from narrativeflow.models import LifecycleStage
from narrativeflow.pipeline import run_pipeline
from narrativeflow.pipeline.ingest import ingest_from
from narrativeflow.sources.manual import ManualSource
from narrativeflow.store import NarrativeRepo, ContentRepo, get_session


SEED_PATH = Path(__file__).resolve().parent.parent / "narrativeflow" / "data" / "seed_content.json"


def _seed_adapters():
    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    out = []
    for it in items:
        a = ManualSource(
            title=it["title"],
            body=it["body"],
            url=it.get("url"),
            author=it.get("author"),
            external_id=it.get("external_id"),
            published_at=datetime.fromisoformat(it["published_at"]) if it.get("published_at") else None,
        )
        a.key = "seed"
        a.name = "Seed corpus"
        out.append(a)
    return out


def test_full_pipeline_ingests_filters_tags_synthesizes():
    counts = ingest_from(_seed_adapters())
    assert counts["seed"] >= 10  # 10 real signals + 2 noise items

    report = run_pipeline(skip_ingest=True)
    # Noise filter should catch the sponsored ad and the horoscope.
    assert report.filtered["filtered"] >= 2
    assert report.tagged["new_narratives"] >= 3
    assert report.synthesized["synthesized"] >= 3


def test_pipeline_produces_narratives_with_ticker_maps():
    ingest_from(_seed_adapters())
    run_pipeline(skip_ingest=True)

    with get_session() as session:
        narratives = NarrativeRepo(session).list_active(limit=20)
        assert len(narratives) >= 3
        # At least one narrative should have surfaced tickers via the heuristic.
        any_with_tickers = any(
            (n.ticker_map.get("main_trade") or [])
            for n in narratives
        )
        assert any_with_tickers, "expected at least one narrative with main-trade tickers"


def test_pipeline_assigns_lifecycle_stages():
    ingest_from(_seed_adapters())
    run_pipeline(skip_ingest=True)

    with get_session() as session:
        narratives = NarrativeRepo(session).list_active(limit=20)
        valid_stages = {s.value for s in LifecycleStage}
        for n in narratives:
            assert n.lifecycle_stage in valid_stages
            assert 0.0 <= n.heat_score <= 1.0


def test_pipeline_is_idempotent():
    ingest_from(_seed_adapters())
    run_pipeline(skip_ingest=True)
    with get_session() as session:
        first_count = ContentRepo(session).count()
    # Running again should not add new content (dedup by external_id).
    ingest_from(_seed_adapters())
    with get_session() as session:
        second_count = ContentRepo(session).count()
    assert first_count == second_count


def test_noise_items_excluded_from_narratives():
    ingest_from(_seed_adapters())
    run_pipeline(skip_ingest=True)

    with get_session() as session:
        narratives = NarrativeRepo(session).list_active(limit=20)
        for n in narratives:
            for c in NarrativeRepo(session).contents_for(n.id):
                assert "horoscope" not in c.title.lower()
                assert "sponsored" not in c.title.lower()
