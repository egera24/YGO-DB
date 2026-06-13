"""Deprecated export scrape — see export_cardmarket_prices and the 3-step HTTP jobs."""

from __future__ import annotations


def run_export_scrape(**kwargs) -> int:
    raise RuntimeError(
        "run_export_scrape is deprecated. Use:\n"
        "  python -m ygo_app.jobs.scrape_cardmarket_expansions\n"
        "  python -m ygo_app.jobs.scrape_cardmarket_card_list\n"
        "  python -m ygo_app.jobs.scrape_cardmarket_card_details\n"
        "  python -m ygo_app.jobs.export_cardmarket_prices"
    )
