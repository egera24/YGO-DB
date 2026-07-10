"""Yugipedia catalog scraping and import adapters."""

from ygo_app.yugipedia.adapter import yugipedia_entries_to_api
from ygo_app.yugipedia.paths import ALL_CARDS_PATH, PASSCODE_LIST_PATH, REJECTED_PATH

__all__ = [
    "ALL_CARDS_PATH",
    "PASSCODE_LIST_PATH",
    "REJECTED_PATH",
    "yugipedia_entries_to_api",
]
