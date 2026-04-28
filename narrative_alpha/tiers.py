"""Tier classification — Section 4.2 of the PRD.

The tier system is the product's moat. Mis-classification corrupts every
downstream signal (strength score, stage, digest ordering), so the rules here
are intentionally conservative: unknown publishers default to Tier 3 and a
warning, never silently to Tier 1.
"""

from __future__ import annotations

from .models import Tier

# Canonical registry. Keys are normalized (lowercase) publisher / origin slugs.
# Each entry maps to a tier. Add to this when a new source is whitelisted.
TIER_REGISTRY: dict[str, int] = {
    # ---------- Tier 1: Primary Research ----------
    "goldman sachs": Tier.T1_PRIMARY_RESEARCH,
    "morgan stanley": Tier.T1_PRIMARY_RESEARCH,
    "jpmorgan": Tier.T1_PRIMARY_RESEARCH,
    "jp morgan": Tier.T1_PRIMARY_RESEARCH,
    "bernstein": Tier.T1_PRIMARY_RESEARCH,
    "redburn": Tier.T1_PRIMARY_RESEARCH,
    "evercore isi": Tier.T1_PRIMARY_RESEARCH,
    "ubs research": Tier.T1_PRIMARY_RESEARCH,
    "barclays research": Tier.T1_PRIMARY_RESEARCH,
    "citi research": Tier.T1_PRIMARY_RESEARCH,
    "bofa global research": Tier.T1_PRIMARY_RESEARCH,
    "wells fargo research": Tier.T1_PRIMARY_RESEARCH,
    "raymond james": Tier.T1_PRIMARY_RESEARCH,
    "rosenblatt": Tier.T1_PRIMARY_RESEARCH,
    "ihs markit": Tier.T1_PRIMARY_RESEARCH,
    "trendforce": Tier.T1_PRIMARY_RESEARCH,
    "gartner": Tier.T1_PRIMARY_RESEARCH,
    "idc": Tier.T1_PRIMARY_RESEARCH,
    "company filing": Tier.T1_PRIMARY_RESEARCH,
    "earnings call": Tier.T1_PRIMARY_RESEARCH,
    "factset transcript": Tier.T1_PRIMARY_RESEARCH,
    "industry expert": Tier.T1_PRIMARY_RESEARCH,
    "expert network": Tier.T1_PRIMARY_RESEARCH,
    # ---------- Tier 2: Quality Media ----------
    "financial times": Tier.T2_QUALITY_MEDIA,
    "ft.com": Tier.T2_QUALITY_MEDIA,
    "bloomberg": Tier.T2_QUALITY_MEDIA,
    "wsj": Tier.T2_QUALITY_MEDIA,
    "wall street journal": Tier.T2_QUALITY_MEDIA,
    "the economist": Tier.T2_QUALITY_MEDIA,
    "nikkei": Tier.T2_QUALITY_MEDIA,
    "nikkei asia": Tier.T2_QUALITY_MEDIA,
    "the information": Tier.T2_QUALITY_MEDIA,
    "barron's": Tier.T2_QUALITY_MEDIA,
    "barrons": Tier.T2_QUALITY_MEDIA,
    "reuters": Tier.T2_QUALITY_MEDIA,
    "axios": Tier.T2_QUALITY_MEDIA,
    "stratechery": Tier.T2_QUALITY_MEDIA,
    "semianalysis": Tier.T2_QUALITY_MEDIA,
    "caixin": Tier.T2_QUALITY_MEDIA,
    # ---------- Tier 3: Social / Self-Media ----------
    "twitter": Tier.T3_SOCIAL_SELF_MEDIA,
    "x.com": Tier.T3_SOCIAL_SELF_MEDIA,
    "fintwit": Tier.T3_SOCIAL_SELF_MEDIA,
    "linkedin": Tier.T3_SOCIAL_SELF_MEDIA,
    "substack": Tier.T3_SOCIAL_SELF_MEDIA,
    "seeking alpha": Tier.T3_SOCIAL_SELF_MEDIA,
    "reddit": Tier.T3_SOCIAL_SELF_MEDIA,
    "r/wallstreetbets": Tier.T3_SOCIAL_SELF_MEDIA,
    "xueqiu": Tier.T3_SOCIAL_SELF_MEDIA,
    "雪球": Tier.T3_SOCIAL_SELF_MEDIA,
    "xiaohongshu": Tier.T3_SOCIAL_SELF_MEDIA,
    "小红书": Tier.T3_SOCIAL_SELF_MEDIA,
}

# Domain → org override (used when only a URL is available).
DOMAIN_TO_ORG: dict[str, str] = {
    "ft.com": "Financial Times",
    "www.ft.com": "Financial Times",
    "bloomberg.com": "Bloomberg",
    "www.bloomberg.com": "Bloomberg",
    "wsj.com": "WSJ",
    "www.wsj.com": "WSJ",
    "economist.com": "The Economist",
    "asia.nikkei.com": "Nikkei Asia",
    "theinformation.com": "The Information",
    "barrons.com": "Barron's",
    "reuters.com": "Reuters",
    "stratechery.com": "Stratechery",
    "semianalysis.com": "SemiAnalysis",
    "twitter.com": "Twitter",
    "x.com": "Twitter",
    "linkedin.com": "LinkedIn",
    "substack.com": "Substack",
    "seekingalpha.com": "Seeking Alpha",
    "reddit.com": "Reddit",
    "xueqiu.com": "Xueqiu",
}


def normalize(s: str) -> str:
    return (s or "").strip().lower()


def classify_tier(org: str, default: int = Tier.T3_SOCIAL_SELF_MEDIA) -> int:
    """Return the tier for a publisher org. Falls back to T3 for unknown sources.

    The default-to-T3 behavior is deliberate: unknown sources should not be
    treated as research-quality. Promotion to a higher tier requires explicit
    registration in TIER_REGISTRY.
    """
    key = normalize(org)
    if key in TIER_REGISTRY:
        return TIER_REGISTRY[key]

    # Substring match — handle "Goldman Sachs Equity Research", etc.
    for known, tier in TIER_REGISTRY.items():
        if known in key:
            return tier

    return default


def org_from_url(url: str) -> str | None:
    """Best-effort publisher inference from a URL."""
    if not url:
        return None
    lowered = url.lower()
    for domain, org in DOMAIN_TO_ORG.items():
        if domain in lowered:
            return org
    return None


def tier_weight(tier: int) -> float:
    """Per-source weight in the tier-mix component of the strength score."""
    return {Tier.T1_PRIMARY_RESEARCH: 3.0, Tier.T2_QUALITY_MEDIA: 2.0, Tier.T3_SOCIAL_SELF_MEDIA: 1.0}.get(tier, 1.0)


def tier_label(tier: int) -> str:
    return {1: "T1 · Primary Research", 2: "T2 · Quality Media", 3: "T3 · Social / Self-Media"}.get(tier, f"T{tier}")
