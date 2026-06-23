"""Compact fetch URL labels for console logging."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

_SEARCH_PATH_SUFFIX = "/Products/Search"
_SEARCH_LOG_KEYS = ("idExpansion", "site", "perSite", "mode", "idProduct")


def format_fetch_url(url: str) -> str:
    """Return a short, distinctive label for fetch logging."""
    parsed = urlparse(url)
    path = parsed.path or ""

    if path.endswith(_SEARCH_PATH_SUFFIX):
        params = parse_qs(parsed.query, keep_blank_values=False)
        parts: list[str] = []
        for key in _SEARCH_LOG_KEYS:
            values = params.get(key)
            if values:
                parts.append(f"{key}={values[0]}")
        if parts:
            return " ".join(parts)

    if path:
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=False)
            if params:
                first_key = next(iter(params))
                return f"{path}?{first_key}={params[first_key][0]}"
        return path

    return url
