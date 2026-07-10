"""HTTP client with rate limiting and retries for Yugipedia wiki pages."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import cloudscraper
import requests

from ygo_app.yugipedia.constants import (
    MAX_RETRIES,
    MIN_REQUEST_INTERVAL,
    PARSE_BATCH_SIZE,
    REQUEST_TIMEOUT,
    RETRY_DELAYS,
    REVISION_BATCH_SIZE,
    SLOW_REQUEST_WARN_SECONDS,
    USER_AGENT,
    WIKI_MAXLAG,
)
from ygo_app.yugipedia.scrape_progress import log_line

YUGIPEDIA_API_URL = "https://yugipedia.com/api.php"
YUGIPEDIA_WIKI_HOST = "yugipedia.com"


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


@dataclass(frozen=True)
class PageFetchResult:
    html: str | None
    revid: int | None
    touched: str | None
    error: str | None


def normalize_wiki_title(title: str) -> str:
    """Unify spaces/underscores for matching API titles to URL-derived titles."""
    return title.replace("_", " ").strip()


def _api_base_params() -> dict:
    return {"format": "json", "maxlag": WIKI_MAXLAG}


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _titles_param(titles: list[str]) -> str:
    return "|".join(titles)


def _parse_api_error(data: dict) -> tuple[str | None, float | None]:
    """Return (error_code, maxlag_seconds) when response JSON contains an error."""
    err = data.get("error") or {}
    code = err.get("code")
    if not code:
        return None, None
    lag = err.get("lag")
    try:
        lag_val = float(lag) if lag is not None else None
    except (TypeError, ValueError):
        lag_val = None
    return str(code), lag_val


def _retry_sleep(*, attempt: int, response=None, api_lag: float | None = None) -> None:
    if api_lag is not None:
        time.sleep(max(api_lag, 5.0) + random.uniform(0, 1))
        return
    if response is not None and getattr(response, "status_code", None) == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                time.sleep(float(retry_after) + random.uniform(0, 1))
                return
            except ValueError:
                pass
    time.sleep(RETRY_DELAYS[attempt] + random.uniform(0, 2))


def _page_meta_from_query_page(page: dict) -> tuple[int | None, str | None]:
    revid = page.get("lastrevid")
    if revid is None:
        revisions = page.get("revisions") or []
        if revisions:
            revid = revisions[0].get("revid")
    touched = page.get("touched")
    if touched is None and page.get("revisions"):
        touched = page["revisions"][0].get("timestamp")
    return revid, touched


def _is_retryable_api_code(code: str | None) -> bool:
    if not code:
        return False
    lower = code.lower()
    return lower in ("maxlag", "readonly", "ratelimited") or "429" in lower


def fetch_current_revisions(
    session: requests.Session,
    titles: list[str],
    *,
    batch_size: int = REVISION_BATCH_SIZE,
    retries: int = MAX_RETRIES,
    timeout: float = REQUEST_TIMEOUT,
) -> dict[str, dict[str, int | str | None]]:
    """Return {title: {revid, touched}} for wiki titles (missing pages omitted)."""
    if not titles:
        return {}

    out: dict[str, dict[str, int | str | None]] = {}
    for chunk in _chunked(titles, batch_size):
        label = f"{len(chunk)} titles"
        for attempt in range(retries):
            started = time.monotonic()
            try:
                _rate_limiter.acquire()
                response = session.get(
                    YUGIPEDIA_API_URL,
                    params={
                        **_api_base_params(),
                        "action": "query",
                        "prop": "revisions",
                        "rvprop": "ids|timestamp",
                        "titles": _titles_param(chunk),
                    },
                    timeout=timeout,
                )
                elapsed = time.monotonic() - started
                if elapsed >= SLOW_REQUEST_WARN_SECONDS:
                    log_line(
                        f"[WARN] Slow revision query {elapsed:.1f}s "
                        f"(attempt {attempt + 1}/{retries}) {label}"
                    )
                response.raise_for_status()
                data = response.json()
                code, lag = _parse_api_error(data)
                if code and _is_retryable_api_code(code) and attempt < retries - 1:
                    log_line(
                        f"[WARN] Retryable revision query {code} "
                        f"(attempt {attempt + 1}/{retries}) {label}"
                    )
                    _retry_sleep(attempt=attempt, response=response, api_lag=lag)
                    continue
                if code:
                    log_line(f"[WARN] Revision query failed: {code} {label}")
                    break
                pages = data.get("query", {}).get("pages", {})
                for page in pages.values():
                    if "missing" in page:
                        continue
                    title = page.get("title")
                    if not title:
                        continue
                    revid, touched = _page_meta_from_query_page(page)
                    out[title] = {"revid": revid, "touched": touched}
                break
            except Exception as e:
                error_type = type(e).__name__
                error_str = str(e)
                resp = getattr(e, "response", None)
                if (
                    _is_retryable_error(error_type, error_str)
                    or (resp is not None and getattr(resp, "status_code", None) == 429)
                ) and attempt < retries - 1:
                    log_line(
                        f"[WARN] Retryable revision query {error_type} "
                        f"(attempt {attempt + 1}/{retries}) {label}"
                    )
                    _retry_sleep(attempt=attempt, response=resp)
                    continue
                log_line(f"[WARN] Revision query failed for {label}: {error_str[:80]}")
                break
    return out


def fetch_pages_batch(
    session: requests.Session,
    titles: list[str],
    *,
    batch_size: int = PARSE_BATCH_SIZE,
    retries: int = MAX_RETRIES,
    timeout: float = REQUEST_TIMEOUT,
) -> dict[str, PageFetchResult]:
    """Fetch rendered HTML for up to batch_size titles per API request."""
    if not titles:
        return {}

    results: dict[str, PageFetchResult] = {}
    for chunk in _chunked(titles, batch_size):
        label = f"{len(chunk)} titles"
        chunk_set = set(chunk)
        for attempt in range(retries):
            started = time.monotonic()
            try:
                _rate_limiter.acquire()
                response = session.get(
                    YUGIPEDIA_API_URL,
                    params={
                        **_api_base_params(),
                        "action": "query",
                        "prop": "parse|revisions",
                        "parseprop": "text",
                        "rvprop": "ids|timestamp",
                        "redirects": "1",
                        "titles": _titles_param(chunk),
                    },
                    timeout=timeout,
                )
                elapsed = time.monotonic() - started
                if elapsed >= SLOW_REQUEST_WARN_SECONDS:
                    log_line(
                        f"[WARN] Slow batch parse {elapsed:.1f}s "
                        f"(attempt {attempt + 1}/{retries}) {label}"
                    )
                response.raise_for_status()
                data = response.json()
                code, lag = _parse_api_error(data)
                if code and _is_retryable_api_code(code) and attempt < retries - 1:
                    log_line(
                        f"[WARN] Retryable batch parse {code} "
                        f"(attempt {attempt + 1}/{retries}) {label}"
                    )
                    _retry_sleep(attempt=attempt, response=response, api_lag=lag)
                    continue
                if code:
                    err = f"ParseApiError: {code}"
                    for title in chunk_set:
                        results[title] = PageFetchResult(
                            html=None, revid=None, touched=None, error=err
                        )
                    break

                pages = data.get("query", {}).get("pages", {})
                seen: set[str] = set()
                for page in pages.values():
                    title = page.get("title")
                    if not title:
                        continue
                    seen.add(title)
                    if "missing" in page:
                        results[title] = PageFetchResult(
                            html=None,
                            revid=None,
                            touched=None,
                            error="MissingPage",
                        )
                        continue
                    revid, touched = _page_meta_from_query_page(page)
                    parse_block = page.get("parse") or {}
                    html = parse_block.get("text", {}).get("*", "") or None
                    if not html:
                        results[title] = PageFetchResult(
                            html=None,
                            revid=revid,
                            touched=touched,
                            error="ParseApiError: empty parse in batch response",
                        )
                    else:
                        results[title] = PageFetchResult(
                            html=html,
                            revid=revid or parse_block.get("revid"),
                            touched=touched,
                            error=None,
                        )

                for title in chunk_set - seen:
                    results[title] = PageFetchResult(
                        html=None,
                        revid=None,
                        touched=None,
                        error="ParseApiError: title absent from batch response",
                    )
                break
            except Exception as e:
                error_type = type(e).__name__
                error_str = str(e)
                resp = getattr(e, "response", None)
                retryable = _is_retryable_error(error_type, error_str) or (
                    resp is not None and getattr(resp, "status_code", None) == 429
                )
                if retryable and attempt < retries - 1:
                    log_line(
                        f"[WARN] Retryable batch parse {error_type} "
                        f"(attempt {attempt + 1}/{retries}) {label}"
                    )
                    _retry_sleep(attempt=attempt, response=resp)
                    continue
                err = f"{error_type}: {error_str[:100]}"
                for title in chunk_set:
                    results[title] = PageFetchResult(
                        html=None, revid=None, touched=None, error=err
                    )
                break
    return results


def _response_log_fields(response) -> dict:
    if response is None:
        return {"has_response": False, "status_code": None, "body_bytes_read": 0}
    content = getattr(response, "content", b"") or b""
    return {
        "has_response": True,
        "status_code": getattr(response, "status_code", None),
        "body_bytes_read": len(content),
    }


def _is_retryable_error(error_type: str, error_str: str) -> bool:
    return any(
        [
            "429" in error_str,
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


def wiki_title_from_url(url: str) -> str | None:
    """Return a MediaWiki page title from a Yugipedia wiki URL, or None."""
    if not url:
        return None
    parsed = urlparse(url.split("#", 1)[0])
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = parsed.path or ""
    if host and host != YUGIPEDIA_WIKI_HOST:
        return None
    prefix = "/wiki/"
    if not path.startswith(prefix):
        return None
    title = unquote(path[len(prefix) :]).strip()
    return title or None


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        }
    )
    return session


def create_scraper() -> cloudscraper.CloudScraper:
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    scraper.headers.update({"User-Agent": USER_AGENT})
    return scraper


def _extract_parse_html(data: dict) -> str | None:
    if data.get("error"):
        return None
    html = data.get("parse", {}).get("text", {}).get("*", "")
    return html if html else None


def _fetch_via_parse(
    session: requests.Session,
    title: str,
    *,
    retries: int = MAX_RETRIES,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[str | None, str | None]:
    batch = fetch_pages_batch(session, [title], batch_size=1, retries=retries, timeout=timeout)
    result = batch.get(title)
    if result is None:
        for api_title, fetch in batch.items():
            if normalize_wiki_title(api_title) == normalize_wiki_title(title):
                result = fetch
                break
    if result is None:
        return None, "ParseApiError: no response"
    return result.html, result.error


def _fetch_via_wiki_url(
    scraper: cloudscraper.CloudScraper,
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
            status_part = (
                f" status={resp_fields['status_code']} bytes={resp_fields['body_bytes_read']}"
                if resp_fields["has_response"]
                else " no_response"
            )
            if _is_retryable_error(error_type, error_str) and attempt < retries - 1:
                log_line(
                    f"[WARN] Retryable {error_type} (attempt {attempt + 1}/{retries}) "
                    f"elapsed={elapsed:.1f}s{status_part} {url[:60]}"
                )
                time.sleep(RETRY_DELAYS[attempt] + random.uniform(0, 2))
                continue
            return None, f"{error_type}: {error_str[:100]}"
    return None, f"Failed after {retries} retry attempts"


def fetch_page(
    client,
    url: str,
    *,
    retries: int = MAX_RETRIES,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[str | None, str | None]:
    """Fetch rendered wiki HTML via MediaWiki parse API, with wiki URL fallback."""
    title = wiki_title_from_url(url)
    if title is not None and isinstance(client, requests.Session):
        html, error = _fetch_via_parse(client, title, retries=retries, timeout=timeout)
        if html:
            return html, None
        log_line(
            f"[WARN] parse failed for {title[:60]}; falling back to wiki URL"
            + (f" — {error}" if error else "")
        )

    scraper = (
        client
        if isinstance(client, cloudscraper.CloudScraper)
        else create_scraper()
    )
    return _fetch_via_wiki_url(scraper, url, retries=retries, timeout=timeout)
