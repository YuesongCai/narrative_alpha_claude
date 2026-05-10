"""Notification channel abstraction.

Subclasses implement `send` and the dispatcher fans out to all enabled
channels. Adding Slack / WeChat-OA / Email is a matter of one new subclass.
"""

from __future__ import annotations

import abc
import logging

logger = logging.getLogger(__name__)


class NotificationChannel(abc.ABC):
    name: str

    @property
    @abc.abstractmethod
    def enabled(self) -> bool: ...

    @abc.abstractmethod
    def send(self, *, title: str, body: str) -> bool:
        """Return True if delivery succeeded."""


class NoopChannel(NotificationChannel):
    """Logs the message and pretends to deliver. Always available."""
    name = "noop"

    @property
    def enabled(self) -> bool:
        return True

    def send(self, *, title: str, body: str) -> bool:
        logger.info("📣 NOTIFY [%s] %s", title, body)
        return True
