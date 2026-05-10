"""Pipeline orchestrator — runs the four stages in sequence."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from ..sources import SourceAdapter, default_registry
from .filter import filter_noise
from .ingest import ingest_from
from .synthesize import synthesize_all
from .tag import tag_content

logger = logging.getLogger(__name__)


@dataclass
class PipelineReport:
    ingested: dict[str, int] = field(default_factory=dict)
    filtered: dict[str, int] = field(default_factory=dict)
    tagged: dict[str, int] = field(default_factory=dict)
    synthesized: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        total_ingested = sum(self.ingested.values())
        return (
            f"ingested={total_ingested} "
            f"filtered_noise={self.filtered.get('filtered', 0)} "
            f"matched={self.tagged.get('matched', 0)} "
            f"new_narratives={self.tagged.get('new_narratives', 0)} "
            f"synthesized={self.synthesized.get('synthesized', 0)} "
            f"state_changes={self.synthesized.get('state_changes', 0)}"
        )

    def to_dict(self) -> dict:
        return asdict(self)


def run_pipeline(
    *,
    adapters: Optional[Iterable[SourceAdapter]] = None,
    skip_ingest: bool = False,
    force_synthesis: bool = False,
) -> PipelineReport:
    """Full pipeline: ingest → filter → tag → synthesize.

    Each stage is independent — `skip_ingest=True` is useful when you've just
    submitted content manually or want to re-run downstream stages.
    """
    report = PipelineReport()

    if not skip_ingest:
        adapters = list(adapters) if adapters is not None else default_registry().all()
        report.ingested = ingest_from(adapters)

    report.filtered = filter_noise()
    report.tagged = tag_content()
    report.synthesized = synthesize_all(force=force_synthesis)
    return report
