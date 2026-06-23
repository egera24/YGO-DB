"""Diff, merge, and validate Cardmarket catalog artifacts for incremental scrapes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ygo_app.cardmarket.artifact_io import save_json
from ygo_app.cardmarket.matching import cardmarket_match_key
from ygo_app.cardmarket.paths import CARDMARKET_INCREMENTAL_CONFLICTS_PATH


class IncrementalConflictError(ValueError):
    """Raised when merge/validation detects hard catalog conflicts."""

    def __init__(self, message: str, conflicts: list[dict[str, Any]]):
        super().__init__(message)
        self.conflicts = conflicts


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_expansion_name(name: str) -> str:
    text = (name or "").replace("&amp;", "&").strip().lower()
    return re.sub(r"\s+", " ", text)


def _expansion_by_id(rows: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in rows:
        eid = row.get("expansion_id")
        if eid is not None:
            out[int(eid)] = row
    return out


def _printing_key(card: dict[str, Any]) -> tuple[str, str] | None:
    exp_code = (card.get("expansion_code") or "").strip()
    card_number = (card.get("card_number") or "").strip()
    card_rarity = (card.get("card_rarity") or "").strip()
    if not exp_code or not card_number or not card_rarity:
        return None
    return cardmarket_match_key(exp_code, card_number, card_rarity)


def _detail_match_key(row: dict[str, Any]) -> tuple[str, str] | None:
    exp = row.get("expansion_data") or {}
    card = row.get("card_data") or {}
    exp_code = (exp.get("expansion_code") or "").strip()
    card_number = (card.get("card_number") or "").strip()
    card_rarity = (card.get("card_rarity") or "").strip()
    if not exp_code or not card_number or not card_rarity:
        return None
    return cardmarket_match_key(exp_code, card_number, card_rarity)


@dataclass
class ExpansionMigration:
    old_id: int
    new_id: int
    reason: str


@dataclass
class ExpansionPlan:
    new_ids: set[int] = field(default_factory=set)
    removed_ids: set[int] = field(default_factory=set)
    unchanged_ids: set[int] = field(default_factory=set)
    migrations: list[ExpansionMigration] = field(default_factory=list)
    orphaned_ids: set[int] = field(default_factory=set)
    ambiguous_migrations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def scrape_ids(self) -> set[int]:
        migrated_new = {m.new_id for m in self.migrations}
        return self.new_ids | migrated_new

    @property
    def purge_expansion_ids(self) -> set[int]:
        return {m.old_id for m in self.migrations}


def diff_expansions(
    stored: list[dict],
    live: list[dict],
    *,
    seed_codes: dict[int, str] | None = None,
) -> ExpansionPlan:
    """Compare stored vs live expansion lists and build a scrape plan."""
    seed_codes = seed_codes or {}
    stored_map = _expansion_by_id(stored)
    live_map = _expansion_by_id(live)

    stored_ids = set(stored_map)
    live_ids = set(live_map)

    plan = ExpansionPlan(
        new_ids=live_ids - stored_ids,
        removed_ids=stored_ids - live_ids,
        unchanged_ids=stored_ids & live_ids,
    )

    removed_pool = list(plan.removed_ids)
    new_pool = list(plan.new_ids)
    matched_removed: set[int] = set()
    matched_new: set[int] = set()

    # Match by expansion_code (stored row or seed)
    for old_id in list(removed_pool):
        if old_id in matched_removed:
            continue
        old_row = stored_map[old_id]
        old_code = (old_row.get("expansion_code") or seed_codes.get(old_id) or "").strip().upper()
        if not old_code:
            continue
        candidates = [
            nid
            for nid in new_pool
            if nid not in matched_new
            and (live_map[nid].get("expansion_code") or seed_codes.get(nid) or "").strip().upper()
            == old_code
        ]
        if len(candidates) == 1:
            new_id = candidates[0]
            plan.migrations.append(
                ExpansionMigration(old_id=old_id, new_id=new_id, reason=f"expansion_code={old_code}")
            )
            matched_removed.add(old_id)
            matched_new.add(new_id)
            plan.new_ids.discard(new_id)

    # Match by normalized expansion_name
    for old_id in list(removed_pool):
        if old_id in matched_removed:
            continue
        old_name = normalize_expansion_name(stored_map[old_id].get("expansion_name", ""))
        if not old_name:
            continue
        candidates = [
            nid
            for nid in new_pool
            if nid not in matched_new
            and normalize_expansion_name(live_map[nid].get("expansion_name", "")) == old_name
        ]
        if len(candidates) == 1:
            new_id = candidates[0]
            plan.migrations.append(
                ExpansionMigration(
                    old_id=old_id,
                    new_id=new_id,
                    reason=f"expansion_name={old_name!r}",
                )
            )
            matched_removed.add(old_id)
            matched_new.add(new_id)
            plan.new_ids.discard(new_id)
        elif len(candidates) > 1:
            plan.ambiguous_migrations.append(
                {
                    "type": "ambiguous_migration",
                    "old_id": old_id,
                    "candidate_new_ids": candidates,
                    "reason": "multiple new expansions share normalized name",
                }
            )

    # Ambiguous code matches (multiple new for one removed)
    for old_id in removed_pool:
        if old_id in matched_removed:
            continue
        old_row = stored_map[old_id]
        old_code = (old_row.get("expansion_code") or seed_codes.get(old_id) or "").strip().upper()
        if not old_code:
            continue
        candidates = [
            nid
            for nid in new_pool
            if nid not in matched_new
            and (live_map[nid].get("expansion_code") or seed_codes.get(nid) or "").strip().upper()
            == old_code
        ]
        if len(candidates) > 1:
            plan.ambiguous_migrations.append(
                {
                    "type": "ambiguous_migration",
                    "old_id": old_id,
                    "candidate_new_ids": candidates,
                    "reason": "multiple new expansions share expansion_code",
                }
            )

    plan.orphaned_ids = plan.removed_ids - {m.old_id for m in plan.migrations}
    return plan


def merge_expansion_lists(stored: list[dict], live: list[dict]) -> list[dict]:
    """Upsert live rows into stored list by expansion_id."""
    merged_map = _expansion_by_id(stored)
    for row in live:
        eid = int(row["expansion_id"])
        existing = merged_map.get(eid)
        if existing is None:
            merged_map[eid] = dict(row)
            continue
        updated = dict(existing)
        updated["expansion_name"] = row.get("expansion_name", updated.get("expansion_name"))
        if row.get("expansion_code"):
            updated["expansion_code"] = row["expansion_code"]
        merged_map[eid] = updated
    return sorted(merged_map.values(), key=lambda r: int(r["expansion_id"]))


def merge_card_lists(
    existing: list[dict],
    incoming: list[dict],
    *,
    purge_expansion_ids: set[int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Merge scraped cards into existing list.

    Returns (merged_cards, conflicts). Non-empty conflicts should abort the run.
    """
    purge = purge_expansion_ids or set()
    conflicts: list[dict[str, Any]] = []

    kept = [c for c in existing if int(c.get("expansion_id", -1)) not in purge]
    by_card_id: dict[int, dict] = {}
    by_printing_key: dict[tuple[str, str], int] = {}

    for card in kept:
        cid = int(card["card_id"])
        by_card_id[cid] = card
        pkey = _printing_key(card)
        if pkey is not None:
            by_printing_key[pkey] = cid

    for card in incoming:
        cid = int(card["card_id"])
        exp_id = int(card.get("expansion_id", -1))
        pkey = _printing_key(card)

        if cid in by_card_id:
            old = by_card_id[cid]
            old_exp = int(old.get("expansion_id", -1))
            if old_exp != exp_id:
                conflicts.append(
                    {
                        "type": "duplicate_card_id",
                        "card_id": cid,
                        "existing_expansion_id": old_exp,
                        "incoming_expansion_id": exp_id,
                    }
                )
            continue

        if pkey is not None and pkey in by_printing_key:
            existing_cid = by_printing_key[pkey]
            if existing_cid != cid:
                conflicts.append(
                    {
                        "type": "duplicate_printing_key",
                        "printing_key": list(pkey),
                        "existing_card_id": existing_cid,
                        "incoming_card_id": cid,
                    }
                )
                continue

        by_card_id[cid] = card
        if pkey is not None:
            by_printing_key[pkey] = cid

    if conflicts:
        return kept, conflicts

    merged = sorted(by_card_id.values(), key=lambda c: (int(c.get("expansion_id", 0)), int(c["card_id"])))
    return merged, []


def merge_card_details(
    existing: list[dict],
    incoming: list[dict],
    *,
    purge_card_ids: set[int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Merge detail rows by card_id; reject duplicate Yugipedia match keys."""
    purge = purge_card_ids or set()
    conflicts: list[dict[str, Any]] = []

    by_card_id: dict[int, dict] = {}
    by_match_key: dict[tuple[str, str], int] = {}

    for row in existing:
        card = row.get("card_data") or {}
        cid = card.get("card_id")
        if cid is None:
            continue
        cid_int = int(cid)
        if cid_int in purge:
            continue
        by_card_id[cid_int] = row
        mkey = _detail_match_key(row)
        if mkey is not None:
            by_match_key[mkey] = cid_int

    for row in incoming:
        card = row.get("card_data") or {}
        cid = card.get("card_id")
        if cid is None:
            continue
        cid_int = int(cid)
        mkey = _detail_match_key(row)

        if mkey is not None and mkey in by_match_key:
            existing_cid = by_match_key[mkey]
            if existing_cid != cid_int:
                conflicts.append(
                    {
                        "type": "duplicate_match_key",
                        "match_key": list(mkey),
                        "existing_card_id": existing_cid,
                        "incoming_card_id": cid_int,
                    }
                )
                continue

        by_card_id[cid_int] = row
        if mkey is not None:
            by_match_key[mkey] = cid_int

    if conflicts:
        return list(by_card_id.values()), conflicts

    merged = sorted(by_card_id.values(), key=lambda r: int((r.get("card_data") or {}).get("card_id", 0)))
    return merged, []


def find_duplicate_card_ids(cards: list[dict]) -> list[int]:
    seen: set[int] = set()
    duplicates: list[int] = []
    for card in cards:
        cid = card.get("card_id")
        if cid is None:
            continue
        cid_int = int(cid)
        if cid_int in seen and cid_int not in duplicates:
            duplicates.append(cid_int)
        seen.add(cid_int)
    return duplicates


def find_duplicate_printing_keys(cards: list[dict]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[int]] = {}
    for card in cards:
        pkey = _printing_key(card)
        if pkey is None:
            continue
        by_key.setdefault(pkey, []).append(int(card["card_id"]))
    conflicts: list[dict[str, Any]] = []
    for pkey, cids in by_key.items():
        if len(set(cids)) > 1:
            conflicts.append(
                {
                    "type": "duplicate_printing_key",
                    "printing_key": list(pkey),
                    "card_ids": sorted(set(cids)),
                }
            )
    return conflicts


def find_duplicate_match_keys(details: list[dict]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[int]] = {}
    for row in details:
        mkey = _detail_match_key(row)
        if mkey is None:
            continue
        cid = int((row.get("card_data") or {}).get("card_id", 0))
        by_key.setdefault(mkey, []).append(cid)
    conflicts: list[dict[str, Any]] = []
    for mkey, cids in by_key.items():
        if len(set(cids)) > 1:
            conflicts.append(
                {
                    "type": "duplicate_match_key",
                    "match_key": list(mkey),
                    "card_ids": sorted(set(cids)),
                }
            )
    return conflicts


def validate_catalog_integrity(
    *,
    cards: list[dict],
    details: list[dict],
    plan: ExpansionPlan | None = None,
) -> list[dict[str, Any]]:
    """Return all hard conflicts; empty list means valid."""
    conflicts: list[dict[str, Any]] = []

    if plan and plan.ambiguous_migrations:
        conflicts.extend(plan.ambiguous_migrations)

    dup_ids = find_duplicate_card_ids(cards)
    for cid in dup_ids:
        conflicts.append({"type": "duplicate_card_id", "card_id": cid})

    conflicts.extend(find_duplicate_printing_keys(cards))
    conflicts.extend(find_duplicate_match_keys(details))

    return conflicts


def card_ids_for_expansion_ids(cards: list[dict], expansion_ids: set[int]) -> set[int]:
    return {int(c["card_id"]) for c in cards if int(c.get("expansion_id", -1)) in expansion_ids}


def write_conflicts(path: Path, conflicts: list[dict[str, Any]]) -> None:
    payload = {"generated_at": _utc_now_iso(), "conflicts": conflicts}
    save_json(path, payload)


def raise_on_conflicts(conflicts: list[dict[str, Any]], *, path: Path | None = None) -> None:
    if not conflicts:
        return
    out = path or CARDMARKET_INCREMENTAL_CONFLICTS_PATH
    write_conflicts(out, conflicts)
    raise IncrementalConflictError(
        f"Catalog integrity check failed ({len(conflicts)} conflict(s)); see {out}",
        conflicts,
    )


def prepare_incremental_plan(
    stored_expansions: list[dict],
    live_expansions: list[dict],
    *,
    seed_codes: dict[int, str] | None = None,
) -> ExpansionPlan:
    """Build expansion plan and fail on ambiguous migrations."""
    plan = diff_expansions(stored_expansions, live_expansions, seed_codes=seed_codes)
    if plan.ambiguous_migrations:
        raise_on_conflicts(plan.ambiguous_migrations)
    return plan
