"""Load Playwright storage_state cookies into HTTP sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ygo_app.yugipedia.scrape_progress import log_line


def load_storage_cookies(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        return []
    return [c for c in cookies if isinstance(c, dict) and c.get("name")]


def storage_has_cf_clearance(path: Path) -> bool:
    return any(c.get("name") == "cf_clearance" for c in load_storage_cookies(path))


def apply_storage_cookies_to_requests(session: Any, path: Path) -> int:
    """Apply cookies to a requests/cloudscraper session. Returns count applied."""
    from requests.cookies import create_cookie

    applied = 0
    for row in load_storage_cookies(path):
        name = row.get("name")
        value = row.get("value")
        if not name or value is None:
            continue
        session.cookies.set_cookie(
            create_cookie(
                name=name,
                value=value,
                domain=row.get("domain"),
                path=row.get("path") or "/",
                secure=bool(row.get("secure")),
            )
        )
        applied += 1
    return applied


def apply_storage_cookies_to_curl_cffi(session: Any, path: Path) -> int:
    applied = 0
    for row in load_storage_cookies(path):
        name = row.get("name")
        value = row.get("value")
        if not name or value is None:
            continue
        session.cookies.set(
            name,
            value,
            domain=row.get("domain"),
            path=row.get("path") or "/",
            secure=bool(row.get("secure")),
        )
        applied += 1
    return applied


def apply_storage_cookies(session: Any, path: Path, *, backend: str) -> int:
    if not path.is_file():
        return 0
    if backend == "curl_cffi":
        count = apply_storage_cookies_to_curl_cffi(session, path)
    else:
        count = apply_storage_cookies_to_requests(session, path)
    if count:
        cf = storage_has_cf_clearance(path)
        log_line(
            f"[COOKIES] applied {count} cookies from {path}"
            + (" (cf_clearance present)" if cf else "")
        )
    return count
