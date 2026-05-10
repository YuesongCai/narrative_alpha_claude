"""Source registry — the shipping list of public adapters.

The default set is loaded from `data/source_config.yaml` so non-engineers can
add a new RSS feed without writing Python. Programmatic registration is also
supported (e.g. tests, ad-hoc CLI use).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import yaml

from ..config import get_settings
from .base import SourceAdapter
from .hackernews import HackerNewsSource
from .rss import RSSSource
from .sec_edgar import SECEdgarSource

logger = logging.getLogger(__name__)


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if adapter.key in self._adapters:
            logger.debug("overwriting existing source adapter %s", adapter.key)
        self._adapters[adapter.key] = adapter

    def get(self, key: str) -> SourceAdapter | None:
        return self._adapters.get(key)

    def all(self) -> list[SourceAdapter]:
        return list(self._adapters.values())

    def keys(self) -> list[str]:
        return list(self._adapters.keys())


def _from_config(path: Path) -> list[SourceAdapter]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    adapters: list[SourceAdapter] = []
    for entry in (cfg.get("sources") or []):
        kind = entry.get("kind")
        if kind == "rss":
            adapters.append(RSSSource(
                key=entry["key"],
                name=entry.get("name", entry["key"]),
                url=entry["url"],
                language=entry.get("language", "en"),
            ))
        elif kind == "sec_edgar":
            adapters.append(SECEdgarSource(
                key=entry["key"],
                form_type=entry.get("form_type", "8-K"),
            ))
        elif kind == "hackernews":
            adapters.append(HackerNewsSource(top_n=entry.get("top_n", 30)))
        else:
            logger.warning("unknown source kind: %s", kind)
    return adapters


def default_registry() -> SourceRegistry:
    """Build the registry from the bundled YAML config."""
    settings = get_settings()
    reg = SourceRegistry()
    for adapter in _from_config(settings.project_root / "narrativeflow" / "data" / "source_config.yaml"):
        reg.register(adapter)
    return reg
