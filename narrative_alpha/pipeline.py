"""Daily pipeline orchestrator.

Runs the six stages from Section 6.2:
  1. Ingest    — load any new sources from the store / RSS / seed file.
  2. Extract   — produce a Claim per source (LLM with rules fallback).
  3. Cluster   — assign each claim to an existing or new narrative.
  4. Score     — recompute strength scores, detect stage transitions.
  5. Map       — refresh alpha targets for new or stage-transitioned narratives.
  6. Generate  — build today's digest.

Inputs are whatever's already in the Store; the CLI orchestrates ingestion
separately so the pipeline itself stays pure: state in → state out + digest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .alpha import attach_alpha_targets, map_alpha_targets
from .cluster import cluster_claims
from .digest import build_digest, render_html, render_terminal
from .extract import extract_claim
from .models import Digest, Narrative, Stage, StageTransition
from .prices import refresh_prices
from .score import score_narrative, update_stage
from .store import Store

logger = logging.getLogger(__name__)


@dataclass
class PipelineReport:
    sources_processed: int = 0
    new_narratives: int = 0
    transitions: list[StageTransition] = field(default_factory=list)
    digest: Optional[Digest] = None

    def summary(self) -> str:
        lines = [
            f"sources processed: {self.sources_processed}",
            f"new narratives:    {self.new_narratives}",
            f"stage transitions: {len(self.transitions)}",
        ]
        for t in self.transitions:
            lines.append(f"  · {t.from_stage} → {t.to_stage} (score {t.score:.1f})")
        return "\n".join(lines)


def run_pipeline(store: Store, *, today: datetime | None = None) -> PipelineReport:
    today = today or datetime.utcnow()
    report = PipelineReport()

    # Step 2 — extract (skip sources we've already extracted)
    new_claims = []
    for src in store.sources_iter():
        existing = next((c for c in store.claims.values() if c.source_id == src.source_id), None)
        if existing:
            continue
        claim = extract_claim(src)
        store.add_claim(claim)
        new_claims.append(claim)
        report.sources_processed += 1

    # Step 3 — cluster
    if new_claims:
        narratives, _assignments = cluster_claims(
            new_claims,
            sources_by_id=dict(store.sources),
            existing=list(store.active_narratives()),
        )
        existing_ids = set(store.narratives.keys())
        for n in narratives:
            store.upsert_narrative(n)
            if n.narrative_id not in existing_ids:
                report.new_narratives += 1

    # Step 4 — score & detect transitions
    sources = list(store.sources_iter())
    for n in store.active_narratives():
        score = score_narrative(n, sources, now=today)
        transition = update_stage(n, score=score, now=today)
        if transition:
            report.transitions.append(transition)

    # Step 5 — map alpha targets (only for narratives lacking targets, or newly
    # transitioned ones; keeps mapping deterministic across re-runs).
    transitioned_ids = {n.narrative_id for n in store.active_narratives()
                        if n.transitions and n.transitions[-1].at == today}
    for n in store.active_narratives():
        needs_mapping = (not n.alpha_targets) or n.narrative_id in transitioned_ids
        if not needs_mapping:
            # Just refresh prices on existing targets.
            refresh_prices(n.alpha_targets)
            continue
        claims_text = [
            store.claims[cid].thesis_summary for cid in n.claim_ids if cid in store.claims
        ][:8]
        mapping = map_alpha_targets(n, claims_text)
        attach_alpha_targets(n, mapping, now=today)
        refresh_prices(n.alpha_targets)

    # Step 6 — digest
    digest = build_digest(store, today=today.date())
    store.add_digest(digest)
    report.digest = digest
    return report


def render_digest_outputs(store: Store, digest: Digest) -> tuple[str, str]:
    """Convenience for the CLI: returns (terminal_text, html)."""
    return render_terminal(store, digest), render_html(store, digest)
