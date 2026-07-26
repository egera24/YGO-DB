"""Transactional email delivery."""

from __future__ import annotations

import base64
import logging
import re

import requests

from ygo_app.config import BREVO_API_KEY, EMAIL_BACKEND, EMAIL_FROM, EMAIL_OTP_TTL_MINUTES
from ygo_app.trade_export import trade_order_attachment_filename, write_trade_order_xlsx

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
    send_copy_to_buyer: bool = False,
) -> None:
    if EMAIL_BACKEND == "brevo":
        _send_trade_order_brevo(
            owner_email=owner_email,
            seller_display_name=seller_display_name,
            buyer_contact=buyer_contact,
            lines=lines,
            submitted_at=submitted_at,
            send_copy_to_buyer=send_copy_to_buyer,
        )
    else:
        _send_trade_order_console(
            owner_email=owner_email,
            seller_display_name=seller_display_name,
            buyer_contact=buyer_contact,
            lines=lines,
            submitted_at=submitted_at,
            send_copy_to_buyer=send_copy_to_buyer,
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


def _build_trade_order_body(
    *,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
) -> tuple[str, str]:
    title = seller_display_name or "Your trade list"
    subject = f"Trade order request — {title}"
    item_count = len(lines)
    item_label = "item" if item_count == 1 else "items"
    body_lines = [
        f"Trade order request for: {title}",
        f"Submitted at (UTC): {submitted_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"See attached Excel file for {item_count} {item_label}.",
        "",
    ]

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


def _trade_order_attachment(lines: list[dict]) -> tuple[bytes, str]:
    content = write_trade_order_xlsx(lines)
    return content, trade_order_attachment_filename()


def _send_trade_order_console(
    *,
    owner_email: str,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
    send_copy_to_buyer: bool = False,
) -> None:
    subject, body = _build_trade_order_body(
        seller_display_name=seller_display_name,
        buyer_contact=buyer_contact,
        lines=lines,
        submitted_at=submitted_at,
    )
    attachment_bytes, attachment_name = _trade_order_attachment(lines)
    buyer_email = buyer_contact.get("email")
    copy_note = ""
    if send_copy_to_buyer and buyer_email:
        copy_note = f"\n(Would also send buyer copy to {buyer_email})"
    print(
        f"TRADE ORDER to {owner_email}: {subject}\n{body}\n"
        f"Attachment: {attachment_name} ({len(attachment_bytes)} bytes)"
        f"{copy_note}",
        flush=True,
    )
    logger.info(
        "Trade order sent to %s (%d lines, attachment=%d bytes, buyer_copy=%s)",
        owner_email,
        len(lines),
        len(attachment_bytes),
        bool(send_copy_to_buyer and buyer_email),
    )


def _post_brevo_trade_order(
    *,
    to_email: str,
    to_name: str | None,
    subject: str,
    body: str,
    attachment_b64: str,
    attachment_name: str,
    reply_to_email: str | None = None,
    reply_to_name: str | None = None,
) -> None:
    if not BREVO_API_KEY:
        raise RuntimeError("BREVO_API_KEY is not configured")
    if not EMAIL_FROM:
        raise RuntimeError("EMAIL_FROM is not configured")

    sender_name, sender_email = _parse_from_address(EMAIL_FROM)
    recipient = {"email": to_email}
    if to_name:
        recipient["name"] = to_name
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [recipient],
        "subject": subject,
        "textContent": body,
        "attachment": [{"content": attachment_b64, "name": attachment_name}],
    }
    if reply_to_email:
        payload["replyTo"] = {"email": reply_to_email}
        if reply_to_name:
            payload["replyTo"]["name"] = reply_to_name

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


def _send_trade_order_brevo(
    *,
    owner_email: str,
    seller_display_name: str | None,
    buyer_contact: dict,
    lines: list[dict],
    submitted_at,
    send_copy_to_buyer: bool = False,
) -> None:
    subject, body = _build_trade_order_body(
        seller_display_name=seller_display_name,
        buyer_contact=buyer_contact,
        lines=lines,
        submitted_at=submitted_at,
    )
    attachment_bytes, attachment_name = _trade_order_attachment(lines)
    attachment_b64 = base64.b64encode(attachment_bytes).decode("ascii")

    buyer_email = buyer_contact.get("email")
    buyer_name = buyer_contact.get("name")
    _post_brevo_trade_order(
        to_email=owner_email,
        to_name=seller_display_name,
        subject=subject,
        body=body,
        attachment_b64=attachment_b64,
        attachment_name=attachment_name,
        reply_to_email=buyer_email,
        reply_to_name=buyer_name if buyer_email else None,
    )
    logger.info(
        "Trade order email sent to %s (%d lines)",
        owner_email,
        len(lines),
    )

    if send_copy_to_buyer and buyer_email:
        _post_brevo_trade_order(
            to_email=buyer_email,
            to_name=buyer_name,
            subject=subject,
            body=body,
            attachment_b64=attachment_b64,
            attachment_name=attachment_name,
            reply_to_email=owner_email,
            reply_to_name=seller_display_name,
        )
        logger.info(
            "Trade order buyer copy sent to %s (%d lines)",
            buyer_email,
            len(lines),
        )
