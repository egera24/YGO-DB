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


def _response_log_fields(response) -> dict:
    if response is None:
        return {"has_response": False, "status_code": None, "body_bytes_read": 0}
    content = getattr(response, "content", b"") or b""
    return {
        "has_response": True,
        "status_code": getattr(response, "status_code", None),
        "body_bytes_read": len(content),
    }


def create_scraper() -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    scraper.headers.update({"User-Agent": USER_AGENT})
    return scraper


def fetch_page(
    scraper,
    url: str,
    *,
    retries: int = MAX_RETRIES,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[str | None, str | None]:
    for attempt in range(retries):
        started = time.monotonic()
        try:
            _rate_limiter.acquire()
            response = scraper.get(url, timeout=timeout)
            elapsed = time.monotonic() - started
            resp_fields = _response_log_fields(response)
            if elapsed >= SLOW_REQUEST_WARN_SECONDS:
                log_line(
                    f"[WARN] Slow HTTP {elapsed:.1f}s status={resp_fields['status_code']} "
                    f"bytes={resp_fields['body_bytes_read']} "
                    f"(attempt {attempt + 1}/{retries}) {url[:80]}"
                )
            response.raise_for_status()
            return response.text, None
        except cloudscraper.exceptions.CloudflareChallengeError as e:
            elapsed = time.monotonic() - started
            error_msg = f"CloudflareError: {str(e)[:100]}"
            log_line(
                f"[WARN] Cloudflare challenge (attempt {attempt + 1}/{retries}) "
                f"elapsed={elapsed:.1f}s {url[:60]}"
            )
            if attempt < retries - 1:
                time.sleep(RETRY_DELAYS[attempt] + random.uniform(0, 2))
                continue
            return None, error_msg
        except Exception as e:
            elapsed = time.monotonic() - started
            error_type = type(e).__name__
            error_str = str(e)
            resp_fields = _response_log_fields(getattr(e, "response", None))
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
            status_part = (
                f" status={resp_fields['status_code']} bytes={resp_fields['body_bytes_read']}"
                if resp_fields["has_response"]
                else " no_response"
            )
            if is_retryable and attempt < retries - 1:
                log_line(
                    f"[WARN] Retryable {error_type} (attempt {attempt + 1}/{retries}) "
                    f"elapsed={elapsed:.1f}s{status_part} {url[:60]}"
                )
                time.sleep(RETRY_DELAYS[attempt] + random.uniform(0, 2))
                continue
            return None, f"{error_type}: {error_str[:100]}"
    return None, f"Failed after {retries} retry attempts"
