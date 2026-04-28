"""Narrative Alpha — narrative lifecycle tracker for alpha discovery.

Detect narratives before they become consensus. Map alpha targets. Validate with price.
"""

__version__ = "0.1.0"

from .models import (
    AlphaTarget,
    Claim,
    Digest,
    Narrative,
    Source,
    Stage,
    Tier,
)

__all__ = [
    "AlphaTarget",
    "Claim",
    "Digest",
    "Narrative",
    "Source",
    "Stage",
    "Tier",
]
