"""HTTP client for Cardmarket scraping."""

from __future__ import annotations

import random
import threading
import time
from typing import TYPE_CHECKING

import cloudscraper

from ygo_app.cardmarket.constants import (
    BASE_URL,
    CIRCUIT_BREAKER_429_COOLDOWN_SECONDS,
    CIRCUIT_BREAKER_429_THRESHOLD,
    FetchBackend,
    MAX_RETRIES,
    RATE_LIMIT_429_BASE_SECONDS,
    REQUEST_TIMEOUT,
    RETRY_DELAY_RANGE,
    USER_AGENT,
)
from ygo_app.yugipedia.scrape_progress import log_line

if TYPE_CHECKING:
    from requests import Response

_consecutive_429_lock = threading.Lock()
_consecutive_429_count = 0


class RateLimiter:
    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def acquire(self, jitter: float = 0.0) -> None:
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            if jitter > 0:
                time.sleep(random.uniform(0, jitter))
            self._last_request_time = time.time()


class SessionPool:
    def __init__(self, num_workers: int, *, reuse_count: int = 10):
        self._sessions: dict[int, cloudscraper.CloudScraper] = {}
        self._uses: dict[int, int] = {}
        self._lock = threading.Lock()
        self._num_workers = num_workers
        self._reuse_count = reuse_count
        self._last_403: dict[int, float] = {}

    def get_session(self, worker_id: int) -> tuple[cloudscraper.CloudScraper, bool]:
        with self._lock:
            if worker_id in self._last_403:
                if time.time() - self._last_403[worker_id] < 30:
                    self._sessions.pop(worker_id, None)
                    self._uses.pop(worker_id, None)

            if worker_id in self._sessions and self._uses[worker_id] < self._reuse_count:
                self._uses[worker_id] += 1
                return self._sessions[worker_id], False

            scraper = create_scraper()
            self._sessions[worker_id] = scraper
            self._uses[worker_id] = 1
            return scraper, True

    def mark_403(self, worker_id: int) -> None:
        with self._lock:
            self._last_403[worker_id] = time.time()
            self._sessions.pop(worker_id, None)
            self._uses.pop(worker_id, None)

    def refresh(self, worker_id: int) -> cloudscraper.CloudScraper:
        with self._lock:
            self._sessions.pop(worker_id, None)
            self._uses.pop(worker_id, None)
        scraper, _ = self.get_session(worker_id)
        return scraper


def create_scraper() -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True},
        delay=10,
    )
    scraper.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Referer": f"{BASE_URL}/en/YuGiOh",
        }
    )
    return scraper


def resolve_scrape_settings(
    *,
    use_browser: bool,
    workers: int,
) -> tuple[int, float, float, FetchBackend]:
    """Return (workers, discovery_rps, price_rps, backend) for scrape mode."""
    from ygo_app.cardmarket.constants import (
        BROWSER_DEFAULT_REQUESTS_PER_SECOND,
        BROWSER_DEFAULT_WORKERS,
        BROWSER_DISCOVERY_REQUESTS_PER_SECOND,
        DEFAULT_REQUESTS_PER_SECOND,
        DEFAULT_WORKERS,
        DISCOVERY_REQUESTS_PER_SECOND,
    )

    if use_browser:
        effective_workers = workers if workers <= 1 else BROWSER_DEFAULT_WORKERS
        if workers > 1:
            log_line(
                f"[WARN] --browser forces workers=1 (requested {workers})"
            )
        return (
            effective_workers,
            BROWSER_DISCOVERY_REQUESTS_PER_SECOND,
            BROWSER_DEFAULT_REQUESTS_PER_SECOND,
            "playwright",
        )
    return (
        workers if workers > 0 else DEFAULT_WORKERS,
        DISCOVERY_REQUESTS_PER_SECOND,
        DEFAULT_REQUESTS_PER_SECOND,
        "cloudscraper",
    )


def _parse_retry_after(headers: dict[str, str] | None) -> float | None:
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _sleep_for_429(
    *,
    attempt: int,
    headers: dict[str, str] | None = None,
) -> None:
    global _consecutive_429_count
    with _consecutive_429_lock:
        _consecutive_429_count += 1
        count = _consecutive_429_count
    retry_after = _parse_retry_after(headers)
    if retry_after is not None:
        delay = max(retry_after, 1.0)
    else:
        delay = RATE_LIMIT_429_BASE_SECONDS * (2**attempt)
    if count >= CIRCUIT_BREAKER_429_THRESHOLD:
        delay = max(delay, CIRCUIT_BREAKER_429_COOLDOWN_SECONDS)
        log_line(
            f"[WARN] Rate limit circuit breaker: {count} consecutive 429s; "
            f"sleeping {delay:.0f}s"
        )
    else:
        log_line(f"[WARN] HTTP 429; sleeping {delay:.0f}s (attempt {attempt + 1})")
    time.sleep(delay)


def _note_success() -> None:
    global _consecutive_429_count
    with _consecutive_429_lock:
        _consecutive_429_count = 0


def _fetch_cloudscraper(
    scraper: cloudscraper.CloudScraper,
    url: str,
) -> tuple[str | None, int | None, dict[str, str], str | None]:
    response: Response = scraper.get(url, timeout=REQUEST_TIMEOUT)
    headers = dict(response.headers)
    if response.status_code == 200:
        return response.text, response.status_code, headers, None
    return None, response.status_code, headers, f"HTTP {response.status_code}"


def _fetch_playwright(url: str) -> tuple[str | None, int | None, dict[str, str], str | None]:
    from ygo_app.cardmarket.browser_client import BrowserSession

    return BrowserSession.get().fetch(url)


def _looks_like_429(*, status: int | None, error: str | None) -> bool:
    if status == 429:
        return True
    if not error:
        return False
    lower = error.lower()
    return any(
        marker in lower
        for marker in (
            "http 429",
            "429",
            "too many requests",
            "rate limit",
            "err_http_response_code_failure",
        )
    )


def _log_fetch_failure(url: str, status: int | None, error: str | None, attempt: int) -> None:
    if status is not None:
        log_line(
            f"[WARN] HTTP {status} {url[:80]} "
            f"(attempt {attempt + 1})"
            + (f" — {error}" if error and not error.startswith("HTTP ") else "")
        )
    elif error:
        log_line(f"[WARN] fetch failed {url[:80]}: {error} (attempt {attempt + 1})")


def fetch_url(
    scraper: cloudscraper.CloudScraper | None,
    url: str,
    *,
    backend: FetchBackend = "cloudscraper",
    rate_limiter: RateLimiter | None = None,
    retries: int = MAX_RETRIES,
    jitter: float = 0.0,
    session_pool: SessionPool | None = None,
    worker_id: int = 0,
) -> tuple[str | None, str | None]:
    if backend == "cloudscraper" and scraper is None:
        scraper = create_scraper()

    for attempt in range(retries):
        try:
            if rate_limiter:
                rate_limiter.acquire(jitter)

            if backend == "playwright":
                html, status, headers, error = _fetch_playwright(url)
            else:
                assert scraper is not None
                html, status, headers, error = _fetch_cloudscraper(scraper, url)

            if html and status == 200:
                _note_success()
                return html, None

            if status == 403:
                _log_fetch_failure(url, status, error, attempt)
                if session_pool:
                    session_pool.mark_403(worker_id)
                if attempt < retries - 1:
                    time.sleep(random.uniform(20, 30))
                    if session_pool and scraper is not None:
                        scraper = session_pool.refresh(worker_id)
                    continue
                return None, "HTTP 403"

            if status == 404:
                return None, "HTTP 404"

            if _looks_like_429(status=status, error=error):
                _log_fetch_failure(url, status or 429, error, attempt)
                if attempt < retries - 1:
                    _sleep_for_429(attempt=attempt, headers=headers)
                    continue
                return None, error or "HTTP 429"

            if status in (500, 503):
                _log_fetch_failure(url, status, error, attempt)
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                return None, error or f"HTTP {status}"

            if status is not None or error:
                _log_fetch_failure(url, status, error, attempt)
            return None, error or (f"HTTP {status}" if status else "fetch failed")
        except Exception as exc:
            from ygo_app.cardmarket.browser_client import BrowserStartupError, format_fetch_error

            if isinstance(exc, BrowserStartupError):
                detail = str(exc)
                if attempt < retries - 1:
                    _log_fetch_failure(url, None, detail, attempt)
                    time.sleep(5)
                    continue
                log_line(f"[WARN] fetch failed {url[:80]}: {detail}")
                return None, detail
            detail = format_fetch_error(exc)
            if attempt < retries - 1:
                _log_fetch_failure(url, None, detail, attempt)
                delay = random.uniform(*RETRY_DELAY_RANGE)
                time.sleep(delay)
                continue
            log_line(f"[WARN] fetch failed {url[:80]}: {detail}")
            return None, detail
    return None, "max retries"
