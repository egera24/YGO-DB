"""Database-backed sliding-window rate limits for auth endpoints."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ygo_app.models import AuthRateLimit

_DEBUG_LOG = Path(__file__).resolve().parent.parent / "debug-3b87b6.log"


def _agent_log(location: str, message: str, data: dict, hypothesis_id: str, run_id: str = "pre-fix") -> None:
    # #region agent log
    try:
        with _DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "sessionId": "3b87b6",
                        "runId": run_id,
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion


@dataclass(frozen=True)
class RateLimitSpec:
    max_count: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


def check_rate_limit(
    session: Session,
    key: str,
    spec: RateLimitSpec,
    now: datetime | None = None,
) -> RateLimitResult:
    current = now or datetime.utcnow()
    row = session.get(AuthRateLimit, key)
    window = timedelta(seconds=spec.window_seconds)

    if row is None or current - row.window_start >= window:
        if row is None:
            row = AuthRateLimit(key=key, count=1, window_start=current)
            session.add(row)
        else:
            row.count = 1
            row.window_start = current
        session.flush()
        return RateLimitResult(allowed=True)

    if row.count >= spec.max_count:
        elapsed = (current - row.window_start).total_seconds()
        retry_after = max(1, int(spec.window_seconds - elapsed))
        return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

    row.count += 1
    session.flush()
    return RateLimitResult(allowed=True)


def enforce_rate_limit(
    session: Session,
    key: str,
    spec: RateLimitSpec,
    now: datetime | None = None,
) -> None:
    # #region agent log
    _agent_log(
        "rate_limit.py:enforce_rate_limit",
        "rate_limit_check_start",
        {"key_prefix": key.split(":", 1)[0], "dialect": session.bind.dialect.name if session.bind else None},
        "A",
    )
    # #endregion
    try:
        result = check_rate_limit(session, key, spec, now=now)
    except Exception as exc:
        # #region agent log
        _agent_log(
            "rate_limit.py:enforce_rate_limit",
            "rate_limit_check_failed",
            {"error_type": type(exc).__name__, "error": str(exc)[:500]},
            "A",
        )
        # #endregion
        raise
    # #region agent log
    _agent_log(
        "rate_limit.py:enforce_rate_limit",
        "rate_limit_check_ok",
        {"allowed": result.allowed, "retry_after": result.retry_after_seconds},
        "A",
    )
    # #endregion
    if not result.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
