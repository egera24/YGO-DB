"""Progress helpers for long-running imports."""

from __future__ import annotations

import time

PROGRESS_MIN_ROWS_FOR_ETA = 10
PROGRESS_THROTTLE_ROWS = 50
PROGRESS_THROTTLE_SECONDS = 0.25


def eta_seconds(current: int, total: int, started: float) -> float | None:
    elapsed = time.monotonic() - started
    if current < PROGRESS_MIN_ROWS_FOR_ETA or elapsed <= 0 or total <= 0:
        return None
    rate = current / elapsed
    remaining = total - current
    return remaining / rate if rate > 0 else None


class ProgressThrottle:
    """Emit progress at most every N rows or T seconds."""

    def __init__(
        self,
        *,
        every_rows: int = PROGRESS_THROTTLE_ROWS,
        every_seconds: float = PROGRESS_THROTTLE_SECONDS,
    ) -> None:
        self.every_rows = every_rows
        self.every_seconds = every_seconds
        self._last_row = 0
        self._last_time = 0.0

    def should_emit(self, current: int) -> bool:
        now = time.monotonic()
        if current <= 0:
            return False
        if self._last_row == 0:
            self._last_row = current
            self._last_time = now
            return True
        if current - self._last_row >= self.every_rows:
            self._last_row = current
            self._last_time = now
            return True
        if now - self._last_time >= self.every_seconds:
            self._last_row = current
            self._last_time = now
            return True
        return False

    def force_emit(self, current: int) -> None:
        self._last_row = current
        self._last_time = time.monotonic()
