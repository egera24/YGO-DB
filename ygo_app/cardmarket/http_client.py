"""HTTP client for Cardmarket scraping."""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cloudscraper

from ygo_app import config
from ygo_app.cardmarket.constants import (
    ADAPTIVE_THROTTLE_MIN_RPS,
    ADAPTIVE_THROTTLE_RECOVER_FACTOR,
    ADAPTIVE_THROTTLE_SLOW_FACTOR,
    ADAPTIVE_THROTTLE_SUCCESS_STREAK,
    BASE_URL,
    CF_CHALLENGE_RETRY_DELAYS,
    CF_RATE_LIMIT_MARKERS,
    CIRCUIT_BREAKER_429_COOLDOWN_SECONDS,
    CIRCUIT_BREAKER_429_THRESHOLD,
    CURL_CFFI_IMPERSONATE,
    FetchBackend,
    INTER_PAGE_DELAY_BROWSER,
    INTER_PAGE_DELAY_HTTP,
    LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS,
    LONG_BAN_RETRY_AFTER_SECONDS,
    MAX_RETRIES,
    RATE_LIMIT_429_BASE_SECONDS,
    REQUEST_TIMEOUT,
    RETRY_DELAY_RANGE,
    SESSION_REUSE_COUNT,
    USER_AGENTS,
    USER_AGENT,
)
from ygo_app.cardmarket.browser_profiles import active_browser_storage_path
from ygo_app.cardmarket.paths import CARDMARKET_BROWSER_STATE_PATH
from ygo_app.cardmarket.url_log import format_fetch_url
from ygo_app.yugipedia.scrape_progress import log_line

if TYPE_CHECKING:
    from requests import Response

_consecutive_429_lock = threading.Lock()
_consecutive_429_count = 0

_scrape_shutdown = threading.Event()


class ScrapeShutdown(Exception):
    """Raised when a scrape job is interrupted (Ctrl+C)."""


def clear_scrape_shutdown() -> None:
    _scrape_shutdown.clear()


def request_scrape_shutdown() -> None:
    _scrape_shutdown.set()


def scrape_shutdown_requested() -> bool:
    return _scrape_shutdown.is_set()

_CF_LOGIN_HINT = "python -m ygo_app.jobs.scrape_cardmarket_expansions --cf-login"


def _browser_cookie_storage_path() -> Path:
    """Cookie file for the active scrape profile (or legacy global path)."""
    try:
        return active_browser_storage_path()
    except Exception:
        return CARDMARKET_BROWSER_STATE_PATH

_CF_CHALLENGE_MARKERS = (
    "_cf_chl_opt",
    "cf-browser-verification",
    "just a moment",
    "challenge-platform",
    "checking your browser",
)


class RateLimitAbort(Exception):
    """Raised when Retry-After indicates a long IP ban; checkpoint and exit."""

    def __init__(self, retry_after_seconds: float, message: str = "") -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            message
            or f"Rate limited for {retry_after_seconds:.0f}s — see docs/cloudflare/README.md"
        )


def is_cloudflare_rate_limited(html: str | None) -> bool:
    if not html:
        return False
    lower = html.lower()
    return any(marker in lower for marker in CF_RATE_LIMIT_MARKERS)


def sleep_inter_page_delay(backend: FetchBackend) -> None:
    if backend == "playwright":
        time.sleep(random.uniform(*INTER_PAGE_DELAY_BROWSER))
    else:
        time.sleep(random.uniform(*INTER_PAGE_DELAY_HTTP))


def log_rate_limit_recovery(retry_after_seconds: float) -> None:
    hours = retry_after_seconds / 3600.0
    wait_hint = f"{retry_after_seconds:.0f}s" if hours < 1 else f"~{hours:.1f}h"
    log_line(
        f"[ABORT] Long rate limit (Retry-After {wait_hint}). "
        "Checkpoint saved. Recovery:"
    )
    log_line("  1. Stop scraping until the ban expires.")
    log_line("  2. Verify https://www.cardmarket.com in your normal browser (not scrape Chrome).")
    log_line("  3. Resume: --resume --polite (or lower --discovery-rps / --rps).")
    log_line("  4. See docs/cloudflare/README.md for details.")


def curl_cffi_available() -> bool:
    try:
        import curl_cffi.requests  # noqa: F401

        return True
    except ImportError:
        return False


def default_fetch_backend() -> FetchBackend:
    if curl_cffi_available():
        return "curl_cffi"
    return "cloudscraper"


def user_agent_for_worker(worker_id: int) -> str:
    return USER_AGENTS[worker_id % len(USER_AGENTS)]


def browser_headers(user_agent: str | None = None) -> dict[str, str]:
    ua = user_agent or USER_AGENT
    return {
        "User-Agent": ua,
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


def is_cloudflare_challenge(html: str | None) -> bool:
    if not html:
        return False
    lower = html.lower()
    return any(marker in lower for marker in _CF_CHALLENGE_MARKERS)


def _proxy_dict() -> dict[str, str] | None:
    proxy = config.CARDMARKET_HTTP_PROXY
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


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


class AdaptiveRateLimiter(RateLimiter):
    """Slow down on 403/429; gradually recover after success streak."""

    def __init__(self, requests_per_second: float):
        super().__init__(requests_per_second)
        self._baseline_interval = self.min_interval
        self._success_streak = 0

    @property
    def current_rps(self) -> float:
        if self.min_interval <= 0:
            return ADAPTIVE_THROTTLE_MIN_RPS
        return 1.0 / self.min_interval

    def note_success(self) -> None:
        with self._lock:
            self._success_streak += 1
            if self._success_streak >= ADAPTIVE_THROTTLE_SUCCESS_STREAK:
                new_interval = max(
                    self._baseline_interval,
                    self.min_interval * ADAPTIVE_THROTTLE_RECOVER_FACTOR,
                )
                if new_interval < self.min_interval - 1e-9:
                    self.min_interval = new_interval
                    log_line(f"[THROTTLE] rps={self.current_rps:.2f} reason=recover")
                self._success_streak = 0

    def note_block(self, *, reason: str) -> None:
        with self._lock:
            self._success_streak = 0
            max_interval = 1.0 / ADAPTIVE_THROTTLE_MIN_RPS
            new_interval = min(max_interval, self.min_interval * ADAPTIVE_THROTTLE_SLOW_FACTOR)
            if new_interval > self.min_interval + 1e-9:
                self.min_interval = new_interval
                log_line(f"[THROTTLE] rps={self.current_rps:.2f} reason={reason}")


class SessionPool:
    def __init__(self, num_workers: int, *, reuse_count: int = SESSION_REUSE_COUNT):
        self._sessions: dict[int, cloudscraper.CloudScraper] = {}
        self._uses: dict[int, int] = {}
        self._lock = threading.Lock()
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

            scraper = create_scraper(worker_id)
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


class CurlCffiSessionPool:
    def __init__(self, num_workers: int, *, reuse_count: int = SESSION_REUSE_COUNT):
        self._sessions: dict[int, Any] = {}
        self._uses: dict[int, int] = {}
        self._lock = threading.Lock()
        self._reuse_count = reuse_count
        self._last_403: dict[int, float] = {}

    def get_session(self, worker_id: int) -> tuple[Any, bool]:
        with self._lock:
            if worker_id in self._last_403:
                if time.time() - self._last_403[worker_id] < 30:
                    self._sessions.pop(worker_id, None)
                    self._uses.pop(worker_id, None)

            if worker_id in self._sessions and self._uses[worker_id] < self._reuse_count:
                self._uses[worker_id] += 1
                return self._sessions[worker_id], False

            session = create_curl_cffi_session(worker_id)
            self._sessions[worker_id] = session
            self._uses[worker_id] = 1
            return session, True

    def mark_403(self, worker_id: int) -> None:
        with self._lock:
            self._last_403[worker_id] = time.time()
            old = self._sessions.pop(worker_id, None)
            self._uses.pop(worker_id, None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass

    def refresh(self, worker_id: int) -> Any:
        with self._lock:
            old = self._sessions.pop(worker_id, None)
            self._uses.pop(worker_id, None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
        session, _ = self.get_session(worker_id)
        return session


def create_session_pool(backend: FetchBackend, num_workers: int) -> SessionPool | CurlCffiSessionPool | None:
    if backend == "cloudscraper":
        return SessionPool(num_workers)
    if backend == "curl_cffi":
        return CurlCffiSessionPool(num_workers)
    return None


def create_scraper(worker_id: int = 0) -> cloudscraper.CloudScraper:
    from ygo_app.cardmarket.browser_cookies import apply_storage_cookies

    ua = user_agent_for_worker(worker_id)
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True},
        delay=10,
    )
    scraper.headers.update(browser_headers(ua))
    proxies = _proxy_dict()
    if proxies:
        scraper.proxies.update(proxies)
    apply_storage_cookies(scraper, _browser_cookie_storage_path(), backend="cloudscraper")
    return scraper


def create_curl_cffi_session(worker_id: int = 0):
    from curl_cffi import requests as curl_requests

    from ygo_app.cardmarket.browser_cookies import apply_storage_cookies

    session = curl_requests.Session(impersonate=CURL_CFFI_IMPERSONATE)
    session.headers.update(browser_headers(user_agent_for_worker(worker_id)))
    proxies = _proxy_dict()
    if proxies:
        session.proxies = proxies
    apply_storage_cookies(session, _browser_cookie_storage_path(), backend="curl_cffi")
    return session


def probe_curl_cffi_session(
    storage_path: Path,
    url: str,
    *,
    worker_id: int = 0,
) -> tuple[bool, int | None, str | None]:
    """Test whether saved browser cookies work with curl_cffi for a URL."""
    from curl_cffi import requests as curl_requests

    from ygo_app.cardmarket.browser_cookies import apply_storage_cookies

    session = curl_requests.Session(impersonate=CURL_CFFI_IMPERSONATE)
    session.headers.update(browser_headers(user_agent_for_worker(worker_id)))
    proxies = _proxy_dict()
    if proxies:
        session.proxies = proxies
    apply_storage_cookies(session, storage_path, backend="curl_cffi")
    try:
        html, status, _headers, error = _fetch_curl_cffi(session, url)
        if html and status == 200:
            return True, status, None
        return False, status, error
    finally:
        try:
            session.close()
        except Exception:
            pass


def resolve_scrape_settings(
    *,
    backend: FetchBackend | None = None,
    use_browser: bool = False,
    workers: int | None = None,
    price_rps: float | None = None,
    discovery_rps: float | None = None,
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

    effective_backend = backend
    if use_browser:
        effective_backend = "playwright"
    if effective_backend is None:
        effective_backend = default_fetch_backend()

    if discovery_rps is None:
        discovery_rps = config.CARDMARKET_DISCOVERY_RPS
    if price_rps is None:
        price_rps = config.CARDMARKET_PRICE_RPS
    if workers is None:
        workers = config.CARDMARKET_WORKERS if config.CARDMARKET_WORKERS is not None else DEFAULT_WORKERS

    if effective_backend == "playwright":
        effective_workers = workers if workers <= 1 else BROWSER_DEFAULT_WORKERS
        if workers > 1:
            log_line(f"[WARN] playwright backend forces workers=1 (requested {workers})")
        return (
            effective_workers,
            discovery_rps if discovery_rps is not None else BROWSER_DISCOVERY_REQUESTS_PER_SECOND,
            price_rps if price_rps is not None else BROWSER_DEFAULT_REQUESTS_PER_SECOND,
            "playwright",
        )

    return (
        workers if workers > 0 else DEFAULT_WORKERS,
        discovery_rps if discovery_rps is not None else DISCOVERY_REQUESTS_PER_SECOND,
        price_rps if price_rps is not None else DEFAULT_REQUESTS_PER_SECOND,
        effective_backend,
    )


def _retry_after_raw(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_retry_after(headers: dict[str, str] | None) -> float | None:
    raw = _retry_after_raw(headers)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime

        retry_at = parsedate_to_datetime(raw)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except (TypeError, ValueError, OverflowError):
        return None


def _effective_retry_after(
    headers: dict[str, str] | None,
    *,
    html: str | None = None,
    error: str | None = None,
) -> float | None:
    retry_after = _parse_retry_after(headers)
    if retry_after is not None:
        return retry_after
    if html and is_cloudflare_rate_limited(html):
        return LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS
    if error:
        lower = error.lower()
        if "1015" in lower or (
            "cloudflare" in lower and "rate limit" in lower
        ):
            return LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS
    return None


def _raise_if_long_ban(
    headers: dict[str, str] | None,
    *,
    html: str | None = None,
    error: str | None = None,
) -> None:
    retry_after = _effective_retry_after(headers, html=html, error=error)
    if retry_after is not None and retry_after >= LONG_BAN_RETRY_AFTER_SECONDS:
        log_rate_limit_recovery(retry_after)
        raise RateLimitAbort(retry_after)


def _sleep_for_429(
    *,
    attempt: int,
    headers: dict[str, str] | None = None,
    html: str | None = None,
    error: str | None = None,
) -> None:
    _raise_if_long_ban(headers, html=html, error=error)
    global _consecutive_429_count
    with _consecutive_429_lock:
        _consecutive_429_count += 1
        count = _consecutive_429_count
    retry_after_raw = _retry_after_raw(headers)
    retry_after = _parse_retry_after(headers)
    if retry_after is not None:
        delay = max(retry_after, 1.0)
        retry_source = f"Retry-After={retry_after_raw!r} ({delay:.0f}s)"
    else:
        delay = RATE_LIMIT_429_BASE_SECONDS * (2**attempt)
        retry_source = f"no Retry-After header (backoff {delay:.0f}s)"
    if count >= CIRCUIT_BREAKER_429_THRESHOLD:
        delay = max(delay, CIRCUIT_BREAKER_429_COOLDOWN_SECONDS)
        log_line(
            f"[WARN] Rate limit circuit breaker: {count} consecutive 429s; "
            f"{retry_source}; sleeping {delay:.0f}s"
        )
    else:
        log_line(f"[WARN] HTTP 429; {retry_source}; sleeping {delay:.0f}s (attempt {attempt + 1})")
    time.sleep(delay)


def _note_success(rate_limiter: RateLimiter | None) -> None:
    global _consecutive_429_count
    with _consecutive_429_lock:
        _consecutive_429_count = 0
    if isinstance(rate_limiter, AdaptiveRateLimiter):
        rate_limiter.note_success()


def _fetch_cloudscraper(
    scraper: cloudscraper.CloudScraper,
    url: str,
) -> tuple[str | None, int | None, dict[str, str], str | None]:
    response: Response = scraper.get(url, timeout=REQUEST_TIMEOUT)
    headers = dict(response.headers)
    if response.status_code == 200:
        if is_cloudflare_rate_limited(response.text):
            return None, 429, headers, "Cloudflare rate limit (Error 1015)"
        if is_cloudflare_challenge(response.text):
            return None, 403, headers, "Cloudflare challenge page"
        return response.text, response.status_code, headers, None
    return None, response.status_code, headers, f"HTTP {response.status_code}"


def _fetch_curl_cffi(
    session: Any,
    url: str,
) -> tuple[str | None, int | None, dict[str, str], str | None]:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    headers = dict(response.headers)
    status = response.status_code
    if status == 200:
        text = response.text
        if is_cloudflare_rate_limited(text):
            return None, 429, headers, "Cloudflare rate limit (Error 1015)"
        if is_cloudflare_challenge(text):
            return None, 403, headers, "Cloudflare challenge page"
        return text, status, headers, None
    return None, status, headers, f"HTTP {status}"


def _fetch_playwright(url: str) -> tuple[str | None, int | None, dict[str, str], str | None]:
    from ygo_app.cardmarket.browser_client import BrowserSession

    if scrape_shutdown_requested():
        return None, None, {}, "Scrape interrupted"
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
            "rate limited",
            "error 1015",
            "1015",
            "err_http_response_code_failure",
        )
    )


def _is_cf_challenge_error(error: str | None) -> bool:
    if not error:
        return False
    lower = error.lower()
    return "cloudflare" in lower or "challenge" in lower


def _log_fetch_failure(
    url: str,
    status: int | None,
    error: str | None,
    attempt: int,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    retry_note = ""
    if status == 429:
        raw = _retry_after_raw(headers)
        if raw is not None:
            parsed = _parse_retry_after(headers)
            if parsed is not None:
                retry_note = f"; Retry-After={raw!r} ({parsed:.0f}s)"
            else:
                retry_note = f"; Retry-After={raw!r} (unparsed)"
        else:
            retry_note = "; Retry-After=(not set)"
    url_label = format_fetch_url(url)
    if status is not None:
        log_line(
            f"[WARN] HTTP {status} {url_label} "
            f"(attempt {attempt + 1})"
            + retry_note
            + (f" — {error}" if error and not error.startswith("HTTP ") else "")
        )
    elif error:
        log_line(f"[WARN] fetch failed {url_label}: {error} (attempt {attempt + 1})")


def _handle_block(
    *,
    url: str,
    status: int | None,
    error: str | None,
    attempt: int,
    retries: int,
    rate_limiter: RateLimiter | None,
    session_pool: SessionPool | CurlCffiSessionPool | None,
    worker_id: int,
    scraper: Any,
    backend: FetchBackend,
) -> tuple[Any, bool]:
    """Return (possibly refreshed scraper/session, should_continue)."""
    if isinstance(rate_limiter, AdaptiveRateLimiter):
        rate_limiter.note_block(reason=str(status or "cf"))

    _log_fetch_failure(url, status, error, attempt)
    if session_pool:
        session_pool.mark_403(worker_id)

    if attempt >= retries - 1:
        if status in (403, 429) or _is_cf_challenge_error(error):
            from ygo_app.cardmarket.browser_cookies import storage_has_cf_clearance

            if not storage_has_cf_clearance(_browser_cookie_storage_path()):
                log_line(f"[HINT] No cf_clearance cookies — run: {_CF_LOGIN_HINT}")
        return scraper, False

    if _is_cf_challenge_error(error):
        delay = CF_CHALLENGE_RETRY_DELAYS[min(attempt, len(CF_CHALLENGE_RETRY_DELAYS) - 1)]
        time.sleep(delay + random.uniform(0, 2))
    else:
        time.sleep(random.uniform(20, 30))

    if session_pool and scraper is not None and backend in ("cloudscraper", "curl_cffi"):
        scraper = session_pool.refresh(worker_id)
    return scraper, True


def fetch_url(
    scraper: cloudscraper.CloudScraper | Any | None,
    url: str,
    *,
    backend: FetchBackend = "cloudscraper",
    rate_limiter: RateLimiter | None = None,
    retries: int = MAX_RETRIES,
    jitter: float = 0.0,
    session_pool: SessionPool | CurlCffiSessionPool | None = None,
    worker_id: int = 0,
) -> tuple[str | None, str | None]:
    if backend == "cloudscraper" and scraper is None:
        scraper = create_scraper(worker_id)
    elif backend == "curl_cffi" and scraper is None:
        if session_pool is not None:
            scraper, _ = session_pool.get_session(worker_id)
        else:
            scraper = create_curl_cffi_session(worker_id)

    for attempt in range(retries):
        if scrape_shutdown_requested():
            return None, "Scrape interrupted"
        try:
            if rate_limiter:
                rate_limiter.acquire(jitter)

            if backend == "playwright":
                html, status, headers, error = _fetch_playwright(url)
            elif backend == "curl_cffi":
                assert scraper is not None
                html, status, headers, error = _fetch_curl_cffi(scraper, url)
            else:
                assert scraper is not None
                html, status, headers, error = _fetch_cloudscraper(scraper, url)

            if html and status == 200:
                if is_cloudflare_rate_limited(html):
                    if isinstance(rate_limiter, AdaptiveRateLimiter):
                        rate_limiter.note_block(reason="429")
                    _log_fetch_failure(url, 429, "Cloudflare rate limit (Error 1015)", attempt, headers=headers)
                    if attempt < retries - 1:
                        _sleep_for_429(attempt=attempt, headers=headers, html=html, error=error)
                        continue
                    return None, "Cloudflare rate limit (Error 1015)"
                _note_success(rate_limiter)
                if backend == "playwright":
                    sleep_inter_page_delay("playwright")
                return html, None

            if _looks_like_429(status=status, error=error):
                if isinstance(rate_limiter, AdaptiveRateLimiter):
                    rate_limiter.note_block(reason="429")
                _log_fetch_failure(url, status or 429, error, attempt, headers=headers)
                if attempt < retries - 1:
                    _sleep_for_429(attempt=attempt, headers=headers, html=html, error=error)
                    continue
                return None, error or "HTTP 429"

            if status == 403 or _is_cf_challenge_error(error):
                scraper, should_continue = _handle_block(
                    url=url,
                    status=status,
                    error=error,
                    attempt=attempt,
                    retries=retries,
                    rate_limiter=rate_limiter,
                    session_pool=session_pool,
                    worker_id=worker_id,
                    scraper=scraper,
                    backend=backend,
                )
                if should_continue:
                    continue
                return None, error or "HTTP 403"

            if status == 404:
                return None, "HTTP 404"

            if status in (500, 503):
                _log_fetch_failure(url, status, error, attempt)
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                return None, error or f"HTTP {status}"

            if status is not None or error:
                _log_fetch_failure(url, status, error, attempt)
            return None, error or (f"HTTP {status}" if status else "fetch failed")
        except cloudscraper.exceptions.CloudflareChallengeError as exc:
            error_msg = f"CloudflareError: {str(exc)[:100]}"
            log_line(
                f"[WARN] Cloudflare challenge (attempt {attempt + 1}/{retries}) {format_fetch_url(url)}"
            )
            scraper, should_continue = _handle_block(
                url=url,
                status=403,
                error=error_msg,
                attempt=attempt,
                retries=retries,
                rate_limiter=rate_limiter,
                session_pool=session_pool if backend in ("cloudscraper", "curl_cffi") else None,
                worker_id=worker_id,
                scraper=scraper,
                backend=backend,
            )
            if should_continue:
                continue
            return None, error_msg
        except Exception as exc:
            if isinstance(exc, RateLimitAbort):
                raise
            from ygo_app.cardmarket.browser_client import BrowserStartupError, format_fetch_error

            if isinstance(exc, BrowserStartupError):
                detail = str(exc)
                lower = detail.lower()
                if "rate-limited" in lower or "rate limit" in lower:
                    raise RateLimitAbort(
                        LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS,
                        detail,
                    ) from exc
                if attempt < retries - 1:
                    _log_fetch_failure(url, None, detail, attempt)
                    time.sleep(5)
                    continue
                log_line(f"[WARN] fetch failed {format_fetch_url(url)}: {detail}")
                return None, detail
            detail = format_fetch_error(exc)
            if attempt < retries - 1:
                _log_fetch_failure(url, None, detail, attempt)
                delay = random.uniform(*RETRY_DELAY_RANGE)
                time.sleep(delay)
                continue
            log_line(f"[WARN] fetch failed {format_fetch_url(url)}: {detail}")
            return None, detail
    return None, "max retries"
