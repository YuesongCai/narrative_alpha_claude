"""Telegram bot channel — public Bot API, no special dependency."""

from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from .base import NotificationChannel

logger = logging.getLogger(__name__)


class TelegramChannel(NotificationChannel):
    name = "telegram"

    def __init__(self) -> None:
        settings = get_settings()
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, *, title: str, body: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        text = f"*{title}*\n{body}"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"})
                resp.raise_for_status()
            return True
        except Exception as e:  # pragma: no cover - network
            logger.warning("Telegram send failed: %s", e)
            return False
