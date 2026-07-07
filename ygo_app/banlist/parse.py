"""Parse Konami banlist JSON payloads."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

STATUS_BY_KEY = {
    "0": "forbidden",
    "1": "limited",
    "2": "semi_limited",
}


def parse_effective_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_label_date(label: str) -> date | None:
    if not label:
        return None
    match = re.match(r"^([A-Za-z]+)\s+(\d{4})$", label.strip())
    if not match:
        return None
    month_name, year = match.groups()
    try:
        return datetime.strptime(f"{month_name} 1 {year}", "%B %d %Y").date()
    except ValueError:
        return None


def normalize_list_payload(
    payload: dict[str, Any],
    *,
    source_list_id: str,
    label: str,
) -> dict[str, Any]:
    effective_from = parse_effective_date(payload.get("from")) or parse_label_date(label)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status_key, status in STATUS_BY_KEY.items():
        for row in payload.get(status_key, []) or []:
            name = (row.get("nameeng") or row.get("name") or "").strip()
            if not name:
                continue
            # Konami's payload can list the same card twice (same category or
            # across categories); the DB enforces one row per (revision, name),
            # so keep the first occurrence (most restrictive status wins).
            if name in seen:
                continue
            seen.add(name)
            cid_raw = row.get("cid")
            konami_cid = int(cid_raw) if cid_raw is not None and str(cid_raw).isdigit() else None
            entries.append(
                {
                    "card_name_raw": name,
                    "konami_cid": konami_cid,
                    "status": status,
                }
            )
    return {
        "source_list_id": source_list_id,
        "label": label,
        "effective_from": effective_from,
        "source_url": f"https://www.yugioh-card.com/eu/_data/fllists/{source_list_id}.json",
        "entries": entries,
    }
