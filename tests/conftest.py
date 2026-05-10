"""Test fixtures — every test runs against an isolated SQLite DB in tmp_path."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("NARRATIVEFLOW_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # force heuristic fallback in tests

    # Clear cached settings + engine + AI client.
    from narrativeflow import ai as _ai
    from narrativeflow.config import get_settings
    from narrativeflow.store import db as _db

    get_settings.cache_clear()
    _db._engine = None
    _db._SessionFactory = None
    _ai.get_client.cache_clear()

    _db.init_db()
    yield
    _db._engine = None
    _db._SessionFactory = None
