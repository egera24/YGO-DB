"""Database-backed sliding-window rate limits for auth endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ygo_app.models import AuthRateLimit


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
    result = check_rate_limit(session, key, spec, now=now)
    if not result.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
