"""Transactional email delivery."""

from __future__ import annotations

import logging
import re

import requests

from ygo_app.config import BREVO_API_KEY, EMAIL_BACKEND, EMAIL_FROM, EMAIL_OTP_TTL_MINUTES

logger = logging.getLogger(__name__)

_FROM_RE = re.compile(r"^(.+?)\s*<([^>]+)>$")


def _parse_from_address(raw: str) -> tuple[str, str]:
    match = _FROM_RE.match(raw.strip())
    if match:
        return match.group(1).strip().strip('"'), match.group(2).strip()
    return "YGO Collection", raw.strip()


def send_verification_code(to: str, code: str) -> None:
    if EMAIL_BACKEND == "brevo":
        _send_brevo(to, code)
    else:
        _send_console(to, code)


def _send_console(to: str, code: str) -> None:
    logger.info("VERIFICATION CODE for %s: %s (valid %s minutes)", to, code, EMAIL_OTP_TTL_MINUTES)


def _send_brevo(to: str, code: str) -> None:
    if not BREVO_API_KEY:
        raise RuntimeError("BREVO_API_KEY is not configured")
    if not EMAIL_FROM:
        raise RuntimeError("EMAIL_FROM is not configured")

    sender_name, sender_email = _parse_from_address(EMAIL_FROM)
    body = (
        f"Your verification code is: {code}\n\n"
        f"This code expires in {EMAIL_OTP_TTL_MINUTES} minutes.\n\n"
        "If you did not request this, you can ignore this email."
    )
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to}],
        "subject": "Your YGO App verification code",
        "textContent": body,
    }
    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code >= 400:
        logger.error("Brevo send failed: %s %s", response.status_code, response.text[:500])
        raise RuntimeError(f"Failed to send verification email ({response.status_code})")
