"""Job 1: fetch TCG expansion list from Cardmarket."""

from __future__ import annotations

from pathlib import Path

from ygo_app.cardmarket.artifact_io import save_json
from ygo_app.cardmarket.constants import DISCOVERY_REQUESTS_PER_SECOND, FetchBackend, SEARCH_URL
from ygo_app.cardmarket.expansions import parse_expansions_from_html
from ygo_app.cardmarket.http_client import AdaptiveRateLimiter, create_scraper, fetch_url
from ygo_app.cardmarket.paths import CARDMARKET_EXPANSION_LIST_PATH
from ygo_app.cardmarket.scrape_session import ScrapeSession
from ygo_app.yugipedia.scrape_progress import log_line


def fetch_expansion_list(session: ScrapeSession) -> list[dict]:
    """Fetch live TCG expansion list from Cardmarket without saving."""
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

    return parse_expansions_from_html(html)


def run_expansion_list_scrape(
    *,
    output: Path = CARDMARKET_EXPANSION_LIST_PATH,
    session: ScrapeSession,
) -> dict[str, int]:
    expansions = fetch_expansion_list(session)
    save_json(output, expansions)
    log_line(f"[EXPANSIONS] wrote {len(expansions)} TCG expansions to {output}")
    return {"total": len(expansions)}
