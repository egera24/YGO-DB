"""Playwright browser backend for Cardmarket scraping."""

from __future__ import annotations

import os
import queue
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ygo_app import config
from ygo_app.cardmarket.browser_profiles import (
    DEFAULT_PROFILE_NAME,
    load_profile_state,
    profile_dir,
    profile_storage_path,
    save_profile_state,
    switch_active_profile,
)
from ygo_app.cardmarket.constants import BASE_URL, CARD_LIST_PROBE_URL, REQUEST_TIMEOUT, SEARCH_URL
from ygo_app.cardmarket.http_client import browser_headers, is_cloudflare_challenge, is_cloudflare_rate_limited, user_agent_for_worker
from ygo_app.cardmarket.paths import CARDMARKET_BROWSER_STATE_PATH
from ygo_app.cardmarket.url_log import format_fetch_url
from ygo_app.yugipedia.scrape_progress import log_line

_STOP = object()
_INSTALL_HINT = "python -m playwright install chromium"
_WARMUP_URL = f"{BASE_URL}/en/YuGiOh"
_WARMUP_SELECTOR = 'select[name="idExpansion"]'
_CF_WAIT_SELECTOR = f'{_WARMUP_SELECTOR}, a[href*="/YuGiOh/Products"]'

BrowserChannel = Literal["chrome", "msedge", "chromium"]

_headed = False
_storage_path: Path = CARDMARKET_BROWSER_STATE_PATH
_browser_channel: BrowserChannel | None = "chrome"
_cf_wait_seconds = 180
_profile_pool: list[str] = [DEFAULT_PROFILE_NAME]

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
"""

_CF_INCOMPATIBLE_MARKERS = (
    "incompatible browser extension",
    "challenges.cloudflare.com",
    "security verification",
)

_COOKIE_CONSENT_MARKERS = (
    "Cardmarket uses cookies",
    "Accept All Cookies",
    "Only Required Cookies",
)

_COOKIE_ACCEPT_SELECTORS = (
    'button:has-text("Accept All Cookies")',
    'button:has-text("Only Required Cookies")',
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
)


def configure_browser_session(
    *,
    headed: bool = False,
    storage_path: Path | None = None,
    browser_channel: BrowserChannel | None = None,
    cf_wait_seconds: int = 180,
    profile_pool: list[str] | None = None,
) -> None:
    global _headed, _storage_path, _browser_channel, _cf_wait_seconds, _profile_pool
    _headed = headed
    if profile_pool is not None:
        _profile_pool = profile_pool
    state = load_profile_state(pool=_profile_pool)
    if state.active in state.burned:
        from ygo_app.cardmarket.browser_profiles import next_available_profile

        nxt = next_available_profile(state)
        if nxt is not None:
            switch_active_profile(state, nxt)
    save_profile_state(state)
    _storage_path = storage_path or profile_storage_path(state.active)
    if browser_channel is not None:
        _browser_channel = browser_channel
    elif headed:
        _browser_channel = "chrome"
    _cf_wait_seconds = cf_wait_seconds


def format_fetch_error(exc: BaseException) -> str:
    """Readable error string; Playwright's exception class is literally named Error."""
    name = type(exc).__name__
    msg = str(exc).strip()
    if name == "Error" and msg:
        text = f"PlaywrightError: {msg[:200]}"
    elif msg:
        text = f"{name}: {msg[:200]}"
    else:
        text = name
    if "executable doesn't exist" in msg.lower() or "playwright install" in msg.lower():
        text = f"{text} — run: {_INSTALL_HINT}"
    return text


def _log_scrape_profile_rate_limit_hint() -> None:
    log_line(
        "[HINT] HTTP 429 / Error 1015 is usually an IP-level ban — rotating Chrome profiles "
        "on the same connection does not reset Cloudflare counters. "
        "Wait for Retry-After to expire, verify cardmarket.com in your normal browser, "
        "then resume with --polite --resume. See docs/cloudflare/README.md"
    )


def _wait_for_product_content(page, *, timeout_ms: int = 12_000) -> None:
    try:
        page.wait_for_selector('div[id^="productRow"]', timeout=timeout_ms)
    except Exception:
        try:
            page.wait_for_selector(_WARMUP_SELECTOR, timeout=3_000)
        except Exception:
            pass


def _accept_html_if_page_ready(
    page,
    url: str,
    html: str,
    headers: dict[str, str],
    *,
    http_status: int | None,
    reason: str,
) -> _FetchResult | None:
    """Use rendered DOM when Cardmarket loaded despite a non-200 HTTP status."""
    if _cardmarket_page_ready(page, html):
        return _FetchResult(html, 200, headers, None)
    return None


def _recover_page_after_goto_error(page, url: str, exc: BaseException) -> _FetchResult | None:
    """If Cardmarket loaded despite a Playwright goto error, return HTML anyway."""
    detail = str(exc)
    if type(exc).__name__ == "TargetClosedError" or (
        "closed" in detail.lower() and "target" in detail.lower()
    ):
        return None
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except Exception:
        pass
    _wait_for_product_content(page)
    try:
        html = page.content()
    except Exception:
        return None
    if not _cardmarket_page_ready(page, html):
        return None
    return _FetchResult(html, 200, {}, None)


def is_cf_incompatible_page(html: str | None) -> bool:
    if not html:
        return False
    lower = html.lower()
    # Match the actual Cloudflare error copy, not script URLs on normal Cardmarket pages.
    return "incompatible browser extension" in lower


def _log_cf_incompatible_help() -> None:
    log_line(
        "[HINT] Cloudflare challenge failed to load. If you see "
        "'Incompatible browser extension', disable ad blockers / privacy extensions "
        "for cardmarket.com and challenges.cloudflare.com, or try a different network."
    )


def _launch_channels_to_try(requested: BrowserChannel | None, *, headed: bool) -> list[str | None]:
    if requested == "chromium":
        return [None]
    if requested in ("chrome", "msedge"):
        return [requested, "msedge" if requested == "chrome" else "chrome", None]
    if headed:
        return ["chrome", "msedge", None]
    return [None]


def _launch_browser(playwright: Any, *, headed: bool, channel: BrowserChannel | None):
    launch_base: dict[str, Any] = {
        "headless": not headed,
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }
    proxy = config.CARDMARKET_HTTP_PROXY
    if proxy:
        launch_base["proxy"] = {"server": proxy}

    last_error: Exception | None = None
    for ch in _launch_channels_to_try(channel, headed=headed):
        kwargs = dict(launch_base)
        if ch:
            kwargs["channel"] = ch
        try:
            browser = playwright.chromium.launch(**kwargs)
            label = ch or "chromium"
            log_line(f"[BROWSER] launched {label} ({'headed' if headed else 'headless'})")
            return browser
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(
        f"Could not launch browser (tried channels: chrome/msedge/chromium): {last_error}"
    )


def _new_context(browser: Any, *, storage_path: Path):
    ua = user_agent_for_worker(0)
    context_kwargs: dict[str, Any] = {
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "Europe/Berlin",
        "user_agent": ua,
        "extra_http_headers": {
            k: v for k, v in browser_headers(ua).items() if k.lower() != "user-agent"
        },
    }
    if storage_path.is_file():
        context_kwargs["storage_state"] = str(storage_path)
    context = browser.new_context(**context_kwargs)
    context.add_init_script(_STEALTH_INIT_SCRIPT)
    return context


_CF_LOGIN_PAGE_READY_GRACE_SECONDS = 15

CfLoginWaitResult = Literal["cf_clearance", "page_ready", "timeout", "closed"]


def _browser_executable(channel: BrowserChannel | None) -> str | None:
    if channel == "msedge":
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Microsoft/Edge/Application/msedge.exe",
        ]
    else:
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _connect_cdp_browser(playwright: Any, port: int, *, timeout_seconds: float = 30):
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"CDP connect failed on port {port}: {last_error}")


def _close_browser_handles(
    *,
    page: Any | None,
    context: Any | None,
    browser: Any | None,
    cdp_proc: subprocess.Popen[Any] | None,
) -> None:
    if cdp_proc is not None:
        _terminate_process(cdp_proc)
    for closer in (page, context, browser):
        if closer is None:
            continue
        try:
            closer.close()
        except Exception:
            pass


def _launch_headed_cdp_browser(
    playwright: Any,
    channel: BrowserChannel | None,
    *,
    chrome_profile_dir: Path,
    profile_name: str,
):
    """Launch real Chrome/Edge and attach via CDP (avoids Playwright automation detection)."""
    exe = _browser_executable(channel or "chrome")
    if not exe:
        label = channel or "chrome"
        raise RuntimeError(f"Could not find {label} executable on this machine.")

    chrome_profile_dir.mkdir(parents=True, exist_ok=True)
    port = _pick_free_port()
    browser_label = channel or "chrome"
    log_line(
        f"[BROWSER] launching real {browser_label} via CDP (headed) profile={profile_name}"
    )

    proc = subprocess.Popen(
        [
            exe,
            f"--user-data-dir={chrome_profile_dir}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            _WARMUP_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    if proc.poll() is not None:
        raise RuntimeError(
            "Chrome exited immediately. Close any other Cardmarket scrape Chrome window "
            f"(profile: {chrome_profile_dir}) and retry."
        )
    browser = _connect_cdp_browser(playwright, port, timeout_seconds=60)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = _cardmarket_page_for_context(context, target_url=_WARMUP_URL)
    return browser, context, page, proc


def _cardmarket_page_for_context(context: Any, *, target_url: str):
    for page in context.pages:
        if "cardmarket.com" in page.url:
            return page
    if context.pages:
        return context.pages[0]
    page = context.new_page()
    page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    return page


def _page_needs_cookie_consent(page, html: str | None = None) -> bool:
    """True only when the cookie banner buttons are still visible."""
    del html  # banner visibility is authoritative; footer text mentions cookies on every page
    try:
        for selector in _COOKIE_ACCEPT_SELECTORS:
            if page.locator(selector).first.is_visible(timeout=500):
                return True
        if page.get_by_role("button", name="Accept All Cookies").is_visible(timeout=500):
            return True
    except Exception:
        pass
    return False


def _dismiss_cookie_consent(page) -> bool:
    """Click Cardmarket cookie banner when visible. Returns True if dismissed."""
    if not _page_needs_cookie_consent(page):
        return False
    for selector in _COOKIE_ACCEPT_SELECTORS:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=1_500):
                button.click(timeout=5_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    except Exception:
                        pass
                if not _page_needs_cookie_consent(page):
                    log_line("[BROWSER] accepted cookie consent")
                    return True
        except Exception:
            continue
    try:
        button = page.get_by_role("button", name="Accept All Cookies")
        if button.is_visible(timeout=1_000):
            button.click(timeout=5_000)
            if not _page_needs_cookie_consent(page):
                log_line("[BROWSER] accepted cookie consent")
                return True
    except Exception:
        pass
    return False


def _cardmarket_page_ready(page, html: str | None) -> bool:
    """True when Cloudflare is cleared and Cardmarket content is visible."""
    if html is None:
        try:
            html = page.content()
        except Exception:
            return False
    lower = html.lower()
    if is_cloudflare_challenge(html) or is_cf_incompatible_page(html):
        return False
    if _page_needs_cookie_consent(page, html):
        return False
    if "price trend" in lower and ("30-day" in lower or "7-day" in lower):
        return True
    if any(
        marker in html
        for marker in (
            "productRow",
            "Search Results",
            "Sorry, no matches",
            'name="idExpansion"',
        )
    ):
        return True
    try:
        if page.locator(_WARMUP_SELECTOR).count() > 0:
            return True
        if page.locator('div[id^="productRow"]').count() > 0:
            return True
    except Exception:
        pass
    return False


def _cookies_have_cf_clearance(page) -> bool:
    try:
        return any(c.get("name") == "cf_clearance" for c in page.context.cookies())
    except Exception:
        return False


def _wait_for_cf_clearance(page, *, timeout_seconds: int) -> bool:
    log_line(
        f"[CF-WAIT] Waiting for Cardmarket to finish loading in the browser "
        f"(up to {timeout_seconds}s)..."
    )
    if _headed:
        log_line(
            "[CF-WAIT] If you see a cookie banner or unstyled page, click "
            "'Accept All Cookies' — the script will also try automatically."
        )
    deadline = time.time() + timeout_seconds
    last_hint_at = 0.0
    while time.time() < deadline:
        if _cookies_have_cf_clearance(page):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            try:
                cookie_html = page.content()
            except Exception:
                cookie_html = None
            if cookie_html and _cardmarket_page_ready(page, cookie_html):
                return True

        html: str | None = None
        try:
            html = page.content()
        except Exception as exc:
            detail = str(exc).lower()
            if type(exc).__name__ == "TargetClosedError" or (
                "closed" in detail and "navigating" not in detail
            ):
                return False
            if "navigating" in detail or "unable to retrieve content" in detail:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
                time.sleep(1)
                continue
            time.sleep(1)
            continue

        if _page_needs_cookie_consent(page, html):
            if _dismiss_cookie_consent(page):
                html = page.content()
            elif _headed and time.time() - last_hint_at >= 20:
                log_line(
                    "[CF-WAIT] Cookie consent is blocking the page — click "
                    "'Accept All Cookies' in the browser window."
                )
                last_hint_at = time.time()

        if is_cf_incompatible_page(html):
            if time.time() - last_hint_at >= 30:
                _log_cf_incompatible_help()
                last_hint_at = time.time()
        if _cardmarket_page_ready(page, html):
            return True
        time.sleep(2)
    return False


def _wait_for_cf_login(page, *, timeout_seconds: int) -> CfLoginWaitResult:
    """Wait for cf_clearance, or page-ready without a visible challenge."""
    log_line(
        f"[CF-WAIT] Waiting for Cardmarket to load or Cloudflare verification "
        f"(up to {timeout_seconds}s)..."
    )
    deadline = time.time() + timeout_seconds
    last_hint_at = 0.0
    page_ready_since: float | None = None
    while time.time() < deadline:
        if _cookies_have_cf_clearance(page):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            return "cf_clearance"

        html: str | None = None
        try:
            html = page.content()
        except Exception as exc:
            detail = str(exc).lower()
            if type(exc).__name__ == "TargetClosedError" or (
                "closed" in detail and "navigating" not in detail
            ):
                return "closed"
            if "navigating" in detail or "unable to retrieve content" in detail:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
                time.sleep(1)
                continue
            time.sleep(1)
            continue

        if is_cf_incompatible_page(html):
            if time.time() - last_hint_at >= 30:
                _log_cf_incompatible_help()
                last_hint_at = time.time()

        if _cardmarket_page_ready(page, html):
            if page_ready_since is None:
                page_ready_since = time.time()
                log_line(
                    "[CF-WAIT] Cardmarket loaded in Chrome. If no Cloudflare check appears, "
                    "that is normal — waiting briefly, then testing automated access..."
                )
            elif (
                time.time() - page_ready_since >= _CF_LOGIN_PAGE_READY_GRACE_SECONDS
            ):
                return "page_ready"
        else:
            page_ready_since = None
        time.sleep(2)
    return "timeout"


def run_cf_login(
    *,
    storage_path: Path | None = None,
    browser_channel: BrowserChannel | None = "chrome",
    timeout_seconds: int = 300,
    profile_pool: list[str] | None = None,
) -> int:
    """Launch real Chrome/Edge (CDP), wait for manual Cloudflare solve, save cookies."""
    from playwright.sync_api import sync_playwright

    pool = profile_pool or _profile_pool
    state = load_profile_state(pool=pool)
    active = state.active
    switch_active_profile(state, active)
    save_profile_state(state)
    effective_storage = storage_path or profile_storage_path(active)
    chrome_profile_dir = profile_dir(active)

    exe = _browser_executable(browser_channel)
    if not exe:
        label = browser_channel or "chrome"
        log_line(f"[ERROR] Could not find {label} executable on this machine.")
        return 1

    port = _pick_free_port()
    browser_label = browser_channel or "chrome"

    log_line(
        f"[CF-LOGIN] Launching real {browser_label} (profile={active}) "
        f"on the product search page..."
    )
    log_line(
        "[CF-LOGIN] Open Cardmarket in Chrome. Complete any Cloudflare check if one appears; "
        "if the search page loads with no challenge, wait — the script will test access automatically."
    )

    proc = subprocess.Popen(
        [
            exe,
            f"--user-data-dir={chrome_profile_dir}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            SEARCH_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        with sync_playwright() as playwright:
            try:
                browser = _connect_cdp_browser(playwright, port)
            except RuntimeError as exc:
                log_line(f"[ERROR] {exc}")
                return 1

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = _cardmarket_page_for_context(context, target_url=SEARCH_URL)

            wait_result = _wait_for_cf_login(page, timeout_seconds=timeout_seconds)
            if wait_result in ("timeout", "closed"):
                log_line("[ERROR] Timed out waiting for Cardmarket to load in Chrome.")
                _log_cf_incompatible_help()
                return 1

            effective_storage.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(effective_storage))
            saved_names = [c.get("name") for c in context.cookies() if c.get("name")]
            has_cf = "cf_clearance" in saved_names
            log_line(f"[CF-LOGIN] Saved session to {effective_storage}")

            from ygo_app.cardmarket.http_client import probe_curl_cffi_session

            probe_ok, probe_status, probe_error = probe_curl_cffi_session(
                effective_storage, CARD_LIST_PROBE_URL
            )

            if probe_ok:
                if has_cf:
                    log_line("[CF-LOGIN] cf_clearance captured — curl_cffi scrape should work.")
                else:
                    log_line(
                        "[CF-LOGIN] No cf_clearance cookie, but curl_cffi probe succeeded — "
                        "you can scrape with the default backend."
                    )
                log_line(
                    "[CF-LOGIN] You can now scrape with: "
                    "python -m ygo_app.jobs.scrape_cardmarket_card_list --limit 5"
                )
                return 0

            log_line(
                f"[CF-LOGIN] curl_cffi probe failed ({probe_error or probe_status}). "
                "Chrome can browse Cardmarket, but automated HTTP cannot reuse that session."
            )
            if wait_result == "page_ready" and not has_cf:
                log_line(
                    "[HINT] No Cloudflare challenge appeared — cf_clearance was never issued. "
                    "Use real-browser scraping instead:"
                )
            log_line(
                "[HINT] python -m ygo_app.jobs.scrape_cardmarket_card_list "
                "--browser --headed --workers 1 --resume"
            )
            return 1
    finally:
        _terminate_process(proc)


@dataclass
class _FetchResult:
    html: str | None
    status: int | None
    headers: dict[str, str]
    error: str | None


class BrowserStartupError(RuntimeError):
    """Raised when the Playwright worker cannot launch Chromium."""


class BrowserSession:
    """Process-wide singleton; Playwright sync API runs on a dedicated worker thread."""

    _instance: BrowserSession | None = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._command_queue: queue.Queue[Any] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._ready_event = threading.Event()
        self._ready = False
        self._startup_error: str | None = None
        self._startup_abort: BaseException | None = None
        self._worker_started = False

    @classmethod
    def get(cls) -> BrowserSession:
        from ygo_app.cardmarket.http_client import ScrapeShutdown, scrape_shutdown_requested

        if scrape_shutdown_requested():
            raise ScrapeShutdown("Scrape interrupted")
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_worker(self) -> None:
        with self._start_lock:
            if self._ready:
                return
            if self._startup_abort is not None:
                raise self._startup_abort
            if self._startup_error:
                raise BrowserStartupError(self._startup_error)
            if not self._worker_started:
                self._ready_event.clear()
                self._worker = threading.Thread(
                    target=self._worker_loop,
                    name="cardmarket-playwright",
                    daemon=True,
                )
                self._worker.start()
                self._worker_started = True

        if not self._ready_event.wait(timeout=180):
            raise BrowserStartupError(
                f"Playwright worker timed out during startup — try: {_INSTALL_HINT}"
            )
        with self._start_lock:
            if self._startup_abort is not None:
                raise self._startup_abort
            if self._startup_error:
                raise BrowserStartupError(self._startup_error)

    def _fail_startup(self, exc: BaseException) -> None:
        from ygo_app.cardmarket.http_client import RateLimitAbort

        if isinstance(exc, RateLimitAbort):
            with self._start_lock:
                self._startup_abort = exc
            log_line(f"[ERROR] browser startup failed: {exc}")
            self._ready_event.set()
            return
        detail = format_fetch_error(exc)
        with self._start_lock:
            self._startup_error = detail
        log_line(f"[ERROR] browser startup failed: {detail}")
        self._ready_event.set()

    def _warmup_page_after_launch(self, page) -> _FetchResult:
        """Reuse the CDP landing tab when possible (avoid a duplicate warmup goto)."""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        try:
            html = page.content()
        except Exception as exc:
            return _FetchResult(None, None, {}, format_fetch_error(exc))

        if is_cloudflare_rate_limited(html):
            return _FetchResult(None, 429, {}, "Cloudflare rate limit (Error 1015)")
        if _cardmarket_page_ready(page, html):
            return _FetchResult(html, 200, {}, None)
        return self._navigate_page(page, _WARMUP_URL)

    def _save_storage_state(self, context) -> None:
        try:
            _storage_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(_storage_path))
        except Exception as exc:
            log_line(f"[WARN] failed to save browser state: {format_fetch_error(exc)}")

    def _navigate_page(self, page, url: str) -> _FetchResult:
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=REQUEST_TIMEOUT * 1000,
            )
            status = response.status if response is not None else None
            html = page.content()
            headers: dict[str, str] = {}
            if response is not None:
                headers = dict(response.headers)

            if _page_needs_cookie_consent(page, html):
                if _dismiss_cookie_consent(page):
                    html = page.content()
                elif _headed and not _cardmarket_page_ready(page, html):
                    log_line(
                        "[BROWSER] Cookie consent visible — click 'Accept All Cookies' "
                        "if the page stays unstyled."
                    )
                    if _wait_for_cf_clearance(page, timeout_seconds=60):
                        html = page.content()

            if is_cf_incompatible_page(html):
                _log_cf_incompatible_help()
                if _headed and _wait_for_cf_clearance(page, timeout_seconds=_cf_wait_seconds):
                    html = page.content()
                    status = 200
                else:
                    return _FetchResult(None, 403, headers, "Cloudflare incompatible browser page")

            if status == 200 and is_cloudflare_rate_limited(html):
                return _FetchResult(None, 429, headers, "Cloudflare rate limit (Error 1015)")

            if status == 200 and is_cloudflare_challenge(html):
                if _headed and _wait_for_cf_clearance(page, timeout_seconds=_cf_wait_seconds):
                    html = page.content()
                    if is_cloudflare_rate_limited(html):
                        return _FetchResult(None, 429, headers, "Cloudflare rate limit (Error 1015)")
                    if is_cloudflare_challenge(html):
                        return _FetchResult(None, 403, headers, "Cloudflare challenge page")
                else:
                    return _FetchResult(None, 403, headers, "Cloudflare challenge page")
            if status == 200 and not _cardmarket_page_ready(page, html):
                if _headed:
                    if _wait_for_cf_clearance(page, timeout_seconds=60):
                        html = page.content()
                    else:
                        return _FetchResult(
                            None,
                            403,
                            headers,
                            "Cardmarket page did not finish loading (cookie consent or challenge)",
                        )
                else:
                    return _FetchResult(
                        None,
                        403,
                        headers,
                        "Cardmarket page did not finish loading",
                    )
            if status == 200 and "/Products/Singles/" in url:
                lower_detail = (html or "").lower()
                if "price trend" not in lower_detail:
                    if _headed and _wait_for_cf_clearance(
                        page, timeout_seconds=_cf_wait_seconds
                    ):
                        html = page.content()
                        lower_detail = (html or "").lower()
                    if "price trend" not in lower_detail:
                        return _FetchResult(
                            None,
                            403,
                            headers,
                            "Product detail page missing price data (challenge or load failure)",
                        )
            if status == 200:
                return _FetchResult(html, status, headers, None)
            accepted = _accept_html_if_page_ready(
                page, url, html, headers, http_status=status, reason="non_200_status"
            )
            if accepted is not None:
                return accepted
            return _FetchResult(None, status, headers, f"HTTP {status}")
        except Exception as exc:
            recovered = _recover_page_after_goto_error(page, url, exc)
            if recovered is not None:
                return recovered
            return _FetchResult(None, None, {}, format_fetch_error(exc))

    def _worker_loop(self) -> None:
        from playwright.sync_api import sync_playwright

        playwright = None
        browser = None
        context = None
        page = None
        cdp_proc: subprocess.Popen[Any] | None = None
        profile_state = load_profile_state(pool=_profile_pool)
        try:
            playwright = sync_playwright().start()

            while True:
                active_name = profile_state.active
                switch_active_profile(profile_state, active_name)
                save_profile_state(profile_state)
                global _storage_path
                _storage_path = profile_storage_path(active_name)
                chrome_profile_dir = profile_dir(active_name)

                browser = None
                context = None
                page = None
                cdp_proc = None

                if _headed and _browser_executable(_browser_channel or "chrome"):
                    browser, context, page, cdp_proc = _launch_headed_cdp_browser(
                        playwright,
                        _browser_channel,
                        chrome_profile_dir=chrome_profile_dir,
                        profile_name=active_name,
                    )
                else:
                    browser = _launch_browser(
                        playwright,
                        headed=_headed,
                        channel=_browser_channel,
                    )
                    context = _new_context(browser, storage_path=_storage_path)
                    page = context.new_page()

                warmup_result = self._warmup_page_after_launch(page)
                if not warmup_result.error:
                    self._save_storage_state(context)
                    break

                log_line(f"[WARN] browser warmup: {warmup_result.error} {_WARMUP_URL}")
                is_429 = warmup_result.status == 429 or (
                    warmup_result.error is not None and "429" in warmup_result.error
                )
                _close_browser_handles(
                    page=page, context=context, browser=browser, cdp_proc=cdp_proc
                )
                browser = context = page = None
                cdp_proc = None

                if is_429:
                    # IP-level ban: rotating profiles on the same connection adds requests
                    # without bypassing Cloudflare counters (see docs/cloudflare/README.md).
                    _log_scrape_profile_rate_limit_hint()
                    from ygo_app.cardmarket.constants import LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS
                    from ygo_app.cardmarket.http_client import RateLimitAbort, log_rate_limit_recovery

                    log_rate_limit_recovery(LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS)
                    self._fail_startup(
                        RateLimitAbort(
                            LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS,
                            "IP rate limited during browser warmup",
                        )
                    )
                    return

                self._fail_startup(
                    RuntimeError(
                        warmup_result.error
                        or f"Browser warmup failed with HTTP {warmup_result.status}"
                    )
                )
                return

            time.sleep(2)

            with self._start_lock:
                self._ready = True
            self._ready_event.set()

            while True:
                item = self._command_queue.get()
                if item is _STOP:
                    break
                url, result_queue = item
                result = self._navigate_page(page, url)
                if result.error:
                    log_line(f"[WARN] browser fetch failed {format_fetch_url(url)}: {result.error}")
                elif result.status == 200:
                    log_line(f"[FETCH] OK {format_fetch_url(url)}")
                    self._save_storage_state(context)
                result_queue.put(result)
        except Exception as exc:
            self._fail_startup(exc)
            return
        finally:
            if context is not None and self._ready:
                try:
                    self._save_storage_state(context)
                except Exception:
                    pass
            _close_browser_handles(
                page=page, context=context, browser=browser, cdp_proc=cdp_proc
            )
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            if self._ready:
                log_line("[BROWSER] Playwright session closed")

    def fetch(self, url: str) -> tuple[str | None, int | None, dict[str, str], str | None]:
        """Return (html, status_code, response_headers, error)."""
        from ygo_app.cardmarket.http_client import scrape_shutdown_requested

        if scrape_shutdown_requested():
            return None, None, {}, "Scrape interrupted"
        self._ensure_worker()
        result_queue: queue.Queue[_FetchResult] = queue.Queue(maxsize=1)
        self._command_queue.put((url, result_queue))
        result = result_queue.get()
        return result.html, result.status, result.headers, result.error

    def close(self) -> None:
        with self._start_lock:
            if not self._worker_started:
                return
            if self._ready:
                self._command_queue.put(_STOP)
            if self._worker is not None:
                self._worker.join(timeout=30)
            self._worker = None
            self._worker_started = False
            self._ready = False
            self._startup_error = None
            self._startup_abort = None
            self._ready_event.clear()


def close_browser_session() -> None:
    with BrowserSession._class_lock:
        if BrowserSession._instance is not None:
            BrowserSession._instance.close()
            BrowserSession._instance = None
