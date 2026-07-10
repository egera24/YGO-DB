"""Cloudflare Turnstile verification (optional)."""

from __future__ import annotations

import requests

from ygo_app.config import TURNSTILE_SECRET_KEY


def turnstile_required() -> bool:
    return bool(TURNSTILE_SECRET_KEY)


def verify_turnstile_token(token: str | None, remote_ip: str | None = None) -> bool:
    if not TURNSTILE_SECRET_KEY:
        return True
    if not token:
        return False
    payload = {"secret": TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip
    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload,
            timeout=10,
        )
        response.raise_for_status()
        return bool(response.json().get("success"))
    except requests.RequestException:
        return False
