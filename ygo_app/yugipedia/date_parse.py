"""Parse Yugipedia human-readable dates into ISO date strings."""

from __future__ import annotations

from datetime import date, datetime

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_yugipedia_date(text: str | None) -> date | None:
    """Parse dates like '8 March 2002' or '2024-11-07'."""
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    parts = raw.replace(",", "").split()
    if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
        month = _MONTHS.get(parts[1].lower())
        if month:
            try:
                return date(int(parts[2]), month, int(parts[0]))
            except ValueError:
                return None
    return None


def date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
