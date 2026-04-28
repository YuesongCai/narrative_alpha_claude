"""Validation framework — Section 5.2.

Builds the system's track record. The two metrics that matter for V1:

  * narrative_hit_rate  — % of Emerging narratives that progress to Strengthening
                          with alpha targets showing positive price action.
  * average_alpha       — mean price move on validated targets.

These feed both the success-metrics readout and the digest's calibration line.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable

from .models import Narrative, Stage


@dataclass
class TrackRecord:
    flagged_emerging: int = 0
    progressed_to_strengthening: int = 0
    progressed_to_consensus: int = 0
    hit_rate_pct: float = 0.0
    average_alpha_pct: float = 0.0
    average_days_to_strengthening: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def compute_track_record(narratives: Iterable[Narrative]) -> TrackRecord:
    flagged = 0
    progressed = 0
    consensus = 0
    days_list: list[float] = []
    alpha_pct_list: list[float] = []

    for n in narratives:
        if not n.transitions and n.stage == Stage.EMERGING and not n.archived:
            flagged += 1
            continue
        # Any narrative we have ever seen at Emerging is in the denominator.
        was_emerging = (
            n.stage == Stage.EMERGING
            or any(t.from_stage == Stage.EMERGING for t in n.transitions)
        )
        if not was_emerging:
            continue
        flagged += 1

        # Find the first transition out of Emerging.
        out = next((t for t in n.transitions if t.from_stage == Stage.EMERGING), None)
        if out:
            progressed += 1
            days = (out.at - n.first_seen).total_seconds() / 86400.0
            if days >= 0:
                days_list.append(days)
            if out.to_stage == Stage.CONSENSUS:
                consensus += 1
            # Alpha capture only counts targets with positive moves.
            for t in n.alpha_targets:
                if t.price_change_pct > 0:
                    alpha_pct_list.append(t.price_change_pct)

    rec = TrackRecord(
        flagged_emerging=flagged,
        progressed_to_strengthening=progressed,
        progressed_to_consensus=consensus,
    )
    if flagged:
        rec.hit_rate_pct = round(progressed / flagged * 100.0, 1)
    if alpha_pct_list:
        rec.average_alpha_pct = round(sum(alpha_pct_list) / len(alpha_pct_list), 2)
    if days_list:
        rec.average_days_to_strengthening = round(sum(days_list) / len(days_list), 1)
    return rec
