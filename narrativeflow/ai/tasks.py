"""High-level AI tasks called by the pipeline.

🤖 Each function is a single AI touchpoint. Every one of them has a
deterministic fallback so the pipeline runs to completion without an API key —
the fallback is conservative (rules-based filtering, lexical tagging, template
synthesis) and the digest will say "AI disabled" in a footer when used.

Each function returns a typed dict that the caller treats as gospel.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Optional

from .client import get_client
from .prompts import (
    NARRATIVE_MATCH_SYSTEM,
    NARRATIVE_SYNTHESIS_SYSTEM,
    NARRATIVE_TAGGING_SYSTEM,
    NOISE_FILTER_SYSTEM,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- noise
NOISE_KEYWORDS = (
    "sponsored", "advertisement", "promo code", "giveaway", "horoscope",
    "celebrity", "reality tv", "recipe", "weather forecast", "scoreboard",
)
INVESTABLE_KEYWORDS = (
    "earnings", "revenue", "guidance", "stock", "shares", "ipo", "acquisition",
    "merger", "valuation", "market", "fed", "rate", "inflation", "tariff",
    "ai", "chip", "semiconductor", "energy", "oil", "drug", "fda", "etf",
    "yield", "dollar", "yen", "treasury", "supply chain",
)


def classify_noise(*, title: str, body: str) -> dict:
    """🤖 Stage 2 — noise filter. Returns {is_noise, noise_score, reason}."""
    text = f"{title}\n{body}"
    payload = get_client().call_json(
        system=NOISE_FILTER_SYSTEM,
        user=text[:4000],
        max_tokens=200,
    )
    if isinstance(payload, dict) and "is_noise" in payload:
        return {
            "is_noise": bool(payload.get("is_noise")),
            "noise_score": float(payload.get("noise_score") or 0.0),
            "reason": str(payload.get("reason") or ""),
        }

    # ---- Heuristic fallback ----
    lowered = text.lower()
    if any(kw in lowered for kw in NOISE_KEYWORDS):
        return {"is_noise": True, "noise_score": 0.85, "reason": "matched noise keyword (heuristic)"}
    investable_hits = sum(1 for kw in INVESTABLE_KEYWORDS if kw in lowered)
    if investable_hits == 0 and len(text) < 80:
        return {"is_noise": True, "noise_score": 0.7, "reason": "very short, no markets terms (heuristic)"}
    if investable_hits == 0:
        return {"is_noise": True, "noise_score": 0.6, "reason": "no markets keywords (heuristic)"}
    return {"is_noise": False, "noise_score": 0.1, "reason": "passes investable keyword check (heuristic)"}


# ----------------------------------------------------------- tagging
def tag_to_narratives(
    *,
    title: str,
    body: str,
    candidate_narratives: list[dict],
) -> dict:
    """🤖 Stage 3 — match content to existing narratives.

    Returns:
        {
          "matches": [{"narrative_id": str, "relevance": float, "rationale": str}],
          "new_narrative": Optional[{"title": str, "one_liner": str}]
        }
    """
    excerpt = (title + "\n" + body)[:4000]
    candidate_block = "\n".join(
        f"{i}. {c['title']} — {c.get('one_liner','')}" for i, c in enumerate(candidate_narratives)
    ) or "(none)"

    payload = get_client().call_json(
        system=NARRATIVE_TAGGING_SYSTEM,
        user=f"CONTENT:\n{excerpt}\n\nCANDIDATE NARRATIVES:\n{candidate_block}",
        max_tokens=400,
    )
    if isinstance(payload, dict) and "matches" in payload:
        matches = []
        for m in payload.get("matches") or []:
            idx = m.get("narrative_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(candidate_narratives):
                continue
            relevance = float(m.get("relevance") or 0.0)
            if relevance < 0.55:
                continue
            matches.append({
                "narrative_id": candidate_narratives[idx]["id"],
                "relevance": relevance,
                "rationale": str(m.get("rationale") or ""),
            })
        new_nar = None
        if payload.get("is_new_narrative") and payload.get("suggested_title"):
            new_nar = {
                "title": str(payload["suggested_title"]).strip(),
                "one_liner": str(payload.get("suggested_one_liner") or "").strip(),
            }
        return {"matches": matches, "new_narrative": new_nar}

    # ---- Heuristic fallback: lexical token overlap with centroid_terms ----
    return _heuristic_tag(title, body, candidate_narratives)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", text or "") if len(t) > 2]


def _heuristic_tag(title: str, body: str, candidates: list[dict]) -> dict:
    tokens = set(_tokenize((title + " ") * 3 + body))
    matches: list[dict] = []
    for c in candidates:
        centroid = set(t.lower() for t in (c.get("centroid_terms") or []))
        title_terms = set(_tokenize(c.get("title", "")))
        target = (centroid | title_terms)
        if not target:
            continue
        overlap = len(tokens & target)
        if overlap < 3:
            continue
        relevance = min(0.95, 0.4 + 0.05 * overlap)
        matches.append({"narrative_id": c["id"], "relevance": relevance, "rationale": f"lexical overlap={overlap} (heuristic)"})

    matches.sort(key=lambda m: m["relevance"], reverse=True)
    matches = matches[:3]

    new_nar = None
    if not matches and len(tokens) >= 6:
        # Propose a new narrative from the title.
        new_nar = {"title": title[:80], "one_liner": title}
    return {"matches": matches, "new_narrative": new_nar}


# -------------------------------------------------------- synthesis
def synthesize_narrative(
    *,
    title: str,
    one_liner_hint: str,
    excerpts: list[dict],
) -> dict:
    """🤖 Stage 4 — produce the full Narrative Tracker.

    `excerpts` items: {"publisher": str, "date": str, "title": str, "body": str}.

    Returns the structured tracker dict (one_liner, causal_chain, ticker_map,
    catalysts, key_evidence, counter_narrative).
    """
    excerpt_block = "\n\n".join(
        f"[{i}] {e.get('publisher','')} · {e.get('date','')}\n  {e.get('title','')}\n  {e.get('body','')[:600]}"
        for i, e in enumerate(excerpts[:15])
    )
    user = f"NARRATIVE TITLE: {title}\nWORKING ONE-LINER: {one_liner_hint}\n\nEVIDENCE:\n{excerpt_block}"

    payload = get_client().call_json(
        system=NARRATIVE_SYNTHESIS_SYSTEM,
        user=user,
        model=get_client().settings.model_deep,
        max_tokens=1800,
    )
    if isinstance(payload, dict) and "one_liner" in payload:
        return _normalize_synthesis(payload)

    return _heuristic_synthesis(title=title, one_liner_hint=one_liner_hint, excerpts=excerpts)


def _normalize_synthesis(payload: dict) -> dict:
    tm = payload.get("ticker_map") or {}
    return {
        "one_liner": str(payload.get("one_liner") or "").strip(),
        "causal_chain": [str(s).strip() for s in (payload.get("causal_chain") or []) if str(s).strip()],
        "ticker_map": {
            "main_trade": list(tm.get("main_trade") or []),
            "second_derivative": list(tm.get("second_derivative") or []),
            "etf_proxy": list(tm.get("etf_proxy") or []),
            "hk_mirror": list(tm.get("hk_mirror") or []),
        },
        "catalysts": list(payload.get("catalysts") or []),
        "key_evidence": list(payload.get("key_evidence") or []),
        "counter_narrative": str(payload.get("counter_narrative") or "").strip(),
    }


# Tiny ticker fallback. Two-pass strategy: (1) prefer parenthetical / dollar-
# prefixed tickers like "(CRDO)" or "$TSLA"; (2) fall back to bare uppercase
# tokens, screened against a generous blocklist of common acronyms.
_PARENTHETICAL_TICKER_RE = re.compile(r"\(([A-Z]{1,5})\)|\$([A-Z]{1,5})\b")
_BARE_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")
_BLOCK = {
    # general acronyms / words
    "AI", "USA", "USD", "GDP", "CEO", "CFO", "CTO", "EPS", "ETF", "IPO",
    "EU", "UK", "US", "GMT", "PST", "EST", "AM", "PM", "TBA", "TBD",
    "FAQ", "NA", "PR", "TV", "IT", "OS", "API", "CPU", "GPU", "SDK",
    "SMR", "TAM", "WFE", "HBM", "PPA", "PPAS", "FT", "WSJ", "SEC", "FED",
    "VIP", "VPN", "URL", "HTML", "HTTP", "JSON", "XML", "USB",
    # lifecycle / org acronyms commonly mistaken for tickers
    "GLP", "DNA", "RNA", "FDA", "NRC", "DOE", "DOD",
    # currencies / jurisdictions
    "JPY", "EUR", "CNY", "HKD", "GBP", "RMB",
}


def _heuristic_synthesis(*, title: str, one_liner_hint: str, excerpts: list[dict]) -> dict:
    text = " ".join(e.get("body", "") + " " + e.get("title", "") for e in excerpts)

    # Pass 1: explicit ticker syntax wins.
    paren = [t for pair in _PARENTHETICAL_TICKER_RE.findall(text) for t in pair if t and t not in _BLOCK]
    counts: Counter[str] = Counter(paren)

    # Pass 2: only fall back to bare uppercase if pass 1 is empty.
    if not counts:
        for t in _BARE_TICKER_RE.findall(text):
            if t in _BLOCK or len(t) < 3:
                continue
            counts[t] += 1

    main = [{"ticker": t, "name": t, "thesis": "Surfaced across multiple sources."} for t, _ in counts.most_common(3)]

    causal = [
        f"Multiple sources independently surface the {title.lower()} thesis.",
        "Cross-source convergence raises the probability the thesis becomes consensus.",
        "Liquidity and positioning shift toward the named beneficiaries.",
    ]
    evidence = [
        {"claim": (e.get("title") or "")[:200], "source_index": i, "date": e.get("date", "")}
        for i, e in enumerate(excerpts[:5])
    ]
    return {
        "one_liner": one_liner_hint or title,
        "causal_chain": causal,
        "ticker_map": {"main_trade": main, "second_derivative": [], "etf_proxy": [], "hk_mirror": []},
        "catalysts": [],
        "key_evidence": evidence,
        "counter_narrative": "AI disabled — counter-narrative not generated. Requires manual review.",
    }


# ---------------------------------------------------- NL search match
def match_query_to_narrative(*, query: str, candidates: list[dict]) -> dict:
    """🤖 NL search — pick the best narrative for a user's natural-language query."""
    candidate_block = "\n".join(
        f"{i}. {c['title']} — {c.get('one_liner','')}" for i, c in enumerate(candidates)
    )
    payload = get_client().call_json(
        system=NARRATIVE_MATCH_SYSTEM,
        user=f"QUERY: {query}\n\nCANDIDATES:\n{candidate_block}",
        max_tokens=200,
    )
    if isinstance(payload, dict):
        idx = payload.get("best_match_index")
        match_id: Optional[str] = None
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            match_id = candidates[idx]["id"]
        return {
            "match_id": match_id,
            "confidence": float(payload.get("confidence") or 0.0),
            "should_create_new": bool(payload.get("should_create_new", False)),
            "suggested_title": str(payload.get("suggested_title") or "").strip() or None,
        }

    # Heuristic: simple substring + token overlap.
    q_tokens = set(_tokenize(query))
    best, best_score = None, 0
    for c in candidates:
        score = 0
        if query.lower() in c["title"].lower():
            score += 5
        score += len(q_tokens & set(_tokenize(c["title"]))) * 2
        score += len(q_tokens & set(t.lower() for t in (c.get("centroid_terms") or [])))
        if score > best_score:
            best, best_score = c, score
    if best:
        return {"match_id": best["id"], "confidence": min(0.9, 0.3 + 0.1 * best_score),
                "should_create_new": False, "suggested_title": None}
    return {"match_id": None, "confidence": 0.0, "should_create_new": True, "suggested_title": query}
