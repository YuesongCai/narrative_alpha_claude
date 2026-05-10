"""Anthropic Claude integration.

🤖 EVERY AI API CALL IN NARRATIVEFLOW LIVES IN THIS PACKAGE. 🤖

If a module outside `narrativeflow.ai/` imports `anthropic` directly, that's a
violation of the architecture — push the call into here and expose a typed
helper. This isolation means we have one place to swap models, add caching,
add observability, or drop the dependency entirely.

Public surface:
    AIClient           — Anthropic wrapper with prompt caching + JSON parsing.
    classify_noise     — 🤖 noise filter (Stage 2 of the pipeline).
    tag_to_narratives  — 🤖 narrative tagging (Stage 3 of the pipeline).
    synthesize_narrative — 🤖 full tracker synthesis (Stage 4 of the pipeline).
    match_query_to_narrative — 🤖 NL search resolver.
"""

from .client import AIClient, get_client, ai_enabled
from .tasks import (
    classify_noise,
    match_query_to_narrative,
    synthesize_narrative,
    tag_to_narratives,
)

__all__ = [
    "AIClient",
    "get_client",
    "ai_enabled",
    "classify_noise",
    "tag_to_narratives",
    "synthesize_narrative",
    "match_query_to_narrative",
]
