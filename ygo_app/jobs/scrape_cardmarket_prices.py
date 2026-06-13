"""Deprecated: use the 4-step Cardmarket scrape pipeline instead."""

from __future__ import annotations

import sys

_MIGRATION = """
The monolithic scrape_cardmarket_prices job has been replaced by a 4-step pipeline:

  1. python -m ygo_app.jobs.scrape_cardmarket_expansions [--cf-login]
  2. python -m ygo_app.jobs.scrape_cardmarket_card_list --resume
  3. python -m ygo_app.jobs.scrape_cardmarket_card_details --resume
  4. python -m ygo_app.jobs.export_cardmarket_prices

Then upload/import as before:
  python -m ygo_app.jobs.upload_cardmarket_prices
  python -m ygo_app.jobs.import_cardmarket_prices --file data/catalog/cardmarket_prices.json
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
