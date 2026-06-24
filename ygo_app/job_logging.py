"""File logging for long-running CLI jobs (tee from log_line)."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ygo_app import config

LOG_DIR = config.DATA_DIR / "logs"

_lock = threading.Lock()
_log_file = None
_log_path: Path | None = None
_start_monotonic: float | None = None


class JobLogHandle:
    """Active job log session; set exit_code before returning from main."""

    __slots__ = ("exit_code", "path")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.exit_code = 0


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _resolve_log_path(job_name: str, started: datetime) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    base = LOG_DIR / f"{job_name}_{stamp}.log"
    if not base.exists():
        return base
    for suffix in range(1, 1000):
        candidate = LOG_DIR / f"{job_name}_{stamp}_{suffix:03d}.log"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique log path for job {job_name!r}")


def configure_job_log(job_name: str) -> Path:
    """Open a timestamped log file for the current job. Returns the log path."""
    global _log_file, _log_path, _start_monotonic

    with _lock:
        if _log_file is not None:
            raise RuntimeError("Job log session already active")

        started = datetime.now().replace(microsecond=0)
        path = _resolve_log_path(job_name, started)
        handle = path.open("w", encoding="utf-8", newline="\n")

        _log_file = handle
        _log_path = path
        _start_monotonic = time.monotonic()

        argv_repr = " ".join(sys.argv)
        handle.write(
            f"[JOB_START] job={job_name} started={started.isoformat()} "
            f"pid={os.getpid()} argv={argv_repr}\n"
        )
        handle.flush()

    return path


def format_log_line(message: str) -> str:
    """Prefix message with a local timestamp when a job log session is active."""
    if _log_file is None:
        return message
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"{stamp} {message}"


def write_log_line(line: str) -> None:
    """Append a formatted line to the active job log file."""
    global _log_file
    if _log_file is None:
        return
    with _lock:
        if _log_file is not None:
            _log_file.write(f"{line}\n")
            _log_file.flush()


def close_job_log(*, exit_code: int | None = None) -> None:
    """Write job footer and close the log file."""
    global _log_file, _log_path, _start_monotonic

    footer = ""
    with _lock:
        if _log_file is None:
            return

        elapsed = ""
        if _start_monotonic is not None:
            elapsed = _format_elapsed(time.monotonic() - _start_monotonic)

        exit_part = f" exit={exit_code}" if exit_code is not None else ""
        footer = f"[JOB_END] elapsed={elapsed}{exit_part}"
        _log_file.write(f"{footer}\n")
        _log_file.flush()
        _log_file.close()

        _log_file = None
        _log_path = None
        _start_monotonic = None

    print(footer, flush=True)


@contextmanager
def job_log_session(job_name: str) -> Iterator[JobLogHandle]:
    """Configure file logging for a job; close with handle.exit_code on exit."""
    path = configure_job_log(job_name)
    handle = JobLogHandle(path)
    try:
        yield handle
    except BaseException:
        handle.exit_code = 1
        raise
    finally:
        close_job_log(exit_code=handle.exit_code)


def run_job_logged(job_name: str, fn: Callable[[], int]) -> int:
    """Run a job main body under file logging; propagates its return code to [JOB_END]."""
    with job_log_session(job_name) as handle:
        handle.exit_code = fn()
        return handle.exit_code
