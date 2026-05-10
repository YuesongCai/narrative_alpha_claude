"""FastAPI smoke tests — board renders, search responds, JSON API works."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from narrativeflow.api.main import create_app
from narrativeflow.pipeline import run_pipeline
from narrativeflow.pipeline.ingest import ingest_from
from narrativeflow.sources.manual import ManualSource


SEED_PATH = Path(__file__).resolve().parent.parent / "narrativeflow" / "data" / "seed_content.json"


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def seeded():
    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))[:6]
    adapters = []
    for it in items:
        a = ManualSource(
            title=it["title"],
            body=it["body"],
            url=it.get("url"),
            external_id=it.get("external_id"),
            published_at=datetime.fromisoformat(it["published_at"]) if it.get("published_at") else None,
        )
        a.key = "seed"
        a.name = "Seed"
        adapters.append(a)
    ingest_from(adapters)
    run_pipeline(skip_ingest=True)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "ai_enabled" in data


def test_board_renders(client, seeded):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Narrative Board" in resp.text


def test_api_narratives(client, seeded):
    resp = client.get("/api/narratives")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    sample = items[0]
    assert "title" in sample
    assert "lifecycle_stage" in sample


def test_search_lexical(client, seeded):
    resp = client.get("/search?q=nuclear")
    assert resp.status_code == 200
    assert "nuclear" in resp.text.lower()
