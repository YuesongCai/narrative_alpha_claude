"""Core data models for Narrative Alpha.

Every domain object — Source, Claim, AlphaTarget, Narrative, Digest — is defined
here as a dataclass. All persistence flows through `to_dict` / `from_dict` so the
JSON store stays straightforward and stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import IntEnum
from typing import Any, Optional


class Tier(IntEnum):
    """Source credibility tier — Section 4.2 of the PRD."""

    T1_PRIMARY_RESEARCH = 1
    T2_QUALITY_MEDIA = 2
    T3_SOCIAL_SELF_MEDIA = 3


# Stage strings are kept as plain strings (not enum) to make digest output trivial.
class Stage:
    EMERGING = "Emerging"
    STRENGTHENING = "Strengthening"
    CONSENSUS = "Consensus"

    ALL = (EMERGING, STRENGTHENING, CONSENSUS)

    @staticmethod
    def from_score(score: float) -> str:
        if score <= 35:
            return Stage.EMERGING
        if score <= 70:
            return Stage.STRENGTHENING
        return Stage.CONSENSUS

    @staticmethod
    def order_index(stage: str) -> int:
        # For ordering by alpha opportunity (Emerging first).
        return {Stage.EMERGING: 0, Stage.STRENGTHENING: 1, Stage.CONSENSUS: 2}.get(stage, 99)


def _iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return dt.isoformat()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


@dataclass
class Source:
    """A single piece of raw content (research note, article, tweet, etc.)."""

    source_id: str
    title: str
    org: str
    tier: int
    published_at: datetime
    body: str
    url: Optional[str] = None
    submitted_by: Optional[str] = None  # user id when manually submitted
    cites: list[str] = field(default_factory=list)  # ids of other sources cited

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = _iso(self.published_at)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Source":
        return cls(
            source_id=d["source_id"],
            title=d["title"],
            org=d["org"],
            tier=int(d["tier"]),
            published_at=_parse_dt(d["published_at"]) or datetime.utcnow(),
            body=d["body"],
            url=d.get("url"),
            submitted_by=d.get("submitted_by"),
            cites=list(d.get("cites") or []),
        )


@dataclass
class Claim:
    """A normalized assertion extracted from a Source."""

    claim_id: str
    source_id: str
    text: str
    thesis_summary: str
    entities: list[str] = field(default_factory=list)  # tickers, companies, sectors, technologies
    extracted_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["extracted_at"] = _iso(self.extracted_at)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Claim":
        return cls(
            claim_id=d["claim_id"],
            source_id=d["source_id"],
            text=d["text"],
            thesis_summary=d["thesis_summary"],
            entities=list(d.get("entities") or []),
            extracted_at=_parse_dt(d.get("extracted_at")) or datetime.utcnow(),
        )


@dataclass
class AlphaTarget:
    """An investable hypothesis derived from a narrative."""

    ticker: str
    name: str
    thesis: str
    mapped_at: datetime
    price_at_mapping: float
    current_price: float
    last_price_update: Optional[datetime] = None
    kind: str = "direct"  # direct | supply_chain | analogy | contrarian

    @property
    def price_change_pct(self) -> float:
        if not self.price_at_mapping:
            return 0.0
        return (self.current_price - self.price_at_mapping) / self.price_at_mapping * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "thesis": self.thesis,
            "mapped_at": _iso(self.mapped_at),
            "price_at_mapping": self.price_at_mapping,
            "current_price": self.current_price,
            "last_price_update": _iso(self.last_price_update),
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AlphaTarget":
        return cls(
            ticker=d["ticker"],
            name=d["name"],
            thesis=d["thesis"],
            mapped_at=_parse_dt(d["mapped_at"]) or datetime.utcnow(),
            price_at_mapping=float(d["price_at_mapping"]),
            current_price=float(d["current_price"]),
            last_price_update=_parse_dt(d.get("last_price_update")),
            kind=d.get("kind", "direct"),
        )


@dataclass
class StageTransition:
    """Audit log of a stage change, used for early-detection metrics."""

    from_stage: str
    to_stage: str
    at: datetime
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "at": _iso(self.at),
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StageTransition":
        return cls(
            from_stage=d["from_stage"],
            to_stage=d["to_stage"],
            at=_parse_dt(d["at"]) or datetime.utcnow(),
            score=float(d["score"]),
        )


@dataclass
class Narrative:
    """A clustered market narrative with full lifecycle state."""

    narrative_id: str
    title: str
    subtitle: str
    stage: str
    strength_score: float
    first_seen: datetime
    last_updated: datetime
    source_trail: list[str] = field(default_factory=list)  # source_ids, chronological
    claim_ids: list[str] = field(default_factory=list)
    alpha_targets: list[AlphaTarget] = field(default_factory=list)
    big_cap_signal: str = "None — no large-cap acknowledgment yet."
    key_question: str = ""
    centroid_terms: list[str] = field(default_factory=list)  # for clustering
    transitions: list[StageTransition] = field(default_factory=list)
    archived: bool = False

    def add_source(self, source_id: str) -> None:
        if source_id not in self.source_trail:
            self.source_trail.append(source_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "narrative_id": self.narrative_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "stage": self.stage,
            "strength_score": self.strength_score,
            "first_seen": _iso(self.first_seen),
            "last_updated": _iso(self.last_updated),
            "source_trail": list(self.source_trail),
            "claim_ids": list(self.claim_ids),
            "alpha_targets": [t.to_dict() for t in self.alpha_targets],
            "big_cap_signal": self.big_cap_signal,
            "key_question": self.key_question,
            "centroid_terms": list(self.centroid_terms),
            "transitions": [t.to_dict() for t in self.transitions],
            "archived": self.archived,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Narrative":
        return cls(
            narrative_id=d["narrative_id"],
            title=d["title"],
            subtitle=d["subtitle"],
            stage=d["stage"],
            strength_score=float(d["strength_score"]),
            first_seen=_parse_dt(d["first_seen"]) or datetime.utcnow(),
            last_updated=_parse_dt(d["last_updated"]) or datetime.utcnow(),
            source_trail=list(d.get("source_trail") or []),
            claim_ids=list(d.get("claim_ids") or []),
            alpha_targets=[AlphaTarget.from_dict(t) for t in (d.get("alpha_targets") or [])],
            big_cap_signal=d.get("big_cap_signal", ""),
            key_question=d.get("key_question", ""),
            centroid_terms=list(d.get("centroid_terms") or []),
            transitions=[StageTransition.from_dict(t) for t in (d.get("transitions") or [])],
            archived=bool(d.get("archived", False)),
        )


@dataclass
class Digest:
    """A daily digest snapshot."""

    digest_date: date
    counts: dict[str, int]
    highlight: str
    narrative_ids: list[str]  # ordered by alpha opportunity

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest_date": self.digest_date.isoformat(),
            "counts": dict(self.counts),
            "highlight": self.highlight,
            "narrative_ids": list(self.narrative_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Digest":
        return cls(
            digest_date=date.fromisoformat(d["digest_date"]),
            counts=dict(d.get("counts") or {}),
            highlight=d.get("highlight", ""),
            narrative_ids=list(d.get("narrative_ids") or []),
        )
