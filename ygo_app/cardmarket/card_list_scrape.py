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
    clear_checkpoint,
    load_checkpoint,
    load_json_list,
    save_checkpoint,
    save_json,
)
from ygo_app.cardmarket.checkpoints import (
    build_card_list_checkpoint_at_idx,
    build_card_list_recovery_checkpoint_at_idx,
    resolve_card_list_recovery_start,
    resolve_card_list_resume_index,
)
from ygo_app.cardmarket.constants import (
    DISCOVERY_MAX_RETRIES,
    DISCOVERY_REQUESTS_PER_SECOND,
    FetchBackend,
    INTER_EXPANSION_DELAY_BROWSER,
    RANDOM_JITTER,
    RECOVERY_REQUESTS_PER_SECOND,
)
from ygo_app.cardmarket.expansion_seed import regenerate_expansion_seed
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
    CARDMARKET_CARD_LIST_CHECKPOINT_PATH,
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_CARD_LIST_RECOVERY_CHECKPOINT_PATH,
    CARDMARKET_EMPTY_EXPANSIONS_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
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
CHECKPOINT_EVERY = 5

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
) -> None:
    with _file_lock:
        save_json(card_list_path, all_cards)
        save_json(expansion_list_path, expansions)
        if empty_expansions:
            save_json(empty_path, empty_expansions)
        if rejected_expansions:
            save_json(rejected_path, rejected_expansions)


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
            log_line(
                f"[CARD_LIST] expansion {expansion.get('expansion_id')} "
                f"({completed}/{len(expansions)}): {result['status']}"
                f"{f', {result['total_count']} cards' if result['total_count'] else ''}"
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
    input_path: Path = CARDMARKET_EXPANSION_LIST_PATH,
    output_path: Path = CARDMARKET_CARD_LIST_PATH,
    expansion_list_path: Path = CARDMARKET_EXPANSION_LIST_PATH,
    empty_path: Path = CARDMARKET_EMPTY_EXPANSIONS_PATH,
    rejected_path: Path = CARDMARKET_REJECTED_EXPANSIONS_PATH,
    checkpoint_path: Path = CARDMARKET_CARD_LIST_CHECKPOINT_PATH,
    recovery_checkpoint_path: Path = CARDMARKET_CARD_LIST_RECOVERY_CHECKPOINT_PATH,
    session: ScrapeSession,
    resume: bool = False,
    limit: int | None = None,
    update_seed: bool = True,
    expansion_filter: set[int] | None = None,
    purge_expansion_ids: set[int] | None = None,
) -> dict[str, int]:
    backend = session.backend
    expansions = load_json_list(input_path)

    resume_expansion_id: int | None = None
    resume_checkpoint: dict[str, Any] | None = None
    if resume and checkpoint_path.is_file() and expansion_filter is None:
        resume_checkpoint = load_checkpoint(checkpoint_path)
        old_idx = resume_checkpoint.get("last_expansion_idx", -1)
        if 0 <= old_idx < len(expansions):
            resume_expansion_id = int(expansions[old_idx]["expansion_id"])
        elif resume_checkpoint.get("last_expansion_id") is not None:
            resume_expansion_id = int(resume_checkpoint["last_expansion_id"])

    empty_for_purge = load_json_list(empty_path) if empty_path.is_file() else []
    expansions, _, _ = _purge_non_tcg_expansions(
        expansions,
        expansion_list_path=expansion_list_path,
        rejected_path=rejected_path,
        empty_path=empty_path,
        empty_expansions=empty_for_purge,
    )

    if expansion_filter is not None:
        expansions = [e for e in expansions if int(e["expansion_id"]) in expansion_filter]
        if not expansions:
            log_line("[CARD_LIST] nothing to do (expansion filter empty)")
            return {"cards": 0, "empty": 0, "rejected": 0}

        existing_cards = load_json_list(output_path) if output_path.is_file() else []
        scrape_result = scrape_expansions(expansions, session=session)
        if scrape_result.get("interrupted"):
            log_line("[CARD_LIST] incremental run interrupted — no merge")
            return {
                "cards": len(existing_cards),
                "success": scrape_result.get("success", 0),
                "empty": scrape_result.get("empty", 0),
                "rejected": scrape_result.get("rejected", 0),
                "interrupted": 1,
            }

        from ygo_app.cardmarket.incremental import merge_card_lists, raise_on_conflicts

        merged_cards, conflicts = merge_card_lists(
            existing_cards,
            scrape_result["cards"],
            purge_expansion_ids=purge_expansion_ids,
        )
        raise_on_conflicts(conflicts)

        all_expansions = load_json_list(expansion_list_path)
        exp_by_id = {int(e["expansion_id"]): e for e in all_expansions}
        for exp in expansions:
            eid = int(exp["expansion_id"])
            if eid in exp_by_id:
                exp_by_id[eid].update(
                    {
                        k: v
                        for k, v in exp.items()
                        if k in ("total_number_of_cards", "expansion_code") and v
                    }
                )
            else:
                exp_by_id[eid] = exp
        merged_expansion_list = sorted(exp_by_id.values(), key=lambda e: int(e["expansion_id"]))

        empty_expansions = (
            load_json_list(empty_path) if empty_path.is_file() else []
        )
        empty_expansions.extend(scrape_result["empty_expansions"])

        prior_rejections = (
            load_json_list(rejected_path) if rejected_path.is_file() else []
        )
        scraped_ids = {int(e["expansion_id"]) for e in expansions}
        still_rejected_ids = {
            int(r["expansion_id"]) for r in scrape_result["rejected_expansions"]
        }
        recovered_ids = scraped_ids - still_rejected_ids
        prior_rejections = [
            r
            for r in prior_rejections
            if int(r["expansion_id"]) not in recovered_ids
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
            card_list_path=output_path,
            expansion_list_path=expansion_list_path,
            empty_path=empty_path,
            rejected_path=rejected_path,
        )
        if update_seed:
            seed_path = regenerate_expansion_seed(expansion_list_path)
            log_line(f"[EXPANSIONS] regenerated seed at {seed_path}")
        return {
            "cards": len(merged_cards),
            "success": scrape_result["success"],
            "empty": scrape_result["empty"],
            "rejected": scrape_result["rejected"],
        }

    start_idx = 0
    all_cards: list[dict] = []
    empty_expansions: list[dict] = []
    rejected_expansions: list[dict] = []

    if resume and (resume_expansion_id is not None or checkpoint_path.is_file()):
        if output_path.is_file():
            all_cards = load_json_list(output_path)
        if empty_path.is_file():
            empty_expansions = load_json_list(empty_path)
        if rejected_path.is_file():
            rejected_expansions = load_json_list(rejected_path)
        if resume_expansion_id is not None:
            start_idx = resolve_card_list_resume_index(
                resume_checkpoint or {"last_expansion_id": resume_expansion_id},
                expansions,
            )
        elif resume_checkpoint is not None:
            start_idx = resolve_card_list_resume_index(resume_checkpoint, expansions)
        else:
            checkpoint = load_checkpoint(checkpoint_path)
            start_idx = resolve_card_list_resume_index(checkpoint, expansions)
        log_line(f"[CARD_LIST] resuming from expansion index {start_idx}")

    if limit is not None:
        expansions = expansions[:limit]

    remaining = expansions[start_idx:]
    if not remaining:
        log_line("[CARD_LIST] nothing to do")
        return {"cards": len(all_cards), "empty": len(empty_expansions), "rejected": 0}

    # Phase 1: fast parallel
    workers = session.workers
    interactive = session.interactive
    discovery_rps = session.discovery_rps or DISCOVERY_REQUESTS_PER_SECOND
    rate_limiter = AdaptiveRateLimiter(discovery_rps)
    session_pool = create_session_pool(backend, workers)

    stats = {"success": 0, "empty": 0, "rejected": 0}
    rejected_list: list[dict] = []
    completed = 0
    start_time = datetime.now()

    log_line(f"[CARD_LIST] phase1 workers={workers} rps={discovery_rps} expansions={len(remaining)}")

    clear_scrape_shutdown()
    interrupted = False
    last_checkpoint_idx = start_idx - 1
    executor = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures: dict = {}
        for idx, expansion in enumerate(remaining):
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
            futures[future] = (start_idx + idx, expansion)

        for future in as_completed(futures):
            abs_idx, expansion = futures[future]
            try:
                result = future.result()
            except RateLimitAbort as exc:
                _save_card_list_artifacts(
                    all_cards=all_cards,
                    expansions=expansions,
                    empty_expansions=empty_expansions,
                    rejected_expansions=rejections_for_save(
                        rejected_expansions, rejected_list
                    ),
                    card_list_path=output_path,
                    expansion_list_path=expansion_list_path,
                    empty_path=empty_path,
                    rejected_path=rejected_path,
                )
                save_checkpoint(
                    checkpoint_path,
                    build_card_list_checkpoint_at_idx(expansions, abs_idx - 1),
                )
                raise SystemExit(2) from exc
            except ScrapeShutdown:
                interrupted = True
                request_scrape_shutdown()
                for f in futures:
                    f.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                _save_card_list_artifacts(
                    all_cards=all_cards,
                    expansions=expansions,
                    empty_expansions=empty_expansions,
                    rejected_expansions=rejections_for_save(
                        rejected_expansions, rejected_list
                    ),
                    card_list_path=output_path,
                    expansion_list_path=expansion_list_path,
                    empty_path=empty_path,
                    rejected_path=rejected_path,
                )
                save_checkpoint(
                    checkpoint_path,
                    build_card_list_checkpoint_at_idx(expansions, last_checkpoint_idx),
                )
                log_line("[CARD_LIST] terminated by user — progress saved")
                break

            expansion["total_number_of_cards"] = result["total_count"]
            if result.get("expansion_code"):
                expansion["expansion_code"] = result["expansion_code"]

            all_cards.extend(result["cards"])

            if result["status"] == "empty":
                empty_expansions.append(dict(expansion))
                stats["empty"] += 1
            elif result["status"] == "rejected":
                rejected_list.append(_rejection_row_from_worker(expansion, result))
                stats["rejected"] += 1
            else:
                stats["success"] += 1

            completed += 1
            last_checkpoint_idx = abs_idx
            first_issue = ""
            if result["status"] == "rejected":
                if result.get("rejection_reason"):
                    first_issue = f" — {result['rejection_reason']}"
                elif result["attempts"]:
                    issues = result["attempts"][-1].get("issues") or []
                    if issues:
                        first_issue = f" — {issues[0][:100]}"
            log_line(
                f"[CARD_LIST] expansion {expansion.get('expansion_id')} "
                f"({completed}/{len(remaining)}): {result['status']}"
                f"{f', {result['total_count']} cards' if result['total_count'] else ''}"
                f"{first_issue if result['status'] == 'rejected' else ''}"
            )
            if completed % CHECKPOINT_EVERY == 0:
                _save_card_list_artifacts(
                    all_cards=all_cards,
                    expansions=expansions,
                    empty_expansions=empty_expansions,
                    rejected_expansions=rejections_for_save(
                        rejected_expansions, rejected_list
                    ),
                    card_list_path=output_path,
                    expansion_list_path=expansion_list_path,
                    empty_path=empty_path,
                    rejected_path=rejected_path,
                )
                save_checkpoint(
                    checkpoint_path,
                    build_card_list_checkpoint_at_idx(expansions, abs_idx),
                )

            if backend == "playwright":
                time.sleep(random.uniform(*INTER_EXPANSION_DELAY_BROWSER))

    except KeyboardInterrupt:
        interrupted = True
        request_scrape_shutdown()
        for f in futures:
            f.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        _save_card_list_artifacts(
            all_cards=all_cards,
            expansions=expansions,
            empty_expansions=empty_expansions,
            rejected_expansions=rejections_for_save(
                rejected_expansions, rejected_list
            ),
            card_list_path=output_path,
            expansion_list_path=expansion_list_path,
            empty_path=empty_path,
            rejected_path=rejected_path,
        )
        save_checkpoint(
            checkpoint_path,
            build_card_list_checkpoint_at_idx(expansions, last_checkpoint_idx),
        )
        log_line("[CARD_LIST] interrupted — progress saved")
    finally:
        if not interrupted:
            executor.shutdown(wait=True)

    if interrupted:
        return {
            "cards": len(all_cards),
            "success": stats["success"],
            "empty": stats["empty"],
            "rejected": len(
                rejections_for_save(rejected_expansions, rejected_list)
            ),
            "interrupted": 1,
        }

    clear_checkpoint(checkpoint_path)

    # Phase 2: recovery for rejected
    if rejected_list:
        log_line(f"[CARD_LIST] phase2 recovery for {len(rejected_list)} rejected expansions")
        recovery_rps = RECOVERY_REQUESTS_PER_SECOND
        recovery_limiter = AdaptiveRateLimiter(recovery_rps)
        recovery_start = 0
        if resume and recovery_checkpoint_path.is_file():
            recovery_cp = load_checkpoint(recovery_checkpoint_path)
            recovery_start = resolve_card_list_recovery_start(recovery_cp, rejected_list)
            log_line(f"[CARD_LIST] recovery resume from rejection #{recovery_start + 1}")

        still_rejected: list[dict] = []
        recovered_ids: set[int] = set()
        for idx, rejected_exp in enumerate(rejected_list[recovery_start:], start=recovery_start):
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
                _save_card_list_artifacts(
                    all_cards=all_cards,
                    expansions=expansions,
                    empty_expansions=empty_expansions,
                    rejected_expansions=rejections_for_save(
                        rejected_expansions,
                        still_rejected,
                        recovered_ids=recovered_ids,
                    ),
                    card_list_path=output_path,
                    expansion_list_path=expansion_list_path,
                    empty_path=empty_path,
                    rejected_path=rejected_path,
                )
                save_checkpoint(
                    recovery_checkpoint_path,
                    build_card_list_recovery_checkpoint_at_idx(rejected_list, idx - 1),
                )
                log_line("[CARD_LIST] terminated by user — progress saved")
                return {
                    "cards": len(all_cards),
                    "success": stats["success"],
                    "empty": stats["empty"],
                    "rejected": len(
                        rejections_for_save(
                            rejected_expansions,
                            still_rejected,
                            recovered_ids=recovered_ids,
                        )
                    ),
                    "interrupted": 1,
                }

            if result["status"] == "success":
                all_cards.extend(result["cards"])
                for exp in expansions:
                    if exp["expansion_id"] == expansion["expansion_id"]:
                        exp["total_number_of_cards"] = result["total_count"]
                        if result.get("expansion_code"):
                            exp["expansion_code"] = result["expansion_code"]
                        break
                stats["success"] += 1
                stats["rejected"] -= 1
                recovered_ids.add(int(expansion["expansion_id"]))
            elif result["status"] == "empty":
                empty_expansions.append(expansion)
                stats["empty"] += 1
                stats["rejected"] -= 1
                recovered_ids.add(int(expansion["expansion_id"]))
            else:
                still_rejected.append(rejected_exp)

            if (idx + 1) % 10 == 0:
                _save_card_list_artifacts(
                    all_cards=all_cards,
                    expansions=expansions,
                    empty_expansions=empty_expansions,
                    rejected_expansions=rejections_for_save(
                        rejected_expansions,
                        still_rejected,
                        recovered_ids=recovered_ids,
                    ),
                    card_list_path=output_path,
                    expansion_list_path=expansion_list_path,
                    empty_path=empty_path,
                    rejected_path=rejected_path,
                )
                save_checkpoint(
                    recovery_checkpoint_path,
                    build_card_list_recovery_checkpoint_at_idx(rejected_list, idx),
                )

        rejected_expansions = rejections_for_save(
            rejected_expansions,
            still_rejected,
            recovered_ids=recovered_ids,
        )
        clear_checkpoint(recovery_checkpoint_path)

    _save_card_list_artifacts(
        all_cards=all_cards,
        expansions=expansions,
        empty_expansions=empty_expansions,
        rejected_expansions=rejected_expansions,
        card_list_path=output_path,
        expansion_list_path=expansion_list_path,
        empty_path=empty_path,
        rejected_path=rejected_path,
    )

    if update_seed:
        seed_path = regenerate_expansion_seed(expansion_list_path)
        log_line(f"[EXPANSIONS] regenerated seed at {seed_path}")

    elapsed = (datetime.now() - start_time).total_seconds()
    log_line(
        f"[CARD_LIST] cards={len(all_cards)} success={stats['success']} "
        f"empty={stats['empty']} rejected={len(rejected_expansions)} "
        f"elapsed={elapsed:.0f}s"
    )
    return {
        "cards": len(all_cards),
        "success": stats["success"],
        "empty": stats["empty"],
        "rejected": len(rejected_expansions),
    }
