"""Job 1: fetch TCG expansion list from Cardmarket."""

from __future__ import annotations

from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list, save_json_atomic
from ygo_app.cardmarket.constants import DISCOVERY_REQUESTS_PER_SECOND, SEARCH_URL
from ygo_app.cardmarket.expansions import parse_expansions_from_html_with_exclusions
from ygo_app.cardmarket.http_client import AdaptiveRateLimiter, create_scraper, fetch_url
from ygo_app.cardmarket.paths import (
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
    expansion_list_path,
)
from ygo_app.cardmarket.rejections import merge_rejected_expansions
from ygo_app.cardmarket.scrape_session import ScrapeSession
from ygo_app.cardmarket.scrape_state import (
    assign_expansion_seq,
    ensure_scrape_state,
    load_scrape_state,
    save_scrape_state,
    today_run_date,
    update_state_seq,
)
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
    return assign_expansion_seq(tcg)


def run_expansion_list_scrape(
    *,
    output: Path | None = None,
    rejected_path: Path = CARDMARKET_REJECTED_EXPANSIONS_PATH,
    session: ScrapeSession,
    run_date: str | None = None,
) -> dict[str, int]:
    rd = run_date or today_run_date()
    out = output or expansion_list_path(rd)

    tcg, excluded = fetch_expansion_list_with_exclusions(session)
    tcg = assign_expansion_seq(tcg)
    save_json_atomic(out, tcg)

    if excluded:
        prior = load_json_list(rejected_path) if rejected_path.is_file() else []
        save_json_atomic(rejected_path, merge_rejected_expansions(prior, excluded))

    state = ensure_scrape_state(run_date=rd, mode="full", phase="expansion_list", reset=True)
    state["expansion_list_file"] = out.name
    state["card_list_file"] = f"card_list_{rd}.json"
    state["last_completed_seq"] = len(tcg)
    state["phase"] = "card_list"
    save_scrape_state(state)

    log_line(
        f"[EXPANSIONS] wrote {len(tcg)} TCG expansions (seq 1..{len(tcg)}) to {out}, "
        f"excluded {len(excluded)} non-TCG"
    )
    return {"total": len(tcg), "excluded": len(excluded)}


def load_dated_expansion_list(run_date: str | None = None) -> list[dict]:
    """Load expansion list for run_date from state or explicit date."""
    if run_date:
        return load_json_list(expansion_list_path(run_date))
    state = load_scrape_state()
    if state and state.get("expansion_list_file"):
        from ygo_app.cardmarket.paths import CATALOG_DIR

        return load_json_list(CATALOG_DIR / str(state["expansion_list_file"]))
    latest = expansion_list_path(today_run_date())
    if latest.is_file():
        return load_json_list(latest)
    raise FileNotFoundError("No expansion list found; run scrape_cardmarket_expansions first")
