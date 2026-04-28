"""End-to-end pipeline using the bundled seed corpus."""

from datetime import datetime
from pathlib import Path

import pytest

from narrative_alpha.digest import render_html, render_terminal
from narrative_alpha.ingest import load_seed_file, submit_manual
from narrative_alpha.models import Stage
from narrative_alpha.pipeline import run_pipeline
from narrative_alpha.store import Store


SEED = Path(__file__).resolve().parent.parent / "data" / "seed_sources.json"


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.load()
    load_seed_file(s, SEED)
    return s


def test_pipeline_produces_narratives_and_digest(store):
    today = datetime(2026, 4, 28, 12, 0, 0)
    report = run_pipeline(store, today=today)

    assert report.sources_processed == len(store.sources)
    assert len(store.active_narratives()) >= 3
    assert report.digest is not None

    digest = report.digest
    assert digest.digest_date == today.date()
    assert sum(digest.counts.values()) >= 3


def test_digest_orders_emerging_first(store):
    run_pipeline(store, today=datetime(2026, 4, 28))
    digest = store.latest_digest()
    stages = [store.narratives[nid].stage for nid in digest.narrative_ids]

    indices = [Stage.order_index(s) for s in stages]
    assert indices == sorted(indices), f"digest order should be Emerging→Strengthening→Consensus, got {stages}"


def test_html_renders_without_template_placeholders(store):
    run_pipeline(store, today=datetime(2026, 4, 28))
    digest = store.latest_digest()
    html = render_html(store, digest)
    assert "{{" not in html and "}}" not in html
    assert "Narrative Alpha" in html


def test_terminal_render_smoke(store):
    run_pipeline(store, today=datetime(2026, 4, 28))
    text = render_terminal(store, store.latest_digest())
    assert "NARRATIVE ALPHA" in text
    assert "strength" in text


def test_user_submitted_source_feeds_pipeline(store):
    run_pipeline(store, today=datetime(2026, 4, 28))
    pre_count = len(store.active_narratives())

    submit_manual(
        store,
        title="Humanoid Robotics: Tesla Optimus production curve",
        org="Bernstein",
        body="Bernstein research note arguing humanoid robotics manufacturing is entering a learning-curve phase. "
             "Tesla Optimus production targets imply per-unit cost trajectory that re-rates the entire humanoid robotics "
             "supply chain. Actuator vendors and reduction-gear specialists are the supply-chain beneficiaries.",
        url="https://example.com/bernstein-humanoid",
    )
    report = run_pipeline(store, today=datetime(2026, 4, 29))
    # The new source should produce at least one new narrative.
    assert len(store.active_narratives()) >= pre_count + 1
    assert report.sources_processed == 1


def test_round_trip_through_disk(store, tmp_path):
    run_pipeline(store, today=datetime(2026, 4, 28))
    store.save()
    nar_count = len(store.narratives)
    src_count = len(store.sources)

    re = Store(store.data_dir).load()
    assert len(re.narratives) == nar_count
    assert len(re.sources) == src_count

    # Re-running should be idempotent (no new sources to process).
    report = run_pipeline(re, today=datetime(2026, 4, 28))
    assert report.sources_processed == 0
