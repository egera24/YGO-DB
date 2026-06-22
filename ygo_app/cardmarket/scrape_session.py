"""Shared Cardmarket scrape session bootstrap (backend, CF cookies, Playwright)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from ygo_app import config
from ygo_app.cardmarket.browser_client import (
    close_browser_session,
    configure_browser_session,
    run_cf_login,
)
from ygo_app.cardmarket.browser_cookies import storage_has_cf_clearance
from ygo_app.cardmarket.browser_profiles import (
    active_browser_storage_path,
    resolve_profile_pool,
)
from ygo_app.cardmarket.constants import DEFAULT_WORKERS, FetchBackend
from ygo_app.cardmarket.http_client import default_fetch_backend, resolve_scrape_settings
from ygo_app.yugipedia.scrape_progress import log_line

CF_LOGIN_JOB = "python -m ygo_app.jobs.scrape_cardmarket_expansions --cf-login"


@dataclass(frozen=True)
class ScrapeSession:
    backend: FetchBackend
    workers: int
    discovery_rps: float
    price_rps: float
    headed: bool = False


def prepare_scrape_session(
    *,
    backend: FetchBackend | None = None,
    use_browser: bool = False,
    headed: bool = False,
    cf_login: bool = False,
    browser_channel: str | None = None,
    browser_profiles: str | None = None,
    workers: int = DEFAULT_WORKERS,
    price_rps: float | None = None,
    discovery_rps: float | None = None,
) -> ScrapeSession | int:
    """Return ScrapeSession, or exit code from --cf-login."""
    profile_pool = resolve_profile_pool(browser_profiles, config.CARDMARKET_BROWSER_PROFILES)

    if cf_login:
        channel = browser_channel or "chrome"
        return run_cf_login(
            browser_channel=channel,  # type: ignore[arg-type]
            profile_pool=profile_pool,
        )

    effective_backend = backend
    if use_browser and effective_backend is None:
        effective_backend = "playwright"
    if effective_backend is None:
        effective_backend = default_fetch_backend()

    effective_workers, eff_discovery_rps, eff_price_rps, backend_label = resolve_scrape_settings(
        backend=effective_backend,
        use_browser=use_browser,
        workers=workers,
        price_rps=price_rps,
        discovery_rps=discovery_rps,
    )

    if backend_label == "playwright":
        configure_browser_session(
            headed=headed,
            browser_channel=browser_channel or ("chrome" if headed else None),  # type: ignore[arg-type]
            profile_pool=profile_pool,
        )

    if backend_label in ("curl_cffi", "cloudscraper"):
        storage_path = active_browser_storage_path()
        if storage_has_cf_clearance(storage_path):
            log_line(f"[COOKIES] will reuse cf_clearance from {storage_path}")
        else:
            log_line(
                f"[WARN] No cf_clearance cookies found. If you get HTTP 403, run: {CF_LOGIN_JOB} "
                "or use --browser --headed --workers 1"
            )

    if len(profile_pool) > 1 and backend_label == "playwright":
        log_line(f"[PROFILE] pool={','.join(profile_pool)} (auto-rotate on warmup 429)")

    log_line(
        f"[CARDMARKET] backend={backend_label} workers={effective_workers} "
        f"discovery_rps={eff_discovery_rps} price_rps={eff_price_rps}"
        + (" headed" if headed and backend_label == "playwright" else "")
    )

    return ScrapeSession(
        backend=backend_label,
        workers=effective_workers,
        discovery_rps=eff_discovery_rps,
        price_rps=eff_price_rps,
        headed=headed,
    )


class scrape_session_context:
    """Context manager: teardown Playwright after a scrape job."""

    def __init__(self, session: ScrapeSession):
        self.session = session

    def __enter__(self) -> ScrapeSession:
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.session.backend == "playwright":
            close_browser_session()


def managed_scrape_session(**kwargs) -> Iterator[ScrapeSession]:
    result = prepare_scrape_session(**kwargs)
    if isinstance(result, int):
        raise SystemExit(result)
    with scrape_session_context(result) as session:
        yield session
