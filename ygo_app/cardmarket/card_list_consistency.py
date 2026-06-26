"""Seq-based gap detection for v2 card list resume."""

from __future__ import annotations

from typing import Any


class CardListConsistencyError(Exception):
    """Gap or inconsistency in expansion_seq coverage."""


def _seq_set(rows: list[dict[str, Any]], key: str = "expansion_seq") -> set[int]:
    out: set[int] = set()
    for row in rows:
        val = row.get(key)
        if val is not None:
            out.add(int(val))
    return out


def card_seqs_present(cards: list[dict[str, Any]]) -> set[int]:
    return _seq_set(cards)


def assert_no_seq_gaps(
    *,
    last_completed_seq: int,
    cards: list[dict[str, Any]],
    empty_expansions: list[dict[str, Any]],
    rejected_expansions: list[dict[str, Any]],
) -> None:
    """Raise if any seq in 1..last_completed_seq is not accounted for."""
    if last_completed_seq <= 0:
        return

    card_seqs = card_seqs_present(cards)
    empty_seqs = _seq_set(empty_expansions)
    rejected_seqs = _seq_set(rejected_expansions)
    accounted = card_seqs | empty_seqs | rejected_seqs

    gaps: list[int] = []
    for seq in range(1, last_completed_seq + 1):
        if seq not in accounted:
            gaps.append(seq)

    if gaps:
        sample = gaps[:20]
        suffix = "..." if len(gaps) > 20 else ""
        raise CardListConsistencyError(
            f"Expansion seq gap(s) in 1..{last_completed_seq}: {sample}{suffix}. "
            "Edit cardmarket_scrape_state.json last_completed_seq and re-run --resume."
        )


def expansions_for_new_ids(
    today_list: list[dict[str, Any]],
    prev_ids: set[int],
) -> list[dict[str, Any]]:
    """Expansions in today's list whose expansion_id was not in the previous run."""
    return [e for e in today_list if int(e["expansion_id"]) not in prev_ids]


def copy_cards_for_incremental(
    *,
    today_list: list[dict[str, Any]],
    prev_cards: list[dict[str, Any]],
    prev_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy cards from previous run for expansion_ids still present; update expansion_seq."""
    prev_id_to_seq = {int(e["expansion_id"]): int(e.get("seq", 0)) for e in prev_list}
    today_id_to_row = {int(e["expansion_id"]): e for e in today_list}
    copied: list[dict[str, Any]] = []

    for card in prev_cards:
        eid = int(card["expansion_id"])
        if eid not in today_id_to_row:
            continue
        if eid not in prev_id_to_seq:
            continue
        today_row = today_id_to_row[eid]
        updated = dict(card)
        updated["expansion_seq"] = int(today_row["seq"])
        updated["expansion_name"] = today_row.get("expansion_name", card.get("expansion_name"))
        if today_row.get("expansion_code"):
            updated["expansion_code"] = today_row["expansion_code"]
        copied.append(updated)

    return copied
