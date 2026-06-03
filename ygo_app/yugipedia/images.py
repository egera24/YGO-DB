"""YGOPRODeck CDN image URLs from card passcode (no local downloads)."""

from __future__ import annotations

YGOPRODECK_CARD_URL = "https://ygoprodeck.com/card/{}"
YGOPRODECK_IMAGE_URL = "https://images.ygoprodeck.com/images/cards/{}.jpg"
YGOPRODECK_IMAGE_SMALL_URL = "https://images.ygoprodeck.com/images/cards_small/{}.jpg"


def passcode_to_int(password: str | int) -> int | None:
    try:
        return int(password)
    except (ValueError, TypeError):
        return None


def image_urls_for_passcode(password: str | int) -> dict[str, str | None]:
    """Build CDN URLs for a card passcode."""
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
