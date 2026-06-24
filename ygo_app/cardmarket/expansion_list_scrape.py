"""Job 1: fetch TCG expansion list from Cardmarket."""

from __future__ import annotations

from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list, save_json
from ygo_app.cardmarket.constants import DISCOVERY_REQUESTS_PER_SECOND, FetchBackend, SEARCH_URL
from ygo_app.cardmarket.expansions import parse_expansions_from_html_with_exclusions
from ygo_app.cardmarket.http_client import AdaptiveRateLimiter, create_scraper, fetch_url
from ygo_app.cardmarket.paths import (
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
)
from ygo_app.cardmarket.rejections import merge_rejected_expansions
from ygo_app.cardmarket.scrape_session import ScrapeSession
from ygo_app.yugipedia.scrape_progress import log_line


def fetch_expansion_list_with_exclusions(session: ScrapeSession) -> tuple[list[dict], list[dict]]:
    """Fetch live expansion list from Cardmarket; return TCG rows and non-TCG rejections."""
    backend = session.backend
    discovery_rps = session.discovery_rps or DISCOVERY_REQUESTS_PER_SECOND

    scraper = None
    if backend == "cloudscraper":
        scraper = create_scraper(0)

    rate_limiter = AdaptiveRateLimiter(discovery_rps)
    html, error = fetch_url(
        scraper,
        SEARCH_URL,
        backend=backend,
        rate_limiter=rate_limiter,
    )
    if not html:
        raise RuntimeError(f"Failed to fetch expansion list: {error}")

    return parse_expansions_from_html_with_exclusions(html)


def fetch_expansion_list(session: ScrapeSession) -> list[dict]:
    """Fetch live TCG expansion list from Cardmarket without saving."""
    tcg, _ = fetch_expansion_list_with_exclusions(session)
    return tcg


def run_expansion_list_scrape(
    *,
    output: Path = CARDMARKET_EXPANSION_LIST_PATH,
    rejected_path: Path = CARDMARKET_REJECTED_EXPANSIONS_PATH,
    session: ScrapeSession,
) -> dict[str, int]:
    tcg, excluded = fetch_expansion_list_with_exclusions(session)
    save_json(output, tcg)
    if excluded:
        prior = load_json_list(rejected_path) if rejected_path.is_file() else []
        save_json(rejected_path, merge_rejected_expansions(prior, excluded))
    log_line(
        f"[EXPANSIONS] wrote {len(tcg)} TCG expansions, "
        f"excluded {len(excluded)} non-TCG to {output}"
    )
    return {"total": len(tcg), "excluded": len(excluded)}
