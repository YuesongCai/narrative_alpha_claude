"""Alpha-target identification.

Section 5.1 lists four kinds of mapping: direct mentions, supply-chain
mapping, analogy targets, contrarian targets. With an LLM available we ask it
to do the full map and return JSON. Without one, we fall back to a hand-curated
playbook (`PLAYBOOK`) keyed by narrative fingerprint terms; it produces real,
defensible mappings for the example narratives in the PRD and gracefully
returns nothing for narratives outside its catalogue (rather than fabricating).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .llm import call_json
from .models import AlphaTarget, Narrative, Source
from .prices import current_price


_ALPHA_SYSTEM_PROMPT = """You are an equity strategist mapping investable targets to a market narrative.

Given the narrative thesis and supporting source claims, produce 3 to 5 alpha targets.
For each target, classify the mapping kind as one of:
  "direct"        — explicitly named beneficiary in the source material
  "supply_chain"  — upstream / downstream enabler (e.g. silicon, fab tools, power)
  "analogy"       — similar exposure in adjacent sector or geography
  "contrarian"    — currently out of favor but re-rates if the narrative is correct

Avoid mega-cap bellwethers (Mag7, TSMC, big banks) — they belong in `big_cap_signal`,
not in `alpha_targets`, because by the time they move the alpha window is closed.

Return JSON with this exact shape:
{
  "alpha_targets": [
    {"ticker": "<symbol>", "name": "<company>", "thesis": "<1-sentence connection to the narrative>", "kind": "direct|supply_chain|analogy|contrarian"}
  ],
  "big_cap_signal": "<one sentence describing whether/how large-caps have acknowledged it>",
  "key_question": "<the critical unresolved question that determines staying power>"
}

Output ONLY the JSON object.
"""


# Hand-curated fallback so the system produces meaningful output offline. Keys
# are sets of fingerprint terms; first match wins. New playbook entries should
# land here as the curator validates them.
PLAYBOOK: list[dict] = [
    {
        "fingerprint": {"inference", "ai", "deflation", "cost"},
        "alpha_targets": [
            {"ticker": "CRDO", "name": "Credo Technology", "kind": "supply_chain",
             "thesis": "Active electrical cables become the dominant inside-rack interconnect as inference clusters scale out."},
            {"ticker": "ANET", "name": "Arista Networks", "kind": "supply_chain",
             "thesis": "East-west datacenter traffic explodes with multi-tenant inference; Arista's leaf-spine fabric is the standard."},
            {"ticker": "AMD", "name": "AMD", "kind": "direct",
             "thesis": "MI-series GPUs benefit disproportionately as customers diversify away from a single inference provider."},
        ],
        "big_cap_signal": "NVDA management has not yet framed the inference-cost-deflation thesis explicitly on earnings.",
        "key_question": "Does inference unit economics improve fast enough to expand TAM, or does deflation simply compress margins?",
    },
    {
        "fingerprint": {"japan", "reindustrialization", "fab", "semiconductor"},
        "alpha_targets": [
            {"ticker": "8035.T", "name": "Tokyo Electron", "kind": "direct",
             "thesis": "Largest beneficiary of new fab capacity coming online across Kyushu and Hokkaido."},
            {"ticker": "6857.T", "name": "Advantest", "kind": "supply_chain",
             "thesis": "Test capacity is the bottleneck for advanced packaging; Advantest holds high-end share."},
            {"ticker": "4063.T", "name": "Shin-Etsu Chemical", "kind": "supply_chain",
             "thesis": "Wafer demand reaccelerates as new Japanese fabs ramp."},
        ],
        "big_cap_signal": "TSMC has acknowledged Japan expansion on earnings — late-cycle confirmation, not early signal.",
        "key_question": "Does Japan's labor and energy cost structure make these fabs structurally competitive vs. Taiwan?",
    },
    {
        "fingerprint": {"nuclear", "renaissance", "smr", "power"},
        "alpha_targets": [
            {"ticker": "BWXT", "name": "BWX Technologies", "kind": "direct",
             "thesis": "Sole US manufacturer of naval-grade reactor components, leveraged to SMR commercialization."},
            {"ticker": "CCJ", "name": "Cameco", "kind": "supply_chain",
             "thesis": "Uranium fuel-cycle leader benefits from any sustained ramp in reactor count."},
            {"ticker": "VST", "name": "Vistra Energy", "kind": "direct",
             "thesis": "Owns operating nuclear capacity that is suddenly the scarcest asset class on the grid."},
        ],
        "big_cap_signal": "Hyperscaler PPAs (Amazon, Microsoft, Meta) have begun referencing nuclear directly — narrative is mid-lifecycle.",
        "key_question": "Can SMR commercial timelines actually compress to 2028, or do regulators slip them to the 2030s?",
    },
    {
        "fingerprint": {"obesity", "glp", "drug", "diabetes"},
        "alpha_targets": [
            {"ticker": "VKTX", "name": "Viking Therapeutics", "kind": "direct",
             "thesis": "Phase 2 dual-agonist data positions VK2735 as a credible third entrant if Eli Lilly / Novo can't supply."},
            {"ticker": "WGS", "name": "GeneDx", "kind": "analogy",
             "thesis": "Pharmacogenomics demand rises as polypharmacy with GLP-1s creates downstream interaction risk."},
        ],
        "big_cap_signal": "LLY and NVO have been priced for the narrative for 18 months; alpha has rotated to second-tier challengers.",
        "key_question": "Do oral GLP-1 formulations actually arrive in 2026 and compress injectable pricing power?",
    },
]


def map_alpha_targets(narrative: Narrative, claims_text: list[str]) -> dict:
    """Produce the alpha-target package for a narrative.

    Returns a dict with `alpha_targets` (list[dict]), `big_cap_signal`, and
    `key_question`. The pipeline calls this and merges it into the narrative.
    """
    payload = call_json(
        system=_ALPHA_SYSTEM_PROMPT,
        user=_render_prompt(narrative, claims_text),
        max_tokens=900,
    )
    if isinstance(payload, dict) and payload.get("alpha_targets"):
        return _normalize(payload)

    return _playbook_lookup(narrative, claims_text)


def _render_prompt(narrative: Narrative, claims_text: list[str]) -> str:
    body = "\n- ".join(claims_text[:8])
    return (
        f"NARRATIVE TITLE: {narrative.title}\n"
        f"THESIS: {narrative.subtitle}\n"
        f"CENTROID TERMS: {', '.join(narrative.centroid_terms[:15])}\n"
        f"CLAIMS:\n- {body}"
    )


def _normalize(payload: dict) -> dict:
    targets = []
    for t in payload.get("alpha_targets") or []:
        if not t.get("ticker") or not t.get("thesis"):
            continue
        targets.append({
            "ticker": str(t["ticker"]).strip().upper().replace(" ", ""),
            "name": str(t.get("name") or t["ticker"]).strip(),
            "thesis": str(t["thesis"]).strip(),
            "kind": str(t.get("kind") or "direct").strip(),
        })
    return {
        "alpha_targets": targets,
        "big_cap_signal": str(payload.get("big_cap_signal") or "").strip()
        or "No large-cap acknowledgment yet.",
        "key_question": str(payload.get("key_question") or "").strip()
        or "Does this thesis survive a quarter of contradicting evidence?",
    }


def _playbook_lookup(narrative: Narrative, claims_text: list[str]) -> dict:
    haystack = " ".join([
        narrative.title,
        narrative.subtitle,
        " ".join(narrative.centroid_terms),
        " ".join(claims_text),
    ]).lower()

    # Pick the fingerprint with the highest fraction of matching terms,
    # subject to a minimum quality bar of 2 hits and >=50% of the fingerprint.
    best: tuple[float, dict] | None = None
    for entry in PLAYBOOK:
        fp = entry["fingerprint"]
        hits = sum(1 for term in fp if term in haystack)
        if hits < 2 or hits / len(fp) < 0.5:
            continue
        score = hits / len(fp)
        if best is None or score > best[0]:
            best = (score, entry)

    if best is not None:
        entry = best[1]
        return {
            "alpha_targets": [dict(t) for t in entry["alpha_targets"]],
            "big_cap_signal": entry["big_cap_signal"],
            "key_question": entry["key_question"],
        }

    return {
        "alpha_targets": [],
        "big_cap_signal": "No large-cap acknowledgment yet.",
        "key_question": "Pending curator review for alpha mapping.",
    }


# ------------------------------------------------------------- merging
def attach_alpha_targets(narrative: Narrative, mapping: dict, *, now: datetime | None = None) -> list[AlphaTarget]:
    """Merge a fresh mapping into a narrative without losing existing price history.

    A target already on the narrative keeps its `price_at_mapping` and `mapped_at`;
    only thesis / kind get refreshed. New tickers are added with the current price
    snapshotted as the entry point.
    """
    now = now or datetime.utcnow()
    by_ticker = {t.ticker: t for t in narrative.alpha_targets}
    fresh: list[AlphaTarget] = []

    for entry in mapping.get("alpha_targets") or []:
        ticker = entry["ticker"]
        existing = by_ticker.get(ticker)
        if existing is not None:
            existing.thesis = entry["thesis"]
            existing.kind = entry.get("kind", existing.kind)
            fresh.append(existing)
            continue
        price = current_price(ticker)
        target = AlphaTarget(
            ticker=ticker,
            name=entry.get("name", ticker),
            thesis=entry["thesis"],
            mapped_at=now,
            price_at_mapping=price,
            current_price=price,
            last_price_update=now,
            kind=entry.get("kind", "direct"),
        )
        fresh.append(target)

    narrative.alpha_targets = fresh
    narrative.big_cap_signal = mapping.get("big_cap_signal", narrative.big_cap_signal)
    narrative.key_question = mapping.get("key_question", narrative.key_question)
    return fresh
