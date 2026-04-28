"""Price tracking for alpha-target validation.

V1 uses yfinance when available; otherwise we fall back to a deterministic
mock price keyed by ticker so the validation framework remains testable
offline. The mock applies a small drift over time so prices change between
runs — enough to exercise the digest's price-change rendering.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:  # optional dep
    import yfinance  # type: ignore
except ImportError:  # pragma: no cover
    yfinance = None  # type: ignore


def _use_mock() -> bool:
    if os.environ.get("NARRATIVE_ALPHA_PRICES") == "mock":
        return True
    return yfinance is None


def _seed(ticker: str) -> int:
    return int(hashlib.sha1(ticker.encode("utf-8")).hexdigest()[:8], 16)


def _mock_price(ticker: str, *, at: Optional[datetime] = None) -> float:
    """Stable, ticker-dependent baseline + sinusoidal drift over time."""
    seed = _seed(ticker)
    base = 20 + (seed % 380)  # 20..399
    when = at or datetime.utcnow()
    # Drift period of ~30 days, amplitude ~6% of base.
    days = (when - datetime(2026, 1, 1)).total_seconds() / 86400.0
    drift = math.sin(2 * math.pi * days / 30.0 + (seed % 7))
    return round(base * (1.0 + 0.06 * drift), 2)


def current_price(ticker: str) -> float:
    """Best-effort price lookup. Always returns a non-zero float."""
    if _use_mock():
        return _mock_price(ticker)
    try:  # pragma: no cover - network path
        info = yfinance.Ticker(ticker).fast_info
        price = float(info["last_price"])
        if price > 0:
            return price
    except Exception as e:
        logger.debug("yfinance fetch failed for %s: %s — falling back to mock", ticker, e)
    return _mock_price(ticker)


def refresh_prices(targets) -> None:
    """Update `current_price` and `last_price_update` on a list of AlphaTargets."""
    now = datetime.utcnow()
    for t in targets:
        t.current_price = current_price(t.ticker)
        t.last_price_update = now
