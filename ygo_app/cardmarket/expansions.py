"""Cardmarket expansion list fetch and DB cache."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ygo_app.cardmarket.constants import (
    BASE_URL,
    EXPANSION_CACHE_MAX_AGE_DAYS,
    FetchBackend,
    SEARCH_URL,
)
from ygo_app.cardmarket.expansion_seed import apply_seed_to_cache
from ygo_app.cardmarket.http_client import AdaptiveRateLimiter, create_scraper, fetch_url
from ygo_app.models import CardmarketExpansion
from ygo_app.yugipedia.scrape_progress import log_line


def is_ocg_expansion(expansion_name: str) -> bool:
    return "OCG" in expansion_name


def parse_expansions_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    select_element = soup.find("select", attrs={"name": "idExpansion"})
    if not select_element:
        return []

    tcg: dict[int, dict] = {}
    for option in select_element.find_all("option"):
        value = (option.get("value") or "").strip()
        text = option.get_text(strip=True)
        if not value or value == "0" or not value.isdigit():
            continue
        expansion_id = int(value)
        expansion_name = text.replace("&amp;", "&")
        if is_ocg_expansion(expansion_name):
            continue
        if expansion_id in tcg:
            continue
        tcg[expansion_id] = {
            "expansion_id": expansion_id,
            "expansion_name": expansion_name,
            "expansion_code": None,
        }
    return list(tcg.values())


def expansion_cache_is_fresh(session: Session, *, max_age_days: int = EXPANSION_CACHE_MAX_AGE_DAYS) -> bool:
    row = session.scalar(select(CardmarketExpansion.expansion_id).limit(1))
    if row is None:
        return False
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    stale = session.scalar(
        select(CardmarketExpansion.expansion_id)
        .where(CardmarketExpansion.fetched_at < cutoff)
        .limit(1)
    )
    return stale is None


def load_expansions_from_db(session: Session) -> list[CardmarketExpansion]:
    return list(session.scalars(select(CardmarketExpansion).order_by(CardmarketExpansion.expansion_id)))


def refresh_expansion_cache(
    session: Session,
    *,
    force: bool = False,
    backend: FetchBackend = "cloudscraper",
    discovery_rps: float = 3.0,
) -> int:
    apply_seed_to_cache(session)

    cache_fresh = expansion_cache_is_fresh(session)
    db_count = session.scalar(select(func.count()).select_from(CardmarketExpansion)) or 0
    if not force and cache_fresh:
        log_line(f"[EXPANSIONS] cache fresh ({db_count} rows)")
        apply_seed_to_cache(session)
        return int(db_count)

    existing_codes = {
        row.expansion_id: row.expansion_code
        for row in session.scalars(select(CardmarketExpansion)).all()
        if row.expansion_code
    }

    scraper = None
    if backend == "cloudscraper":
        scraper = create_scraper(0)
        try:
            scraper.get(f"{BASE_URL}/en/YuGiOh", timeout=15)
        except Exception:
            pass
        time.sleep(2)

    rate_limiter = AdaptiveRateLimiter(discovery_rps)
    html, error = fetch_url(
        scraper,
        SEARCH_URL,
        backend=backend,
        rate_limiter=rate_limiter,
    )
    if not html:
        raise RuntimeError(f"Failed to fetch expansion list: {error}")

    expansions = parse_expansions_from_html(html)
    now = datetime.utcnow()
    session.query(CardmarketExpansion).delete()
    for row in expansions:
        eid = row["expansion_id"]
        session.add(
            CardmarketExpansion(
                expansion_id=eid,
                expansion_code=existing_codes.get(eid),
                expansion_name=row["expansion_name"],
                fetched_at=now,
            )
        )
    session.commit()
    apply_seed_to_cache(session)
    log_line(f"[EXPANSIONS] cached {len(expansions)} TCG expansions")
    return len(expansions)


def resolve_expansion_ids(
    session: Session,
    expansion_codes: set[str],
    *,
    force_refresh: bool = False,
    backend: FetchBackend = "cloudscraper",
    discovery_rps: float = 3.0,
) -> dict[str, int]:
    """
    Map Yugipedia expansion prefix → Cardmarket expansion_id.
    Uses expansion_code on cached rows when set; otherwise scrapes expansion product
    list pages to learn codes (only while needed codes remain unresolved).
    """
    refresh_expansion_cache(
        session,
        force=force_refresh,
        backend=backend,
        discovery_rps=discovery_rps,
    )
    apply_seed_to_cache(session)
    rows = load_expansions_from_db(session)

    by_code: dict[str, int] = {}
    for row in rows:
        if row.expansion_code:
            by_code[row.expansion_code.upper()] = row.expansion_id

    missing = {code.upper() for code in expansion_codes if code.upper() not in by_code}
    if missing:
        log_line(f"[EXPANSIONS] resolving {len(missing)} codes via product list probe")
        from ygo_app.cardmarket.product_list import probe_expansion_code

        rate_limiter = AdaptiveRateLimiter(discovery_rps)
        scraper = create_scraper(0) if backend == "cloudscraper" else None
        probes = 0
        for row in rows:
            if not missing:
                break
            if row.expansion_code:
                continue
            probes += 1
            code = probe_expansion_code(
                scraper,
                row.expansion_id,
                row.expansion_name,
                rate_limiter=rate_limiter,
                backend=backend,
            )
            if not code:
                continue
            code_upper = code.upper()
            db_row = session.get(CardmarketExpansion, row.expansion_id)
            if db_row:
                db_row.expansion_code = code_upper
            if code_upper in missing:
                by_code[code_upper] = row.expansion_id
                missing.discard(code_upper)
        session.commit()
        log_line(f"[EXPANSIONS] probe requests={probes} remaining_missing={len(missing)}")

    return {code: by_code[code] for code in expansion_codes if code.upper() in by_code}
