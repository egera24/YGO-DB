"""Card image URL helpers — Yugipedia CDN and YGOProDeck API fallback."""

from __future__ import annotations

import re

# Default thumb width when synthesizing from a direct URL (wiki cardtables use 300px).
YUGIPEDIA_DEFAULT_THUMB_WIDTH = 300

YGOPRODECK_CARD_URL = "https://ygoprodeck.com/card/{}"
YGOPRODECK_IMAGE_URL = "https://images.ygoprodeck.com/images/cards/{}.jpg"
YGOPRODECK_IMAGE_SMALL_URL = "https://images.ygoprodeck.com/images/cards_small/{}.jpg"

YUGIPEDIA_MEDIA_HOST = "ms.yugipedia.com"

# UI icons and non-card-art filenames on Yugipedia wiki pages.
_UI_IMAGE_FILENAME_RE = re.compile(
    r"(^LM-|CG_Star|Pendulum_Scale|Continuous\.|Quick-Play\.|SPELL\.|TRAP\.|"
    r"^DARK\.|^LIGHT\.|^EARTH\.|^WATER\.|^FIRE\.|^WIND\.|^DIVINE\.)",
    re.IGNORECASE,
)

_YUGIPEDIA_THUMB_RE = re.compile(
    r"^(https://ms\.yugipedia\.com)/+/thumb/([^/]+)/([^/]+)/([^/]+)/(?:\d+(?:\.\d+)?px-)?\4$",
    re.IGNORECASE,
)
_YUGIPEDIA_DIRECT_RE = re.compile(
    r"^https://ms\.yugipedia\.com/+[^/]+/[^/]+/.+\.(?:png|jpe?g|gif|webp)$",
    re.IGNORECASE,
)


def passcode_to_int(password: str | int) -> int | None:
    try:
        return int(password)
    except (ValueError, TypeError):
        return None


def ygoprodeck_card_url(password: str | int) -> str | None:
    pid = passcode_to_int(password)
    if pid is None:
        return None
    return YGOPRODECK_CARD_URL.format(pid)


def image_urls_for_passcode(password: str | int) -> dict[str, str | None]:
    """Build YGOProDeck CDN URLs for a card passcode (API fallback import only)."""
    pid = passcode_to_int(password)
    if pid is None:
        return {
            "ygoprodeck_url": None,
            "image_url": None,
            "image_url_small": None,
        }
    return {
        "ygoprodeck_url": YGOPRODECK_CARD_URL.format(pid),
        "image_url": YGOPRODECK_IMAGE_URL.format(pid),
        "image_url_small": YGOPRODECK_IMAGE_SMALL_URL.format(pid),
    }


def normalize_yugipedia_image_url(url: str | None) -> str | None:
    """Convert a Yugipedia thumb URL to the direct ms.yugipedia.com file URL."""
    if not url:
        return None
    url = url.strip()
    match = _YUGIPEDIA_THUMB_RE.match(url)
    if match:
        base, h1, h2, filename = match.groups()
        return f"{base}//{h1}/{h2}/{filename}"
    if _YUGIPEDIA_DIRECT_RE.match(url):
        return url
    return url


def yugipedia_thumb_url(full_url: str | None, *, width: int = 150) -> str | None:
    """Build a Yugipedia thumbnail URL from a direct file URL."""
    if not full_url:
        return None
    full_url = normalize_yugipedia_image_url(full_url) or full_url
    match = re.match(
        r"^(https://ms\.yugipedia\.com)/+/([^/]+)/([^/]+)/([^/]+)$",
        full_url,
        re.IGNORECASE,
    )
    if not match:
        return full_url
    base, h1, h2, filename = match.groups()
    return f"{base}//thumb/{h1}/{h2}/{filename}/{width}px-{filename}"


def is_yugipedia_card_art_filename(filename: str) -> bool:
    """True when a wiki File: name looks like card artwork, not a UI icon."""
    if not filename or filename.lower().endswith(".svg"):
        return False
    if _UI_IMAGE_FILENAME_RE.search(filename):
        return False
    return True


def resolve_display_image_url_small(
    image_url_small: str | None,
    image_url: str | None,
) -> str | None:
    """Return a Yugipedia thumb URL that exists on the CDN (fixes legacy 150px synth rows)."""
    if image_url_small and "150px-" not in image_url_small:
        return image_url_small
    if image_url:
        return yugipedia_thumb_url(image_url, width=YUGIPEDIA_DEFAULT_THUMB_WIDTH) or image_url
    return image_url_small


def yugipedia_image_urls_from_src(
    src: str | None,
    *,
    small_width: int = YUGIPEDIA_DEFAULT_THUMB_WIDTH,
) -> dict[str, str | None]:
    """Build full + thumb URLs from a scraped img src."""
    full = normalize_yugipedia_image_url(src)
    if not full:
        return {"image_url": None, "image_url_small": None}

    src_stripped = (src or "").strip()
    if _YUGIPEDIA_THUMB_RE.match(src_stripped):
        image_url_small = src_stripped
    else:
        image_url_small = yugipedia_thumb_url(full, width=small_width)
    return {"image_url": full, "image_url_small": image_url_small}
