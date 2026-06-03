"""HTTP client with rate limiting and retries for Yugipedia wiki pages."""

from __future__ import annotations

import random
import threading
import time

import cloudscraper

from ygo_app.yugipedia.constants import (
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
    RETRY_DELAYS,
    SLOW_REQUEST_WARN_SECONDS,
    USER_AGENT,
)
from ygo_app.yugipedia.scrape_progress import log_line


class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_time = time.time()


_rate_limiter = RateLimiter(MIN_REQUEST_INTERVAL)


def create_scraper() -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    scraper.headers.update({"User-Agent": USER_AGENT})
    return scraper


def fetch_page(scraper, url: str, *, retries: int = MAX_RETRIES) -> tuple[str | None, str | None]:
    for attempt in range(retries):
        try:
            _rate_limiter.acquire()
            started = time.monotonic()
            response = scraper.get(url, timeout=REQUEST_TIMEOUT)
            elapsed = time.monotonic() - started
            if elapsed >= SLOW_REQUEST_WARN_SECONDS:
                log_line(
                    f"[WARN] Slow HTTP {elapsed:.1f}s (attempt {attempt + 1}/{retries}) "
                    f"{url[:80]}"
                )
            response.raise_for_status()
            return response.text, None
        except cloudscraper.exceptions.CloudflareChallengeError as e:
            error_msg = f"CloudflareError: {str(e)[:100]}"
            log_line(
                f"[WARN] Cloudflare challenge (attempt {attempt + 1}/{retries}) "
                f"{url[:60]}"
            )
            if attempt < retries - 1:
                time.sleep(RETRY_DELAYS[attempt] + random.uniform(0, 2))
                continue
            return None, error_msg
        except Exception as e:
            error_type = type(e).__name__
            error_str = str(e)
            is_retryable = any(
                [
                    "502" in error_str,
                    "503" in error_str,
                    "500" in error_str,
                    "504" in error_str,
                    "timeout" in error_str.lower(),
                    "timed out" in error_str.lower(),
                    "ReadTimeout" in error_type,
                    "ConnectTimeout" in error_type,
                    "ConnectionError" in error_type,
                ]
            )
            if is_retryable and attempt < retries - 1:
                log_line(
                    f"[WARN] Retryable {error_type} (attempt {attempt + 1}/{retries}) "
                    f"{url[:60]}"
                )
                time.sleep(RETRY_DELAYS[attempt] + random.uniform(0, 2))
                continue
            return None, f"{error_type}: {error_str[:100]}"
    return None, f"Failed after {retries} retry attempts"
