"""State-change → notification dispatch.

Walks `StateChange` rows that haven't been notified yet, pushes them through
each enabled channel, and stamps `notified_at` on success. Strictly state-
change driven — never news-frequency. Per the PRD §6.1, expected volume is
1–3 per narrative per week.
"""

from __future__ import annotations

import logging
from typing import Iterable

from ..models import utcnow
from ..store import NarrativeRepo, StateChangeRepo, UserRepo, get_session
from .base import NoopChannel, NotificationChannel
from .telegram import TelegramChannel

logger = logging.getLogger(__name__)


def default_channels() -> list[NotificationChannel]:
    """Return all channels that are configured + ready."""
    channels: list[NotificationChannel] = []
    tg = TelegramChannel()
    if tg.enabled:
        channels.append(tg)
    if not channels:
        channels.append(NoopChannel())  # always have one channel
    return channels


def dispatch_pending(channels: Iterable[NotificationChannel] | None = None) -> int:
    """Send all pending state changes; return the number delivered."""
    chans = list(channels) if channels is not None else default_channels()
    delivered = 0

    with get_session() as session:
        sc_repo = StateChangeRepo(session)
        n_repo = NarrativeRepo(session)
        u_repo = UserRepo(session)

        # Single-user V1 — only notify if the user follows the narrative AND
        # has the relevant notification toggle on.
        user = u_repo.get_or_create_local()
        followed_ids = {f.narrative_id: f for f in user.follows}

        for sc in sc_repo.pending_notifications():
            if sc.narrative_id not in followed_ids:
                sc.notified_at = utcnow()  # mark as handled even if skipped
                continue
            follow = followed_ids[sc.narrative_id]
            if not _wants(follow, sc.change_type):
                sc.notified_at = utcnow()
                continue

            narrative = n_repo.get(sc.narrative_id)
            if not narrative:
                continue
            title = f"{narrative.title} — {sc.change_type.replace('_', ' ')}"
            body = sc.description
            ok = any(c.send(title=title, body=body) for c in chans if c.enabled)
            if ok:
                sc.notified_at = utcnow()
                delivered += 1

    return delivered


def _wants(follow, change_type: str) -> bool:
    if change_type in ("heat_shift", "narrative_convergence"):
        return follow.notify_heat
    if change_type == "new_catalyst":
        return follow.notify_catalysts
    if change_type in ("exit_signal", "ticker_rotation"):
        return follow.notify_exit
    return True
