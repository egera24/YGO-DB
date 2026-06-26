"""Job 2: scrape Cardmarket expansion product lists (all TCG cards)."""

from __future__ import annotations

import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from ygo_app.cardmarket.artifact_io import (
    load_json_list,
    save_json,
    save_json_atomic,
)
from ygo_app.cardmarket.card_list_consistency import (
    CardListConsistencyError,
    assert_no_seq_gaps,
    copy_cards_for_incremental,
    expansions_for_new_ids,
)
from ygo_app.cardmarket.card_list_validate import (
    CardListValidationError,
    validate_expansion_slice,
)
from ygo_app.cardmarket.catalog_consistency import (
    CardListCoverageError,
    audit_card_list_coverage,
)
from ygo_app.cardmarket.constants import (
    DISCOVERY_MAX_RETRIES,
    DISCOVERY_REQUESTS_PER_SECOND,
    FetchBackend,
    INTER_EXPANSION_DELAY_BROWSER,
    RANDOM_JITTER,
    RECOVERY_REQUESTS_PER_SECOND,
)
from ygo_app.cardmarket.expansions import (
    REJECTION_REASON_NOT_TCG,
    build_exclusion_rejection,
    exclusion_category,
    partition_expansions,
)
from ygo_app.cardmarket.http_client import (
    AdaptiveRateLimiter,
    RateLimitAbort,
    ScrapeShutdown,
    clear_scrape_shutdown,
    create_session_pool,
    fetch_url,
    request_scrape_shutdown,
    scrape_shutdown_requested,
)
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_EMPTY_EXPANSIONS_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
    card_list_path,
)
from ygo_app.cardmarket.scrape_state import (
    find_latest_card_list,
    find_latest_expansion_list,
    load_scrape_state,
    next_expansion_seq,
    resolve_card_list_file,
    resolve_expansion_list_file,
    rollback_cards_after_seq,
    save_scrape_state,
    today_run_date,
    update_state_seq,
)
from ygo_app.cardmarket.product_list import (
    _search_url,
    extract_cards_from_html,
    is_only_sealed_products,
    is_product_page_redirect,
)
from ygo_app.cardmarket.rejections import (
    is_non_recoverable_rejection,
    merge_rejected_expansions,
    rejections_for_save,
)
from ygo_app.cardmarket.scrape_prompts import prompt_no_product_rows
from ygo_app.cardmarket.scrape_session import ScrapeSession
from ygo_app.yugipedia.scrape_progress import log_line

PHASE1_MAX_RETRIES = 2
PHASE1_RETRY_DELAY = (12, 18)
PHASE2_MAX_RETRIES = 5
PHASE2_RETRY_DELAY = (20, 30)

_file_lock = threading.Lock()


def _rejection_row_from_worker(expansion: dict[str, Any], result: dict[str, Any]) -> dict:
    row: dict[str, Any] = {
        "expansion_id": expansion["expansion_id"],
        "expansion_name": expansion["expansion_name"],
        "total_attempts": len(result.get("attempts") or []),
        "attempts_detail": result.get("attempts") or [],
    }
    if result.get("rejection_reason"):
        row["rejection_reason"] = result["rejection_reason"]
    if result.get("exclusion_category"):
        row["exclusion_category"] = result["exclusion_category"]
    return row


def _enforce_card_list_coverage(
    *,
    expansions: list[dict[str, Any]],
    all_cards: list[dict],
    empty_expansions: list[dict],
    rejected_expansions: list[dict],
) -> None:
    """Raise when job-2 artifacts do not fully account for every expansion row."""
    report = audit_card_list_coverage(
        expansion_list=expansions,
        card_list=all_cards,
        empty_expansions=empty_expansions,
        rejected_expansions=rejected_expansions,
    )
    if report.ok:
        return

    gap_total = report.unaccounted + report.never_scraped + report.ghost_processed
    log_line(
        f"[CARD_LIST] coverage check failed: {gap_total} expansion gap(s), "
        f"{len(report.orphan_card_expansion_ids)} orphan card expansion(s), "
        f"{len(report.duplicate_card_ids)} duplicate card_id(s)"
    )
    log_line("  Run: python -m ygo_app.jobs.cardmarket_catalog_status --strict")
    raise CardListCoverageError(
        f"Card list coverage incomplete ({gap_total} expansion gap(s))"
    )


def _purge_non_tcg_expansions(
    expansions: list[dict],
    *,
    expansion_list_path: Path,
    rejected_path: Path,
    empty_path: Path,
    empty_expansions: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Remove non-TCG expansions from the scrape list and persist rejections."""
    tcg, excluded = partition_expansions(expansions)
    prior = load_json_list(rejected_path) if rejected_path.is_file() else []
    merged_rejections = merge_rejected_expansions(prior, excluded)

    empties = list(empty_expansions or [])
    if not empties and empty_path.is_file():
        empties = load_json_list(empty_path)

    kept_empty: list[dict] = []
    migrated: list[dict] = []
    for row in empties:
        category = exclusion_category(row.get("expansion_name", ""))
        if category:
            migrated.append(build_exclusion_rejection(row, category))
        else:
            kept_empty.append(row)
    if migrated:
        merged_rejections = merge_rejected_expansions(merged_rejections, migrated)

    if excluded or migrated:
        excluded_ids = {int(r["expansion_id"]) for r in excluded}
        if excluded_ids:
            log_line(
                f"[CARD_LIST] excluded {len(excluded_ids)} non-TCG expansions "
                f"from scrape list: {sorted(excluded_ids)[:12]}"
                f"{'...' if len(excluded_ids) > 12 else ''}"
            )
        if migrated:
            log_line(
                f"[CARD_LIST] migrated {len(migrated)} empty non-TCG expansions to rejected"
            )
        save_json(expansion_list_path, tcg)
        save_json(rejected_path, merged_rejections)
        if empty_path.is_file() or migrated:
            save_json(empty_path, kept_empty)

    return tcg, kept_empty, merged_rejections


def _is_empty_first_page(html: str) -> bool:
    if "Sorry, no matches" in html:
        return True
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("p", class_=re.compile(r"noResults")):
        return True
    return False


def scrape_expansion_pages(
    *,
    expansion_id: int,
    expansion_name: str,
    expansion_seq: int | None = None,
    backend: FetchBackend,
    rate_limiter: AdaptiveRateLimiter,
    session_pool,
    worker_id: int,
    scraper,
    is_recovery: bool = False,
    interactive: bool = True,
) -> tuple[list[dict], str | None, list[str], bool]:
    """Returns (cards, expansion_code, fetch_issues, is_genuinely_empty)."""
    all_cards: list[dict] = []
    page = 1
    expansion_code: str | None = None
    fetch_issues: list[str] = []

    while True:
        if scrape_shutdown_requested():
            break
        html, error = fetch_url(
            scraper,
            _search_url(expansion_id, page),
            backend=backend,
            rate_limiter=rate_limiter,
            jitter=0.0 if backend == "playwright" else RANDOM_JITTER,
            session_pool=session_pool,
            worker_id=worker_id,
            retries=DISCOVERY_MAX_RETRIES,
        )

        if error:
            fetch_issues.append(f"Page {page}: {error}")
            break
        if not html:
            fetch_issues.append(f"Page {page}: No HTML")
            break

        if is_product_page_redirect(html):
            return all_cards, expansion_code, fetch_issues, True
        if page == 1 and _is_empty_first_page(html):
            return all_cards, expansion_code, fetch_issues, True
        if page == 1 and is_only_sealed_products(html):
            return all_cards, expansion_code, fetch_issues, True

        soup = BeautifulSoup(html, "html.parser")
        product_rows = soup.find_all("div", id=re.compile(r"^productRow\d+"))
        if not product_rows:
            if page == 1:
                action = prompt_no_product_rows(
                    url=_search_url(expansion_id, page),
                    expansion_id=expansion_id,
                    expansion_name=expansion_name,
                    enabled=interactive,
                )
                if action == "terminate":
                    request_scrape_shutdown()
                    raise ScrapeShutdown("User terminated: no product rows on page 1")
                if action == "retry":
                    continue
                fetch_issues.append(f"Page {page}: No product rows")
            break

        cards, exp_code = extract_cards_from_html(
            html,
            expansion_id=expansion_id,
            expansion_name=expansion_name,
            expansion_code=expansion_code,
            expansion_seq=expansion_seq,
        )
        if not cards:
            if page == 1:
                fetch_issues.append(f"Page {page}: No cards extracted")
            break

        if page == 1:
            expansion_code = exp_code

        all_cards.extend(cards)
        page += 1

    return all_cards, expansion_code, fetch_issues, False

def _scrape_expansion_worker(
    worker_id: int,
    expansion: dict[str, Any],
    *,
    backend: FetchBackend,
    rate_limiter: AdaptiveRateLimiter,
    session_pool,
    max_retries: int,
    retry_delay_range: tuple[float, float],
    is_recovery: bool,
    interactive: bool = True,
) -> dict[str, Any]:
    expansion_id = expansion["expansion_id"]
    expansion_name = expansion.get("expansion_name", f"Expansion {expansion_id}")
    expansion_seq = expansion.get("seq")

    category = exclusion_category(expansion_name)
    if category:
        return {
            "expansion": expansion,
            "cards": [],
            "total_count": 0,
            "expansion_code": None,
            "attempts": [],
            "status": "rejected",
            "is_empty": False,
            "rejection_reason": REJECTION_REASON_NOT_TCG,
            "exclusion_category": category,
        }

    best_result: dict | None = None
    best_card_count = 0
    all_attempts: list[dict] = []
    is_genuinely_empty = False

    for attempt in range(1, max_retries + 1):
        scraper = None
        if session_pool is not None:
            scraper, _ = session_pool.get_session(worker_id)

        cards, expansion_code, fetch_issues, is_empty = scrape_expansion_pages(
            expansion_id=expansion_id,
            expansion_name=expansion_name,
            expansion_seq=int(expansion_seq) if expansion_seq is not None else None,
            backend=backend,
            rate_limiter=rate_limiter,
            session_pool=session_pool,
            worker_id=worker_id,
            scraper=scraper,
            is_recovery=is_recovery,
            interactive=interactive,
        )

        all_attempts.append(
            {"attempt": attempt, "card_count": len(cards), "issues": fetch_issues, "is_empty": is_empty}
        )

        if is_empty:
            is_genuinely_empty = True
            break

        if len(cards) > best_card_count:
            best_card_count = len(cards)
            best_result = {"cards": cards, "expansion_code": expansion_code, "attempt": attempt}

        if cards:
            break

        has_403 = any("403" in issue for issue in fetch_issues)
        if has_403 and attempt < max_retries:
            time.sleep(random.uniform(30, 45))
        elif attempt < max_retries:
            time.sleep(random.uniform(*retry_delay_range))

    if best_result:
        return {
            "expansion": expansion,
            "cards": best_result["cards"],
            "total_count": len(best_result["cards"]),
            "expansion_code": best_result["expansion_code"],
            "attempts": all_attempts,
            "status": "success",
            "is_empty": False,
        }
    if is_genuinely_empty:
        return {
            "expansion": expansion,
            "cards": [],
            "total_count": 0,
            "expansion_code": None,
            "attempts": all_attempts,
            "status": "empty",
            "is_empty": True,
        }
    return {
        "expansion": expansion,
        "cards": [],
        "total_count": 0,
        "expansion_code": None,
        "attempts": all_attempts,
        "status": "rejected",
        "is_empty": False,
    }


def _save_card_list_artifacts(
    *,
    all_cards: list[dict],
    expansions: list[dict],
    empty_expansions: list[dict],
    rejected_expansions: list[dict],
    card_list_path: Path,
    expansion_list_path: Path,
    empty_path: Path,
    rejected_path: Path,
    atomic: bool = True,
) -> None:
    saver = save_json_atomic if atomic else save_json
    with _file_lock:
        saver(card_list_path, all_cards)
        saver(expansion_list_path, expansions)
        if empty_expansions:
            saver(empty_path, empty_expansions)
        if rejected_expansions:
            saver(rejected_path, rejected_expansions)


def _tag_cards_with_seq(cards: list[dict], expansion: dict[str, Any]) -> list[dict]:
    seq = int(expansion["seq"])
    tagged: list[dict] = []
    for card in cards:
        row = dict(card)
        row["expansion_seq"] = seq
        row["expansion_id"] = int(expansion["expansion_id"])
        row["expansion_name"] = expansion.get("expansion_name", row.get("expansion_name", ""))
        if expansion.get("expansion_code"):
            row["expansion_code"] = expansion["expansion_code"]
        tagged.append(row)
    return tagged


def _sidecar_row(expansion: dict[str, Any]) -> dict[str, Any]:
    return {
        "expansion_seq": int(expansion["seq"]),
        "expansion_id": int(expansion["expansion_id"]),
        "expansion_name": expansion.get("expansion_name", ""),
        "expansion_code": expansion.get("expansion_code"),
    }


def _remove_cards_for_seq(cards: list[dict], seq: int) -> list[dict]:
    return [c for c in cards if int(c.get("expansion_seq", 0)) != seq]


def _remove_sidecar_seq(rows: list[dict], seq: int) -> list[dict]:
    return [r for r in rows if int(r.get("expansion_seq", 0)) != seq]


def _run_phase2_recovery(
    *,
    rejected_list: list[dict],
    expansions: list[dict],
    all_cards: list[dict],
    empty_expansions: list[dict],
    backend: FetchBackend,
    interactive: bool,
) -> tuple[list[dict], list[dict], list[dict], dict[str, int]]:
    """Serial recovery for rejected expansions; returns updated artifacts + stats delta."""
    if not rejected_list:
        return all_cards, empty_expansions, rejected_list, {"success": 0, "empty": 0, "rejected": 0}

    log_line(f"[CARD_LIST] phase2 recovery for {len(rejected_list)} rejected expansions")
    recovery_limiter = AdaptiveRateLimiter(RECOVERY_REQUESTS_PER_SECOND)
    still_rejected: list[dict] = []
    stats = {"success": 0, "empty": 0, "rejected": 0}
    exp_by_id = {int(e["expansion_id"]): e for e in expansions}

    for rejected_exp in rejected_list:
        if is_non_recoverable_rejection(rejected_exp):
            still_rejected.append(rejected_exp)
            continue
        eid = int(rejected_exp["expansion_id"])
        expansion = exp_by_id.get(eid) or {
            "expansion_id": eid,
            "expansion_name": rejected_exp.get("expansion_name", ""),
            "seq": rejected_exp.get("expansion_seq"),
        }
        try:
            result = _scrape_expansion_worker(
                0,
                expansion,
                backend=backend,
                rate_limiter=recovery_limiter,
                session_pool=None,
                max_retries=PHASE2_MAX_RETRIES,
                retry_delay_range=PHASE2_RETRY_DELAY,
                is_recovery=True,
                interactive=interactive,
            )
        except ScrapeShutdown:
            raise

        seq = int(expansion.get("seq") or rejected_exp.get("expansion_seq") or 0)
        all_cards = [c for c in all_cards if int(c.get("expansion_seq", 0)) != seq]
        empty_expansions = _remove_sidecar_seq(empty_expansions, seq)

        if result["status"] == "success":
            cards = _tag_cards_with_seq(result["cards"], expansion)
            known = {int(c["card_id"]) for c in all_cards}
            validate_expansion_slice(cards, expansion=expansion, known_card_ids=known)
            all_cards.extend(cards)
            expansion["total_number_of_cards"] = result["total_count"]
            if result.get("expansion_code"):
                expansion["expansion_code"] = result["expansion_code"]
            stats["success"] += 1
        elif result["status"] == "empty":
            row = _sidecar_row(expansion)
            row["total_number_of_cards"] = 0
            empty_expansions.append(row)
            stats["empty"] += 1
        else:
            row = _rejection_row_from_worker(expansion, result)
            row["expansion_seq"] = seq
            still_rejected.append(row)
            stats["rejected"] += 1

    return all_cards, empty_expansions, still_rejected, stats


def scrape_expansions(
    expansions: list[dict[str, Any]],
    *,
    session: ScrapeSession,
) -> dict[str, Any]:
    """Scrape product lists for the given expansions only (no checkpoint resume)."""
    if not expansions:
        return {
            "cards": [],
            "empty_expansions": [],
            "rejected_expansions": [],
            "success": 0,
            "empty": 0,
            "rejected": 0,
        }

    backend = session.backend
    workers = session.workers
    interactive = session.interactive
    discovery_rps = session.discovery_rps or DISCOVERY_REQUESTS_PER_SECOND
    rate_limiter = AdaptiveRateLimiter(discovery_rps)
    session_pool = create_session_pool(backend, workers)

    scraped_cards: list[dict] = []
    empty_expansions: list[dict] = []
    rejected_list: list[dict] = []
    stats = {"success": 0, "empty": 0, "rejected": 0}
    completed = 0
    start_time = datetime.now()

    log_line(
        f"[CARD_LIST] targeted scrape workers={workers} rps={discovery_rps} "
        f"expansions={len(expansions)}"
    )

    clear_scrape_shutdown()
    interrupted = False
    executor = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures: dict = {}
        for idx, expansion in enumerate(expansions):
            worker_id = idx % max(workers, 1)
            future = executor.submit(
                _scrape_expansion_worker,
                worker_id,
                expansion,
                backend=backend,
                rate_limiter=rate_limiter,
                session_pool=session_pool,
                max_retries=PHASE1_MAX_RETRIES,
                retry_delay_range=PHASE1_RETRY_DELAY,
                is_recovery=False,
                interactive=interactive,
            )
            futures[future] = expansion

        for future in as_completed(futures):
            expansion = futures[future]
            try:
                result = future.result()
            except RateLimitAbort:
                raise
            except ScrapeShutdown:
                interrupted = True
                request_scrape_shutdown()
                for f in futures:
                    f.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                break

            expansion["total_number_of_cards"] = result["total_count"]
            if result.get("expansion_code"):
                expansion["expansion_code"] = result["expansion_code"]

            scraped_cards.extend(result["cards"])

            if result["status"] == "empty":
                empty_expansions.append(dict(expansion))
                stats["empty"] += 1
            elif result["status"] == "rejected":
                rejected_list.append(_rejection_row_from_worker(expansion, result))
                stats["rejected"] += 1
            else:
                stats["success"] += 1

            completed += 1
            cards_suffix = (
                f", {result['total_count']} cards" if result["total_count"] else ""
            )
            log_line(
                f"[CARD_LIST] expansion {expansion.get('expansion_id')} "
                f"({completed}/{len(expansions)}): {result['status']}{cards_suffix}"
            )

            if backend == "playwright":
                time.sleep(random.uniform(*INTER_EXPANSION_DELAY_BROWSER))
    finally:
        if not interrupted:
            executor.shutdown(wait=True)

    if interrupted:
        log_line("[CARD_LIST] terminated by user — partial results only")
        return {
            "cards": scraped_cards,
            "empty_expansions": empty_expansions,
            "rejected_expansions": rejected_list,
            **stats,
            "rejected": len(rejected_list),
            "interrupted": 1,
        }

    if rejected_list:
        log_line(f"[CARD_LIST] phase2 recovery for {len(rejected_list)} rejected expansions")
        recovery_limiter = AdaptiveRateLimiter(RECOVERY_REQUESTS_PER_SECOND)
        still_rejected: list[dict] = []
        for rejected_exp in rejected_list:
            if is_non_recoverable_rejection(rejected_exp):
                still_rejected.append(rejected_exp)
                continue
            expansion = {
                "expansion_id": rejected_exp["expansion_id"],
                "expansion_name": rejected_exp["expansion_name"],
            }
            try:
                result = _scrape_expansion_worker(
                    0,
                    expansion,
                    backend=backend,
                    rate_limiter=recovery_limiter,
                    session_pool=None,
                    max_retries=PHASE2_MAX_RETRIES,
                    retry_delay_range=PHASE2_RETRY_DELAY,
                    is_recovery=True,
                    interactive=interactive,
                )
            except ScrapeShutdown:
                log_line("[CARD_LIST] terminated by user — partial results only")
                return {
                    "cards": scraped_cards,
                    "empty_expansions": empty_expansions,
                    "rejected_expansions": still_rejected + [
                        r for r in rejected_list if r not in still_rejected
                    ],
                    **stats,
                    "rejected": len(still_rejected),
                    "interrupted": 1,
                }
            if result["status"] == "success":
                scraped_cards.extend(result["cards"])
                for exp in expansions:
                    if exp["expansion_id"] == expansion["expansion_id"]:
                        exp["total_number_of_cards"] = result["total_count"]
                        if result.get("expansion_code"):
                            exp["expansion_code"] = result["expansion_code"]
                        break
                stats["success"] += 1
                stats["rejected"] -= 1
            elif result["status"] == "empty":
                empty_expansions.append(expansion)
                stats["empty"] += 1
                stats["rejected"] -= 1
            else:
                still_rejected.append(rejected_exp)
        rejected_list = still_rejected

    elapsed = (datetime.now() - start_time).total_seconds()
    log_line(
        f"[CARD_LIST] targeted cards={len(scraped_cards)} success={stats['success']} "
        f"empty={stats['empty']} rejected={len(rejected_list)} elapsed={elapsed:.0f}s"
    )
    return {
        "cards": scraped_cards,
        "empty_expansions": empty_expansions,
        "rejected_expansions": rejected_list,
        **stats,
        "rejected": len(rejected_list),
    }


def run_card_list_scrape(
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
    expansion_list_path: Path | None = None,
    empty_path: Path = CARDMARKET_EMPTY_EXPANSIONS_PATH,
    rejected_path: Path = CARDMARKET_REJECTED_EXPANSIONS_PATH,
    session: ScrapeSession,
    resume: bool = False,
    limit: int | None = None,
    load_mode: str = "full",
    expansion_filter: set[int] | None = None,
    purge_expansion_ids: set[int] | None = None,
    skip_same_day: bool = False,
) -> dict[str, int]:
    """Scrape card lists with dated artifacts and scrape_state.json resume."""
    backend = session.backend
    interactive = session.interactive
    discovery_rps = session.discovery_rps or DISCOVERY_REQUESTS_PER_SECOND
    rate_limiter = AdaptiveRateLimiter(discovery_rps)
    session_pool = create_session_pool(backend, max(1, session.workers))

    state = load_scrape_state()
    run_date = state.get("run_date") if state else today_run_date()
    if not state:
        run_date = today_run_date()

    exp_list_path = expansion_list_path or (
        resolve_expansion_list_file(state) if state else input_path or CARDMARKET_EXPANSION_LIST_PATH
    )
    card_out = output_path or (
        resolve_card_list_file(state) if state else card_list_path(run_date)
    )

    expansions = load_json_list(exp_list_path)
    if "seq" not in (expansions[0] if expansions else {}):
        from ygo_app.cardmarket.scrape_state import assign_expansion_seq

        expansions = assign_expansion_seq(expansions)
        save_json_atomic(exp_list_path, expansions)

    empty_for_purge = load_json_list(empty_path) if empty_path.is_file() else []
    expansions, _, _ = _purge_non_tcg_expansions(
        expansions,
        expansion_list_path=exp_list_path,
        rejected_path=rejected_path,
        empty_path=empty_path,
        empty_expansions=empty_for_purge,
    )

    if expansion_filter is not None:
        expansions = [e for e in expansions if int(e["expansion_id"]) in expansion_filter]
        if not expansions:
            log_line("[CARD_LIST] nothing to do (expansion filter empty)")
            return {"cards": 0, "empty": 0, "rejected": 0}

        existing_cards = load_json_list(card_out) if card_out.is_file() else []
        scrape_result = scrape_expansions(expansions, session=session)
        if scrape_result.get("interrupted"):
            return {
                "cards": len(existing_cards),
                "success": scrape_result.get("success", 0),
                "empty": scrape_result.get("empty", 0),
                "rejected": scrape_result.get("rejected", 0),
                "interrupted": 1,
            }

        from ygo_app.cardmarket.incremental import merge_card_lists, raise_on_conflicts

        tagged = []
        exp_by_id = {int(e["expansion_id"]): e for e in expansions}
        for card in scrape_result["cards"]:
            eid = int(card["expansion_id"])
            exp = exp_by_id.get(eid)
            if exp:
                tagged.extend(_tag_cards_with_seq([card], exp))
            else:
                tagged.append(card)

        merged_cards, conflicts = merge_card_lists(
            existing_cards,
            tagged,
            purge_expansion_ids=purge_expansion_ids,
        )
        raise_on_conflicts(conflicts)

        all_expansions = load_json_list(exp_list_path)
        exp_by_id = {int(e["expansion_id"]): e for e in all_expansions}
        for exp in expansions:
            eid = int(exp["expansion_id"])
            if eid in exp_by_id:
                exp_by_id[eid].update(
                    {
                        k: exp[k]
                        for k in ("total_number_of_cards", "expansion_code")
                        if k in exp
                    }
                )
            else:
                exp_by_id[eid] = exp
        merged_expansion_list = sorted(exp_by_id.values(), key=lambda e: int(e["expansion_id"]))

        empty_expansions = load_json_list(empty_path) if empty_path.is_file() else []
        empty_expansions.extend(scrape_result["empty_expansions"])
        prior_rejections = load_json_list(rejected_path) if rejected_path.is_file() else []
        scraped_ids = {int(e["expansion_id"]) for e in expansions}
        still_rejected_ids = {
            int(r["expansion_id"]) for r in scrape_result["rejected_expansions"]
        }
        recovered_ids = scraped_ids - still_rejected_ids
        prior_rejections = [
            r for r in prior_rejections if int(r["expansion_id"]) not in recovered_ids
        ]
        rejected_expansions = merge_rejected_expansions(
            prior_rejections,
            scrape_result["rejected_expansions"],
        )

        _save_card_list_artifacts(
            all_cards=merged_cards,
            expansions=merged_expansion_list,
            empty_expansions=empty_expansions,
            rejected_expansions=rejected_expansions,
            card_list_path=card_out,
            expansion_list_path=exp_list_path,
            empty_path=empty_path,
            rejected_path=rejected_path,
        )
        return {
            "cards": len(merged_cards),
            "success": scrape_result["success"],
            "empty": scrape_result["empty"],
            "rejected": scrape_result["rejected"],
        }

    if skip_same_day and card_out.is_file() and state.get("run_date") == today_run_date():
        if state.get("phase") == "done" or int(state.get("last_completed_seq", 0)) >= len(expansions):
            log_line(f"[CARD_LIST] same-day skip: {card_out.name} already complete")
            return {"cards": len(load_json_list(card_out)), "empty": 0, "rejected": 0, "skipped": 1}

    if not state or state.get("run_date") != run_date:
        from ygo_app.cardmarket.scrape_state import ensure_scrape_state

        state = ensure_scrape_state(run_date=run_date, mode=load_mode, phase="card_list", reset=False)
        state["expansion_list_file"] = exp_list_path.name
        state["card_list_file"] = card_out.name
        state["mode"] = load_mode
        save_scrape_state(state)

    all_cards: list[dict] = []
    empty_expansions: list[dict] = []
    rejected_expansions: list[dict] = load_json_list(rejected_path) if rejected_path.is_file() else []

    if load_mode == "incremental":
        prev = find_latest_card_list()
        if prev and prev[0] != run_date:
            prev_date, prev_path = prev
            prev_list_info = find_latest_expansion_list()
            if prev_list_info:
                _, prev_exp_path = prev_list_info
                prev_list = load_json_list(prev_exp_path)
                prev_cards = load_json_list(prev_path)
                all_cards = copy_cards_for_incremental(
                    today_list=expansions,
                    prev_cards=prev_cards,
                    prev_list=prev_list,
                )
                to_scrape = expansions_for_new_ids(
                    expansions,
                    {int(e["expansion_id"]) for e in prev_list},
                )
                expansions = to_scrape
                log_line(
                    f"[CARD_LIST] incremental: copied {len(all_cards)} cards, "
                    f"scraping {len(to_scrape)} new expansion(s)"
                )
    elif card_out.is_file() and not resume:
        all_cards = []

    if resume and card_out.is_file():
        all_cards = load_json_list(card_out)
        if empty_path.is_file():
            empty_expansions = load_json_list(empty_path)
        last_seq = int(state.get("last_completed_seq", 0))
        assert_no_seq_gaps(
            last_completed_seq=last_seq,
            cards=all_cards,
            empty_expansions=empty_expansions,
            rejected_expansions=rejected_expansions,
        )
        all_cards = rollback_cards_after_seq(all_cards, last_seq)
        empty_expansions = [
            e for e in empty_expansions if int(e.get("expansion_seq", 0)) <= last_seq
        ]
        log_line(f"[CARD_LIST] resume from seq {next_expansion_seq(state)}")
    elif card_out.is_file() and load_mode == "full":
        all_cards = []

    if limit is not None:
        expansions = expansions[:limit]

    start_seq = next_expansion_seq(state) if resume else 1
    if resume:
        expansions = [e for e in expansions if int(e.get("seq", 0)) >= start_seq]
    elif load_mode == "incremental":
        pass
    else:
        expansions = [e for e in expansions if int(e.get("seq", 0)) >= start_seq]

    if not expansions and all_cards:
        log_line("[CARD_LIST] nothing to scrape")
        return {"cards": len(all_cards), "empty": len(empty_expansions), "rejected": 0}

    stats = {"success": 0, "empty": 0, "rejected": 0}
    pending_rejected: list[dict] = []
    start_time = datetime.now()
    clear_scrape_shutdown()

    log_line(
        f"[CARD_LIST] serial scrape rps={discovery_rps} expansions={len(expansions)} "
        f"mode={load_mode} run_date={run_date}"
    )

    known_card_ids = {int(c["card_id"]) for c in all_cards}

    try:
        for completed, expansion in enumerate(expansions, start=1):
            if scrape_shutdown_requested():
                raise ScrapeShutdown("shutdown requested")

            seq = int(expansion["seq"])
            result = _scrape_expansion_worker(
                0,
                expansion,
                backend=backend,
                rate_limiter=rate_limiter,
                session_pool=session_pool,
                max_retries=PHASE1_MAX_RETRIES,
                retry_delay_range=PHASE1_RETRY_DELAY,
                is_recovery=False,
                interactive=interactive,
            )

            all_cards = _remove_cards_for_seq(all_cards, seq)
            empty_expansions = _remove_sidecar_seq(empty_expansions, seq)
            rejected_expansions = [
                r for r in rejected_expansions if int(r.get("expansion_seq", 0)) != seq
            ]

            expansion["total_number_of_cards"] = result["total_count"]
            if result.get("expansion_code"):
                expansion["expansion_code"] = result["expansion_code"]

            if result["status"] == "success":
                cards = _tag_cards_with_seq(result["cards"], expansion)
                validate_expansion_slice(cards, expansion=expansion, known_card_ids=known_card_ids)
                all_cards.extend(cards)
                known_card_ids.update(int(c["card_id"]) for c in cards)
                stats["success"] += 1
            elif result["status"] == "empty":
                empty_expansions.append(_sidecar_row(expansion))
                stats["empty"] += 1
            else:
                row = _rejection_row_from_worker(expansion, result)
                row["expansion_seq"] = seq
                pending_rejected.append(row)
                stats["rejected"] += 1

            _save_card_list_artifacts(
                all_cards=all_cards,
                expansions=load_json_list(exp_list_path),
                empty_expansions=empty_expansions,
                rejected_expansions=rejections_for_save(rejected_expansions, pending_rejected),
                card_list_path=card_out,
                expansion_list_path=exp_list_path,
                empty_path=empty_path,
                rejected_path=rejected_path,
            )
            state = update_state_seq(state, seq, phase="card_list")

            cards_suffix = (
                f", {result['total_count']} cards" if result["total_count"] else ""
            )
            log_line(
                f"[CARD_LIST] seq={seq} expansion {expansion.get('expansion_id')} "
                f"({completed}/{len(expansions)}): {result['status']}{cards_suffix}"
            )

            if backend == "playwright":
                time.sleep(random.uniform(*INTER_EXPANSION_DELAY_BROWSER))

    except (ScrapeShutdown, KeyboardInterrupt):
        log_line("[CARD_LIST] interrupted — progress saved in scrape state")
        return {
            "cards": len(all_cards),
            **stats,
            "rejected": len(rejections_for_save(rejected_expansions, pending_rejected)),
            "interrupted": 1,
        }
    except RateLimitAbort as exc:
        raise SystemExit(2) from exc
    except (CardListValidationError, CardListConsistencyError) as exc:
        log_line(f"[CARD_LIST] validation error: {exc}")
        raise

    if pending_rejected:
        try:
            all_cards, empty_expansions, still_rejected, rec_stats = _run_phase2_recovery(
                rejected_list=pending_rejected,
                expansions=load_json_list(exp_list_path),
                all_cards=all_cards,
                empty_expansions=empty_expansions,
                backend=backend,
                interactive=interactive,
            )
            stats["success"] += rec_stats["success"]
            stats["empty"] += rec_stats["empty"]
            stats["rejected"] = rec_stats["rejected"]
            rejected_expansions = rejections_for_save(rejected_expansions, still_rejected)
            pending_rejected = still_rejected
            _save_card_list_artifacts(
                all_cards=all_cards,
                expansions=load_json_list(exp_list_path),
                empty_expansions=empty_expansions,
                rejected_expansions=rejected_expansions,
                card_list_path=card_out,
                expansion_list_path=exp_list_path,
                empty_path=empty_path,
                rejected_path=rejected_path,
            )
            if still_rejected:
                last_ok = int(state.get("last_completed_seq", 0))
            else:
                last_ok = max(int(e["seq"]) for e in load_json_list(exp_list_path))
                state = update_state_seq(state, last_ok, phase="done")
        except ScrapeShutdown:
            return {
                "cards": len(all_cards),
                **stats,
                "rejected": len(rejected_expansions),
                "interrupted": 1,
            }
    else:
        full_list = load_json_list(exp_list_path)
        if limit is None:
            state = update_state_seq(state, max(int(e["seq"]) for e in full_list), phase="done")

    if limit is None:
        _enforce_card_list_coverage(
            expansions=load_json_list(exp_list_path),
            all_cards=all_cards,
            empty_expansions=empty_expansions,
            rejected_expansions=rejected_expansions,
        )

    elapsed = (datetime.now() - start_time).total_seconds()
    log_line(
        f"[CARD_LIST] cards={len(all_cards)} success={stats['success']} "
        f"empty={stats['empty']} rejected={len(rejected_expansions)} elapsed={elapsed:.0f}s"
    )
    return {
        "cards": len(all_cards),
        "success": stats["success"],
        "empty": stats["empty"],
        "rejected": len(rejected_expansions),
    }
