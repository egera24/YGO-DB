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


def send_trade_order_request(
    *,
    owner_email: str,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
) -> None:
    if EMAIL_BACKEND == "brevo":
        _send_trade_order_brevo(
            owner_email=owner_email,
            seller_display_name=seller_display_name,
            buyer_contact=buyer_contact,
            lines=lines,
            submitted_at=submitted_at,
        )
    else:
        _send_trade_order_console(
            owner_email=owner_email,
            seller_display_name=seller_display_name,
            buyer_contact=buyer_contact,
            lines=lines,
            submitted_at=submitted_at,
        )


def _send_console(to: str, code: str) -> None:
    message = (
        f"VERIFICATION CODE for {to}: {code} "
        f"(valid {EMAIL_OTP_TTL_MINUTES} minutes)"
    )
    # print: uvicorn does not configure app loggers; console backend must be visible locally.
    print(message, flush=True)
    logger.info(
        "Verification code sent to %s (valid %s minutes)",
        to,
        EMAIL_OTP_TTL_MINUTES,
    )


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


def _format_price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f} €"


def _build_trade_order_body(
    *,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
) -> tuple[str, str]:
    title = seller_display_name or "Your trade list"
    subject = f"Trade order request — {title}"
    body_lines = [
        f"Trade order request for: {title}",
        f"Submitted at (UTC): {submitted_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Items:",
    ]
    for index, line in enumerate(lines, start=1):
        body_lines.append(f"{index}. {line.get('card_name') or 'Unknown card'}")
        body_lines.append(f"   Set: {line.get('set_code')} ({line.get('set_name') or '—'})")
        body_lines.append(
            f"   Rarity: {line.get('rarity_display') or line.get('rarity_code') or '—'}"
        )
        body_lines.append(f"   Condition: {line.get('condition') or '—'}")
        body_lines.append(f"   Quantity: {line['quantity']}")
        body_lines.append(f"   List price: {_format_price(line.get('list_price'))}")
        if line.get("offer_price") is not None:
            body_lines.append(f"   Alternate offer price: {_format_price(line.get('offer_price'))}")
        if line.get("comment"):
            body_lines.append(f"   Comment: {line['comment']}")
        body_lines.append("")

    contact_lines = []
    if buyer_contact.get("name"):
        contact_lines.append(f"Name: {buyer_contact['name']}")
    if buyer_contact.get("email"):
        contact_lines.append(f"Email: {buyer_contact['email']}")
    if buyer_contact.get("phone"):
        contact_lines.append(f"Phone: {buyer_contact['phone']}")
    if buyer_contact.get("address"):
        contact_lines.append(f"Address: {buyer_contact['address']}")
    if contact_lines:
        body_lines.extend(["Contact details:", *contact_lines, ""])
    else:
        body_lines.append("No contact details were provided.")
        body_lines.append("")

    body_lines.append("Reply to this email if the buyer included an email address.")
    return subject, "\n".join(body_lines)


def _send_trade_order_console(
    *,
    owner_email: str,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
) -> None:
    subject, body = _build_trade_order_body(
        seller_display_name=seller_display_name,
        buyer_contact=buyer_contact,
        lines=lines,
        submitted_at=submitted_at,
    )
    print(f"TRADE ORDER to {owner_email}: {subject}\n{body}", flush=True)
    logger.info(
        "Trade order sent to %s (%d lines)",
        owner_email,
        len(lines),
    )


def _send_trade_order_brevo(
    *,
    owner_email: str,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
) -> None:
    if not BREVO_API_KEY:
        raise RuntimeError("BREVO_API_KEY is not configured")
    if not EMAIL_FROM:
        raise RuntimeError("EMAIL_FROM is not configured")

    sender_name, sender_email = _parse_from_address(EMAIL_FROM)
    subject, body = _build_trade_order_body(
        seller_display_name=seller_display_name,
        buyer_contact=buyer_contact,
        lines=lines,
        submitted_at=submitted_at,
    )
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": owner_email}],
        "subject": subject,
        "textContent": body,
    }
    buyer_email = buyer_contact.get("email")
    if buyer_email:
        payload["replyTo"] = {"email": buyer_email}
        if buyer_contact.get("name"):
            payload["replyTo"]["name"] = buyer_contact["name"]

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
        logger.error(
            "Brevo trade order send failed: %s %s",
            response.status_code,
            response.text[:500],
        )
        raise RuntimeError(f"Failed to send trade order email ({response.status_code})")
    logger.info(
        "Trade order email sent to %s (%d lines)",
        owner_email,
        len(lines),
    )
