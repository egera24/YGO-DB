"""HTTP client for Cardmarket scraping."""

from __future__ import annotations

import random
import threading
import time

import cloudscraper

from ygo_app.cardmarket.constants import (
    BASE_URL,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY_RANGE,
    USER_AGENT,
)
from ygo_app.yugipedia.scrape_progress import log_line


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


def fetch_url(
    scraper: cloudscraper.CloudScraper,
    url: str,
    *,
    rate_limiter: RateLimiter | None = None,
    retries: int = MAX_RETRIES,
    jitter: float = 0.0,
    session_pool: SessionPool | None = None,
    worker_id: int = 0,
) -> tuple[str | None, str | None]:
    for attempt in range(retries):
        try:
            if rate_limiter:
                rate_limiter.acquire(jitter)
            response = scraper.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return response.text, None
            if response.status_code == 403:
                if session_pool:
                    session_pool.mark_403(worker_id)
                if attempt < retries - 1:
                    time.sleep(random.uniform(20, 30))
                    if session_pool:
                        scraper = session_pool.refresh(worker_id)
                    continue
                return None, "HTTP 403"
            if response.status_code == 404:
                return None, "HTTP 404"
            if response.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if response.status_code in (500, 503):
                time.sleep(5)
                continue
            return None, f"HTTP {response.status_code}"
        except Exception as exc:
            if attempt < retries - 1:
                delay = random.uniform(*RETRY_DELAY_RANGE)
                time.sleep(delay)
                continue
            log_line(f"[WARN] fetch failed {url[:80]}: {type(exc).__name__}")
            return None, type(exc).__name__
    return None, "max retries"
