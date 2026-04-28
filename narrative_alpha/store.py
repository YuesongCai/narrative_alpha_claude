"""JSON-backed persistence.

A single JSON document under `<data_dir>/state.json` holds the entire pipeline
state: sources, claims, narratives, and digests. This keeps V1 trivially
inspectable and diffable. We can swap in SQLite/Postgres later without changing
call sites — every consumer goes through the Store API.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Iterable

from .models import Claim, Digest, Narrative, Source


DEFAULT_DATA_DIR = Path(os.environ.get("NARRATIVE_ALPHA_DATA", "./data"))
STATE_FILENAME = "state.json"


class Store:
    """In-memory state with atomic JSON persistence."""

    def __init__(self, data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / STATE_FILENAME

        self.sources: dict[str, Source] = {}
        self.claims: dict[str, Claim] = {}
        self.narratives: dict[str, Narrative] = {}
        self.digests: dict[str, Digest] = {}  # keyed by ISO date

        self._loaded = False

    # ---------------------------------------------------------------- I/O
    def load(self) -> "Store":
        if self.state_path.exists():
            with self.state_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            self.sources = {sid: Source.from_dict(s) for sid, s in (raw.get("sources") or {}).items()}
            self.claims = {cid: Claim.from_dict(c) for cid, c in (raw.get("claims") or {}).items()}
            self.narratives = {nid: Narrative.from_dict(n) for nid, n in (raw.get("narratives") or {}).items()}
            self.digests = {d: Digest.from_dict(v) for d, v in (raw.get("digests") or {}).items()}
        self._loaded = True
        return self

    def save(self) -> None:
        payload = {
            "sources": {sid: s.to_dict() for sid, s in self.sources.items()},
            "claims": {cid: c.to_dict() for cid, c in self.claims.items()},
            "narratives": {nid: n.to_dict() for nid, n in self.narratives.items()},
            "digests": {d: v.to_dict() for d, v in self.digests.items()},
        }
        # Atomic write — never leave a half-written state file.
        fd, tmp_path = tempfile.mkstemp(prefix="state.", suffix=".json", dir=str(self.data_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.state_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # ----------------------------------------------------------- mutators
    def add_source(self, source: Source) -> bool:
        """Returns True if newly added, False if already present (deduped by id)."""
        if source.source_id in self.sources:
            return False
        self.sources[source.source_id] = source
        return True

    def add_claim(self, claim: Claim) -> None:
        self.claims[claim.claim_id] = claim

    def upsert_narrative(self, narrative: Narrative) -> None:
        self.narratives[narrative.narrative_id] = narrative

    def add_digest(self, digest: Digest) -> None:
        self.digests[digest.digest_date.isoformat()] = digest

    # ------------------------------------------------------------ queries
    def active_narratives(self) -> list[Narrative]:
        return [n for n in self.narratives.values() if not n.archived]

    def latest_digest(self) -> Digest | None:
        if not self.digests:
            return None
        latest_key = max(self.digests.keys())
        return self.digests[latest_key]

    def get_digest(self, d: date) -> Digest | None:
        return self.digests.get(d.isoformat())

    def claims_for_narrative(self, narrative_id: str) -> list[Claim]:
        n = self.narratives.get(narrative_id)
        if not n:
            return []
        return [self.claims[c] for c in n.claim_ids if c in self.claims]

    def sources_for_narrative(self, narrative_id: str) -> list[Source]:
        n = self.narratives.get(narrative_id)
        if not n:
            return []
        return [self.sources[s] for s in n.source_trail if s in self.sources]

    def sources_iter(self) -> Iterable[Source]:
        return self.sources.values()
