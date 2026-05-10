"""Anthropic SDK wrapper.

🤖 Wraps `anthropic.Anthropic` with:
   * lazy initialization (no key → no client → callers fall back gracefully)
   * prompt caching on the system prompt (each task reuses one system prompt
     across many user messages, so caching saves ~70% on tokens)
   * tolerant JSON extraction so model wobble doesn't break the pipeline
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Optional

from ..config import get_settings

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    """Pull the first valid JSON blob from a model response. Tolerates fences."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
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


class AIClient:
    """Thin wrapper around Anthropic with caching + JSON helper.

    Construct via `get_client()`; never instantiate directly so the lru_cache
    keeps the SDK client alive for the process.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        if not self.settings.ai_enabled:
            return
        try:
            import anthropic  # type: ignore

            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        except Exception as e:  # pragma: no cover
            logger.warning("Failed to init Anthropic client: %s", e)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def call_json(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        cache_system: bool = True,
    ) -> Any | None:
        """Run a JSON-returning prompt. Returns parsed JSON, or None on failure."""
        if not self.enabled:
            return None
        chosen = model or self.settings.model_fast
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}
        try:
            msg = self._client.messages.create(
                model=chosen,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:  # pragma: no cover - network path
            logger.warning("LLM call failed (%s); caller should fall back.", e)
            return None
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        return _extract_json(text)


@lru_cache(maxsize=1)
def get_client() -> AIClient:
    return AIClient()


def ai_enabled() -> bool:
    return get_client().enabled
