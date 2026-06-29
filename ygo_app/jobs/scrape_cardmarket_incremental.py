"""Deprecated: legacy Cardmarket web scraper archived."""

from __future__ import annotations

import sys

from ygo_app.jobs._deprecated_cardmarket import deprecated_main


def main(argv: list[str] | None = None) -> int:
    return deprecated_main(argv)


if __name__ == "__main__":
    sys.exit(main())
