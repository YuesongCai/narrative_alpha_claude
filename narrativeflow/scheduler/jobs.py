"""Tiny in-process scheduler.

V1 ships a sleep-loop scheduler so we don't drag in APScheduler/celery for an
MVP. The scheduler runs the pipeline + dispatch loop on a configurable
interval. For multi-process / distributed scheduling we'll swap this for
APScheduler or a Cloud-side cron in V3.
"""

from __future__ import annotations

import logging
import signal
import time
from typing import Optional

from ..notify import dispatch_pending
from ..pipeline import run_pipeline

logger = logging.getLogger(__name__)


def run_loop(*, interval_seconds: int = 600, run_once: bool = False) -> None:
    """Run pipeline + notifications every `interval_seconds`. Ctrl-C exits cleanly."""
    stop = {"flag": False}

    def _handler(_signo, _frame) -> None:
        stop["flag"] = True
        logger.info("scheduler: shutdown requested")

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    while not stop["flag"]:
        try:
            report = run_pipeline()
            logger.info("scheduler: %s", report.summary())
            delivered = dispatch_pending()
            logger.info("scheduler: delivered=%d notifications", delivered)
        except Exception as e:  # pragma: no cover
            logger.exception("scheduler iteration failed: %s", e)

        if run_once:
            break

        for _ in range(interval_seconds):
            if stop["flag"]:
                break
            time.sleep(1)
