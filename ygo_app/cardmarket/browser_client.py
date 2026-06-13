"""Playwright browser backend for Cardmarket scraping."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from ygo_app.cardmarket.constants import BASE_URL, REQUEST_TIMEOUT, USER_AGENT
from ygo_app.yugipedia.scrape_progress import log_line

_STOP = object()
_INSTALL_HINT = "python -m playwright install chromium"


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
        self._worker_started = False

    @classmethod
    def get(cls) -> BrowserSession:
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_worker(self) -> None:
        with self._start_lock:
            if self._ready:
                return
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

        if not self._ready_event.wait(timeout=120):
            raise BrowserStartupError(
                f"Playwright worker timed out during startup — try: {_INSTALL_HINT}"
            )
        with self._start_lock:
            if self._startup_error:
                raise BrowserStartupError(self._startup_error)

    def _fail_startup(self, exc: BaseException) -> None:
        detail = format_fetch_error(exc)
        with self._start_lock:
            self._startup_error = detail
        log_line(f"[ERROR] browser startup failed: {detail}")
        self._ready_event.set()

    def _worker_loop(self) -> None:
        from playwright.sync_api import sync_playwright

        playwright = None
        browser = None
        context = None
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Europe/Berlin",
                user_agent=USER_AGENT,
            )
            request = context.request
            try:
                warmup = request.get(f"{BASE_URL}/en/YuGiOh", timeout=15_000)
                if warmup.status != 200:
                    log_line(
                        f"[WARN] browser warmup HTTP {warmup.status} "
                        f"{BASE_URL}/en/YuGiOh"
                    )
                time.sleep(2)
            except Exception as exc:
                log_line(f"[WARN] browser warmup failed: {format_fetch_error(exc)}")

            with self._start_lock:
                self._ready = True
            self._ready_event.set()
            log_line("[BROWSER] Playwright Chromium session started")

            while True:
                item = self._command_queue.get()
                if item is _STOP:
                    break
                url, result_queue = item
                try:
                    response = request.get(url, timeout=REQUEST_TIMEOUT * 1000)
                    status = response.status
                    headers = dict(response.headers)
                    if status == 200:
                        result_queue.put(
                            _FetchResult(response.text(), status, headers, None)
                        )
                    else:
                        result_queue.put(
                            _FetchResult(None, status, headers, f"HTTP {status}")
                        )
                except Exception as exc:
                    log_line(
                        f"[WARN] browser fetch failed {url[:80]}: "
                        f"{format_fetch_error(exc)}"
                    )
                    result_queue.put(
                        _FetchResult(None, None, {}, format_fetch_error(exc))
                    )
        except Exception as exc:
            self._fail_startup(exc)
            return
        finally:
            for closer in (context, browser):
                if closer is None:
                    continue
                try:
                    closer.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            if self._ready:
                log_line("[BROWSER] Playwright session closed")

    def fetch(self, url: str) -> tuple[str | None, int | None, dict[str, str], str | None]:
        """Return (html, status_code, response_headers, error)."""
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
            self._ready_event.clear()


def close_browser_session() -> None:
    with BrowserSession._class_lock:
        if BrowserSession._instance is not None:
            BrowserSession._instance.close()
            BrowserSession._instance = None
