"""Trade share slug generation and validation."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.models import User

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])?$")
_RESERVED_SLUGS = frozenset(
    {
        "api",
        "static",
        "legal",
        "trade",
        "favicon",
        "docs",
        "redoc",
        "openapi",
    }
)


def generate_trade_share_slug() -> str:
    return secrets.token_urlsafe(16)


def normalize_trade_slug(value: str) -> str:
    slug = value.strip().lower()
    if len(slug) < 3 or len(slug) > 64:
        raise ValueError("Slug must be 3–64 characters")
    if not _SLUG_RE.match(slug):
        raise ValueError("Slug may only contain lowercase letters, numbers, and hyphens")
    if slug in _RESERVED_SLUGS:
        raise ValueError("This slug is reserved")
    return slug


def _slug_taken(session: Session, slug: str, *, exclude_user_id: int | None = None) -> bool:
    stmt = select(User.id).where(User.trade_share_slug == slug)
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return session.execute(stmt).scalar_one_or_none() is not None


def ensure_user_trade_slug(session: Session, user: User) -> str:
    if user.trade_share_slug:
        return user.trade_share_slug
    for _ in range(20):
        slug = generate_trade_share_slug()
        if not _slug_taken(session, slug):
            user.trade_share_slug = slug
            session.flush()
            return slug
    raise RuntimeError("Could not generate a unique trade share slug")


def assign_unique_trade_slug(session: Session, user: User, slug: str) -> str:
    normalized = normalize_trade_slug(slug)
    if _slug_taken(session, normalized, exclude_user_id=user.id):
        raise ValueError("This slug is already taken")
    user.trade_share_slug = normalized
    session.flush()
    return normalized


def _register_user_slug_listener() -> None:
    from sqlalchemy import event

    from ygo_app.models import User

    @event.listens_for(User, "before_insert")
    def _assign_trade_slug(_mapper, _connection, target: User) -> None:
        if not target.trade_share_slug:
            target.trade_share_slug = generate_trade_share_slug()


_register_user_slug_listener()
