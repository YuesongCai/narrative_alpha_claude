"""Anthropic SDK wrapper with prompt caching and a heuristic fallback.

The pipeline must run end-to-end without an API key (for unit tests, demos,
and offline development). When `ANTHROPIC_API_KEY` is set, we route real LLM
calls through Claude Sonnet 4.6 with prompt caching on the system prompt. When
it isn't set, every call returns `None` and the caller gracefully falls back to
its rules-based path.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("NARRATIVE_ALPHA_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 1024

_client = None
_client_init_attempted = False


def _get_client():
    """Lazy-instantiate the Anthropic client. Returns None if unavailable."""
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # type: ignore

        _client = anthropic.Anthropic()
    except Exception as e:  # pragma: no cover
        logger.warning("Anthropic SDK unavailable, falling back to heuristics: %s", e)
        _client = None
    return _client


def llm_available() -> bool:
    return _get_client() is not None


def _extract_json(text: str) -> Any:
    """Pull the first JSON blob out of a response. Tolerates code fences."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    # Find the first '{' or '[' and try to parse the smallest valid blob.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = payload.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(payload)):
            ch = payload[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    blob = payload[start : i + 1]
                    try:
                        return json.loads(blob)
                    except json.JSONDecodeError:
                        break
    return None


def call_json(
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
    cache_system: bool = True,
) -> Any | None:
    """Run a JSON-returning prompt. Returns parsed JSON or None on failure.

    The system prompt is marked as a cache breakpoint so repeated extractions
    against the same instructions hit the prompt cache.
    """
    client = _get_client()
    if client is None:
        return None

    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
    if cache_system:
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as e:  # pragma: no cover - network path
        logger.warning("LLM call failed (%s); falling back to heuristic.", e)
        return None

    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    return _extract_json(text)
