"""Shared deprecation message for legacy Cardmarket scrape jobs."""

from __future__ import annotations

import sys

_MIGRATION = """
The Cardmarket web scraper has been archived. Use the catalog pipeline instead:

  python -m ygo_app.jobs.sync_cardmarket_catalog

Weekly import runs via GitHub Actions: sync-cardmarket-catalog.yml

Legacy scraper code: archive/legacy_cardmarket_scrape/
Docs: docs/cardmarket-catalog-pipeline.md
"""


def deprecated_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--help-migration" in args or "-h" in args or "--help" in args:
        print(_MIGRATION.strip())
        return 0
    print(_MIGRATION.strip(), file=sys.stderr)
    return 1
