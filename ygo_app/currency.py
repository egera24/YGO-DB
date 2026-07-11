"""EUR/HUF exchange rate for public trade display."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from ygo_app.config import EUR_HUF_RATE

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.app/latest?from=EUR&to=HUF"
CACHE_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class EurHufRate:
    rate: float
    source: str  # "live" | "fallback"
    as_of: str | None = None


_cache: EurHufRate | None = None
_cache_expires_at: float = 0.0


def clear_eur_huf_cache() -> None:
    global _cache, _cache_expires_at
    _cache = None
    _cache_expires_at = 0.0


def _fetch_live_rate() -> EurHufRate | None:
    try:
        response = requests.get(FRANKFURTER_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        rate = float(data["rates"]["HUF"])
        as_of = data.get("date")
        return EurHufRate(rate=rate, source="live", as_of=as_of)
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        logger.warning("Failed to fetch EUR/HUF rate: %s", exc)
        return None


def get_eur_huf_rate(*, force_refresh: bool = False) -> EurHufRate:
    global _cache, _cache_expires_at

    now = time.monotonic()
    if not force_refresh and _cache is not None and now < _cache_expires_at:
        return _cache

    live = _fetch_live_rate()
    if live is not None:
        _cache = live
        _cache_expires_at = now + CACHE_TTL_SECONDS
        return live

    fallback = EurHufRate(rate=EUR_HUF_RATE, source="fallback", as_of=None)
    _cache = fallback
    _cache_expires_at = now + CACHE_TTL_SECONDS
    return fallback
