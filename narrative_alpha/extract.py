"""Claim extraction.

Each Source produces one Claim — a normalized, deduplicable assertion that
clustering can group into narratives. With an LLM available we use it. Without
one, we fall back to a deterministic heuristic that pulls the strongest
sentence + pattern-matched entities; the system stays usable end-to-end.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .llm import call_json
from .models import Claim, Source


_EXTRACTION_SYSTEM_PROMPT = """You are an analyst on a markets-research desk.
Read the article excerpt and extract its **single most important investable thesis**.

Return JSON with this exact shape:
{
  "thesis_summary": "<one declarative sentence stating the thesis the source advances>",
  "key_quote": "<the strongest single sentence from the source that supports the thesis>",
  "entities": ["<ticker, company, sector, technology, or geography mentioned as central to the thesis>", ...]
}

Rules:
- thesis_summary: forward-looking, declarative, in the third person. No hedging.
- key_quote: verbatim from the source if possible.
- entities: 3 to 8 items, prefer tickers when known (e.g. "NVDA"), otherwise canonical names.
- Output ONLY the JSON object, no preamble.
"""


# Pattern catalogues used by the heuristic fallback. They are deliberately
# narrow — false positives here pollute downstream clustering.
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")
_KNOWN_TICKERS = {
    "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "NVDA", "TSLA", "AVGO",
    "AMD", "INTC", "CRDO", "ANET", "ASML", "TSM", "AMAT", "LRCX", "KLAC",
    "VST", "CEG", "NEE", "BWXT", "CCJ", "NKE", "MCD",
    "8035", "8036", "6857", "4063",  # Tokyo Electron, Hitachi High-Tech, Advantest, Shin-Etsu
}
_KEYWORDS = (
    "AI", "inference", "training", "GPU", "datacenter", "data center",
    "semiconductor", "fab", "wafer", "lithography", "memory", "HBM",
    "nuclear", "SMR", "reactor", "power", "grid", "energy",
    "Japan", "Korea", "China", "Taiwan",
    "robotics", "humanoid", "autonomy",
    "obesity", "GLP-1", "biotech",
    "supply chain", "tariff", "reshoring", "onshoring",
    "connectivity", "networking", "optical", "interconnect",
    "consumer", "demand", "deflation", "inflation",
)


def _heuristic_entities(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    for match in _TICKER_RE.findall(text):
        if match in _KNOWN_TICKERS and match not in seen:
            found.append(match)
            seen.add(match)

    lowered = text.lower()
    for kw in _KEYWORDS:
        if kw.lower() in lowered:
            key = kw.title() if not kw.isupper() else kw
            if key not in seen:
                found.append(key)
                seen.add(key)

    return found[:8]


def _strongest_sentence(text: str) -> str:
    """Pick the longest sentence that contains a keyword or ticker, capped."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return text[:240]
    scored = []
    for s in sentences:
        score = len(s)
        if any(t in s for t in _KNOWN_TICKERS):
            score += 80
        if any(kw.lower() in s.lower() for kw in _KEYWORDS):
            score += 40
        scored.append((score, s))
    scored.sort(reverse=True)
    return scored[0][1][:400]


def _claim_id(source_id: str) -> str:
    return "clm_" + hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:12]


def extract_claim(source: Source) -> Claim:
    """Convert a Source into a Claim. Tries the LLM first, falls back to rules."""
    payload = call_json(
        system=_EXTRACTION_SYSTEM_PROMPT,
        user=f"TITLE: {source.title}\nPUBLISHER: {source.org}\nBODY:\n{source.body}",
        max_tokens=512,
    )
    if isinstance(payload, dict) and payload.get("thesis_summary"):
        thesis = str(payload.get("thesis_summary", "")).strip()
        quote = str(payload.get("key_quote") or "").strip()
        entities = [str(e).strip() for e in (payload.get("entities") or []) if str(e).strip()]
    else:
        thesis = source.title.rstrip(".") + "."
        quote = _strongest_sentence(source.body or source.title)
        entities = _heuristic_entities(f"{source.title}\n{source.body}")

    return Claim(
        claim_id=_claim_id(source.source_id),
        source_id=source.source_id,
        text=quote or source.title,
        thesis_summary=thesis,
        entities=entities,
        extracted_at=datetime.utcnow(),
    )
