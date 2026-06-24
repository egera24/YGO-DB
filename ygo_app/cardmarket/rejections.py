"""Merge and persist Cardmarket expansion rejection rows."""

from __future__ import annotations

from ygo_app.cardmarket.expansions import REJECTION_REASON_NOT_TCG


def merge_rejected_expansions(*sources: list[dict]) -> list[dict]:
    """Merge rejection rows by expansion_id; later sources win."""
    merged: dict[int, dict] = {}
    for source in sources:
        for row in source:
            merged[int(row["expansion_id"])] = row
    return sorted(merged.values(), key=lambda row: int(row["expansion_id"]))


def rejections_for_save(
    persisted: list[dict],
    session: list[dict],
    *,
    recovered_ids: set[int] | None = None,
) -> list[dict]:
    """Combine persisted rejections with the current session, dropping recovered ids."""
    recovered_ids = recovered_ids or set()
    prior = [
        row
        for row in persisted
        if int(row["expansion_id"]) not in recovered_ids
    ]
    return merge_rejected_expansions(prior, session)


def is_non_recoverable_rejection(row: dict) -> bool:
    """True when phase-2 recovery must not retry this rejection."""
    return row.get("rejection_reason") == REJECTION_REASON_NOT_TCG
