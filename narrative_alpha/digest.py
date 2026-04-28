"""Daily digest — both rendered HTML and a terminal printout.

The PRD specifies card ordering by alpha opportunity (Emerging first), within
stage by recency. The renderer also computes the daily counts and highlight
sentence. The HTML template is a single self-contained file so it can be
emailed without external CSS.
"""

from __future__ import annotations

import html as _html
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from . import __version__
from .models import AlphaTarget, Digest, Narrative, Source, Stage
from .store import Store
from .tiers import tier_label
from .validate import compute_track_record


TEMPLATE_PATH = Path(__file__).parent / "templates" / "digest.html"


# --------------------------------------------------------------- ordering
def order_for_digest(narratives: list[Narrative]) -> list[Narrative]:
    """Emerging first, then Strengthening, then Consensus.
    Within stage, most recently updated first.
    """
    return sorted(
        [n for n in narratives if not n.archived],
        key=lambda n: (Stage.order_index(n.stage), -n.last_updated.timestamp()),
    )


def build_digest(store: Store, *, today: date | None = None) -> Digest:
    today = today or datetime.utcnow().date()
    narratives = order_for_digest(store.active_narratives())
    counts = {
        "emerging": sum(1 for n in narratives if n.stage == Stage.EMERGING),
        "strengthening": sum(1 for n in narratives if n.stage == Stage.STRENGTHENING),
        "consensus": sum(1 for n in narratives if n.stage == Stage.CONSENSUS),
        "new_today": sum(1 for n in narratives if n.first_seen.date() == today),
    }
    digest = Digest(
        digest_date=today,
        counts=counts,
        highlight=_pick_highlight(narratives, today),
        narrative_ids=[n.narrative_id for n in narratives],
    )
    return digest


def _pick_highlight(narratives: list[Narrative], today: date) -> str:
    if not narratives:
        return "No active narratives in the system yet."

    # Prefer a stage transition that happened today.
    for n in narratives:
        if n.transitions and n.transitions[-1].at.date() == today:
            t = n.transitions[-1]
            return f"“{n.title}” crossed from {t.from_stage} → {t.to_stage} today."

    # Else: a brand-new emerging narrative.
    new_today = [n for n in narratives if n.first_seen.date() == today and n.stage == Stage.EMERGING]
    if new_today:
        n = new_today[0]
        return f"New emerging narrative: “{n.title}” — {n.subtitle}"

    # Else: strongest narrative still in Strengthening.
    strengthening = [n for n in narratives if n.stage == Stage.STRENGTHENING]
    if strengthening:
        n = max(strengthening, key=lambda x: x.strength_score)
        return f"“{n.title}” at {n.strength_score:.0f} strength — watch for a Consensus crossover."

    n = narratives[0]
    return f"Most active narrative today: “{n.title}” ({n.stage})."


# ---------------------------------------------------------------- HTML
def render_html(store: Store, digest: Digest) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    cards_html = _render_all_cards(store, digest)
    track = compute_track_record(store.active_narratives())

    counts = {
        "emerging": digest.counts.get("emerging", 0),
        "strengthening": digest.counts.get("strengthening", 0),
        "consensus": digest.counts.get("consensus", 0),
        "new_today": digest.counts.get("new_today", 0),
    }
    return (
        template
        .replace("{{ digest.digest_date }}", digest.digest_date.isoformat())
        .replace("{{ digest.counts.emerging }}", str(counts["emerging"]))
        .replace("{{ digest.counts.strengthening }}", str(counts["strengthening"]))
        .replace("{{ digest.counts.consensus }}", str(counts["consensus"]))
        .replace("{{ digest.counts.new_today }}", str(counts["new_today"]))
        .replace("{{ digest.highlight }}", _html.escape(digest.highlight))
        .replace("{{ cards_html }}", cards_html)
        .replace("{{ track.hit_rate_pct }}", f"{track.hit_rate_pct:.0f}")
        .replace("{{ track.average_alpha_pct }}", f"{track.average_alpha_pct:.1f}")
        .replace("{{ version }}", __version__)
    )


def _render_all_cards(store: Store, digest: Digest) -> str:
    return "\n".join(
        _render_card(store.narratives[nid], store)
        for nid in digest.narrative_ids
        if nid in store.narratives
    )


def _render_card(n: Narrative, store: Store) -> str:
    stage_class = n.stage.lower()
    dots = _stage_dots(n.stage)
    score_pct = max(0, min(100, int(round(n.strength_score))))

    sources_html = _render_sources(store.sources_for_narrative(n.narrative_id))
    targets_html = _render_targets(n.alpha_targets)

    return f"""
<div class="card">
  <div class="title-row">
    <h2>{_html.escape(n.title)}</h2>
    <span class="badge {stage_class}">{n.stage}<span class="stage-dots">{dots}</span></span>
  </div>
  <div class="subtitle">{_html.escape(n.subtitle)}</div>
  <div class="score-bar"><div style="width: {score_pct}%"></div></div>

  <details>
    <summary>{len(n.source_trail)} source{'s' if len(n.source_trail)!=1 else ''} · strength {n.strength_score:.0f}/100</summary>
    {sources_html}
  </details>

  <div class="section-label">Alpha targets</div>
  <div class="targets">{targets_html or '<div class="big-cap">No mapping yet — pending curator review.</div>'}</div>

  <div class="section-label">Big-cap signal</div>
  <div class="big-cap">{_html.escape(n.big_cap_signal)}</div>

  <div class="section-label">Key question</div>
  <div class="key-q">{_html.escape(n.key_question)}</div>
</div>
""".strip()


def _stage_dots(stage: str) -> str:
    if stage == Stage.EMERGING:
        return "●○○"
    if stage == Stage.STRENGTHENING:
        return "●●○"
    return "●●●"


def _render_sources(sources: Iterable[Source]) -> str:
    rows: list[str] = []
    for s in sorted(sources, key=lambda x: x.published_at):
        tier_cls = f"t{s.tier}"
        when = s.published_at.strftime("%b %d, %Y")
        link = f' → <a href="{_html.escape(s.url)}" style="color:#7dd3fc">link</a>' if s.url else ""
        rows.append(
            f'<div class="source">'
            f'<span class="tier {tier_cls}">{_html.escape(tier_label(s.tier))}</span>'
            f'<span>{_html.escape(s.org)} · {_html.escape(s.title)}{link}</span>'
            f'<span class="when">{when}</span>'
            f"</div>"
        )
    return "\n".join(rows)


def _render_targets(targets: Iterable[AlphaTarget]) -> str:
    rows: list[str] = []
    for t in targets:
        pct = t.price_change_pct
        cls = "up" if pct > 0.5 else "down" if pct < -0.5 else "flat"
        sign = "+" if pct >= 0 else ""
        rows.append(
            f'<div class="target">'
            f'  <div class="row1">'
            f'    <span><span class="ticker">{_html.escape(t.ticker)}</span> '
            f'<span class="kind">{_html.escape(t.kind)}</span> — {_html.escape(t.name)}</span>'
            f'    <span class="pct {cls}">{sign}{pct:.1f}%</span>'
            f"  </div>"
            f'  <div class="thesis">{_html.escape(t.thesis)}</div>'
            f"</div>"
        )
    return "\n".join(rows)


# -------------------------------------------------------------- terminal
def render_terminal(store: Store, digest: Digest) -> str:
    """Plain-text rendering for shell output. No ANSI colors so it pipes cleanly."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"NARRATIVE ALPHA  —  {digest.digest_date}  —  daily digest")
    lines.append("=" * 78)
    c = digest.counts
    lines.append(
        f"{c.get('emerging',0)} emerging  ·  {c.get('strengthening',0)} strengthening  "
        f"·  {c.get('consensus',0)} consensus  ·  {c.get('new_today',0)} new today"
    )
    lines.append("")
    lines.append(f"  → {digest.highlight}")
    lines.append("")

    for nid in digest.narrative_ids:
        n = store.narratives.get(nid)
        if not n:
            continue
        lines.append("-" * 78)
        lines.append(f"[{n.stage.upper():13s}] {n.title}")
        lines.append(f"               {n.subtitle}")
        lines.append(
            f"               strength {n.strength_score:5.1f} / 100   "
            f"sources {len(n.source_trail):2d}   "
            f"first seen {n.first_seen.date()}"
        )

        lines.append("  Source trail:")
        for s in sorted(store.sources_for_narrative(nid), key=lambda x: x.published_at):
            lines.append(
                f"    [T{s.tier}] {s.published_at.date()}  {s.org:24.24}  {s.title}"
            )

        if n.alpha_targets:
            lines.append("  Alpha targets:")
            for t in n.alpha_targets:
                pct = t.price_change_pct
                sign = "+" if pct >= 0 else ""
                lines.append(
                    f"    {t.ticker:7s} {t.kind:13s}  {sign}{pct:5.1f}%   {t.thesis}"
                )
        else:
            lines.append("  Alpha targets: (pending curator review)")

        lines.append(f"  Big-cap signal: {n.big_cap_signal}")
        lines.append(f"  Key question:   {n.key_question}")
        lines.append("")

    track = compute_track_record(store.active_narratives())
    lines.append("-" * 78)
    lines.append(
        f"Track record · hit rate {track.hit_rate_pct:.0f}%  "
        f"·  avg alpha {track.average_alpha_pct:.1f}%  "
        f"·  avg days to strengthening {track.average_days_to_strengthening:.1f}"
    )
    return "\n".join(lines)
