"""Deprecated: use the 4-step Cardmarket scrape pipeline instead."""

from __future__ import annotations

import sys

_MIGRATION = """
The Cardmarket web scraper has been archived. Use the catalog pipeline instead:

  python -m ygo_app.jobs.sync_cardmarket_catalog

Weekly import runs via GitHub Actions: sync-cardmarket-catalog.yml
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--help-migration" in args or "-h" in args or "--help" in args:
        print(_MIGRATION.strip())
        return 0
    print(_MIGRATION.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
