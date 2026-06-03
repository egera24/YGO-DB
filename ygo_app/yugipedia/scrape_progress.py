"""Heartbeat, stall detection, and degraded-rate warnings for details scrape."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ygo_app.yugipedia.constants import (
    DEGRADED_RATE_THRESHOLD,
    HEARTBEAT_INTERVAL_SECONDS,
    REQUESTS_PER_SECOND,
    STALL_ABORT_SECONDS,
    STALL_WARN_SECONDS,
)


def log_line(message: str) -> None:
    print(message, flush=True)


class ScrapeStalledError(RuntimeError):
    """Raised when no card completes within STALL_ABORT_SECONDS."""


class BatchIncompleteError(RuntimeError):
    """Raised when a batch slice has passcodes neither saved nor rejected."""


def is_retryable_error(error: str | None) -> bool:
    """True if the card should be re-queued for a batch-level retry round."""
    if not error:
        return True
    lower = error.lower()
    retry_markers = (
        "cloudflare",
        "timeout",
        "timed out",
        "readtimeout",
        "connecttimeout",
        "connectionerror",
        "connection error",
        "502",
        "503",
        "504",
        "500",
        "pooltimeout",
        "workererror",
        "failed after",
        "retry attempts",
    )
    if any(m in lower for m in retry_markers):
        return True
    final_markers = (
        "password mismatch",
        "parse",
        "parsing",
        "invalid",
        "missing",
    )
    if any(m in lower for m in final_markers):
        return False
    return False


class ScrapeProgressMonitor:
    """Thread-safe progress tracking with periodic heartbeat logs."""

    def __init__(
        self,
        *,
        total_pending: int,
        output_path: Path,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.total_pending = total_pending
        self.output_path = output_path
        self.heartbeat_interval = heartbeat_interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.completed = 0
        self.successes = 0
        self.failures = 0
        self.start_time = time.monotonic()
        self.last_progress_time = self.start_time
        self.last_completed_at_heartbeat = 0
        self.last_card_name = ""
        self.stall_warned = False
        self.degraded_warned = False
        self._abort: ScrapeStalledError | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def record(self, *, card_name: str, success: bool) -> None:
        with self._lock:
            self.completed += 1
            if success:
                self.successes += 1
            else:
                self.failures += 1
            self.last_card_name = card_name
            self.last_progress_time = time.monotonic()

    def check_abort(self) -> None:
        with self._lock:
            err = self._abort
        if err is not None:
            raise err

    def seconds_since_progress(self) -> float:
        with self._lock:
            return time.monotonic() - self.last_progress_time

    def _output_size_bytes(self) -> int | None:
        try:
            if self.output_path.exists():
                return self.output_path.stat().st_size
        except OSError:
            pass
        return None

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval):
            self._emit_heartbeat()

    def _emit_heartbeat(self) -> None:
        with self._lock:
            completed = self.completed
            elapsed = time.monotonic() - self.start_time
            since_progress = time.monotonic() - self.last_progress_time
            delta = completed - self.last_completed_at_heartbeat
            self.last_completed_at_heartbeat = completed
            successes = self.successes
            failures = self.failures
            last_name = self.last_card_name
            total = self.total_pending

        rate = completed / elapsed if elapsed > 0 else 0.0
        window_rate = delta / self.heartbeat_interval if self.heartbeat_interval > 0 else 0.0
        remaining = total - completed
        eta_min = (remaining / rate / 60) if rate > 0 else 0.0
        size = self._output_size_bytes()
        size_str = f"{size:,} bytes" if size is not None else "n/a"

        log_line(
            f"[HEARTBEAT] {completed}/{total} ok={successes} fail={failures} "
            f"rate={rate:.2f}/s (window={window_rate:.2f}/s) "
            f"idle={since_progress:.0f}s json={size_str} eta={eta_min:.1f}m "
            f"last={last_name[:36]!r}"
        )

        if since_progress >= STALL_WARN_SECONDS and not self.stall_warned:
            self.stall_warned = True
            log_line(
                f"[WARN] No progress for {since_progress:.0f}s "
                f"(stall warn threshold {STALL_WARN_SECONDS}s). "
                "Connection may be degraded or a worker is hung."
            )

        if (
            completed > 0
            and window_rate < DEGRADED_RATE_THRESHOLD
            and window_rate < REQUESTS_PER_SECOND * 0.5
            and not self.degraded_warned
        ):
            self.degraded_warned = True
            log_line(
                f"[WARN] Throughput degraded: {window_rate:.2f}/s in last "
                f"{self.heartbeat_interval:.0f}s (target ~{REQUESTS_PER_SECOND}/s). "
                "Retries or network issues likely."
            )

        if since_progress >= STALL_ABORT_SECONDS:
            with self._lock:
                if self._abort is None:
                    self._abort = ScrapeStalledError(
                        f"No card completed in {since_progress:.0f}s "
                        f"(abort threshold {STALL_ABORT_SECONDS}s). "
                        f"Last card: {last_name!r}. Re-run with --resume to continue."
                    )

    def log_progress_line(
        self,
        *,
        completed: int,
        total: int,
        card_name: str,
        success: bool,
        run_start: float,
    ) -> None:
        elapsed = time.monotonic() - run_start
        rate = completed / elapsed if elapsed > 0 else 0.0
        eta = (total - completed) / rate / 60 if rate > 0 else 0.0
        status = "ok" if success else "fail"
        log_line(
            f"[{completed}/{total}] {status} {card_name[:40]:40} | "
            f"{rate:.1f}/s | ETA {eta:.1f}m"
        )

    def log_summary(self) -> None:
        elapsed = time.monotonic() - self.start_time
        rate = self.completed / elapsed if elapsed > 0 else 0.0
        size = self._output_size_bytes()
        size_part = f" json={size:,} bytes" if size is not None else ""
        log_line(
            f"[SUMMARY] processed={self.completed} ok={self.successes} "
            f"fail={self.failures} elapsed={elapsed / 60:.1f}m "
            f"avg_rate={rate:.2f}/s{size_part}"
        )
