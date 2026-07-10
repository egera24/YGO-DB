"""Email OTP generation and validation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ygo_app.config import EMAIL_OTP_MAX_ATTEMPTS, EMAIL_OTP_TTL_MINUTES, SECRET_KEY
from ygo_app.models import PendingRegistration

MAX_OTP_ATTEMPTS = EMAIL_OTP_MAX_ATTEMPTS
PENDING_RETENTION_HOURS = 24


def normalize_email(email: str) -> str:
    return email.lower().strip()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_otp(code: str, otp_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), otp_hash)


def otp_expires_at(now: datetime | None = None) -> datetime:
    base = now or datetime.utcnow()
    return base + timedelta(minutes=EMAIL_OTP_TTL_MINUTES)


def is_otp_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    return (now or datetime.utcnow()) >= expires_at


def get_pending_by_email(session: Session, email: str) -> PendingRegistration | None:
    return session.execute(
        select(PendingRegistration).where(
            PendingRegistration.email == normalize_email(email)
        )
    ).scalar_one_or_none()


def issue_otp_for_pending(pending: PendingRegistration, now: datetime | None = None) -> str:
    """Set a new OTP on pending row; returns plaintext code for sending."""
    base = now or datetime.utcnow()
    code = generate_otp()
    pending.otp_hash = hash_otp(code)
    pending.otp_expires_at = otp_expires_at(base)
    pending.otp_attempts = 0
    pending.last_sent_at = base
    return code


def cleanup_stale_pending(session: Session, now: datetime | None = None) -> None:
    cutoff = (now or datetime.utcnow()) - timedelta(hours=PENDING_RETENTION_HOURS)
    session.execute(
        delete(PendingRegistration).where(PendingRegistration.otp_expires_at < cutoff)
    )
