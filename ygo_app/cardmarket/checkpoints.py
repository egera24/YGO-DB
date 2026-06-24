"""Human-readable Cardmarket scrape checkpoint builders and resolvers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expansion_summary(expansion: dict[str, Any]) -> dict[str, Any]:
    return {
        "expansion_id": int(expansion["expansion_id"]),
        "expansion_name": expansion.get("expansion_name", ""),
        "expansion_code": (expansion.get("expansion_code") or "").strip() or None,
    }


def _card_summary(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": int(card["card_id"]),
        "card_name": card.get("card_name", ""),
        "expansion_id": int(card.get("expansion_id", 0)),
        "expansion_name": card.get("expansion_name", ""),
        "expansion_code": (card.get("expansion_code") or "").strip() or None,
    }


def build_card_list_recovery_checkpoint_at_idx(
    rejected_list: list[dict[str, Any]],
    idx: int,
) -> dict[str, Any]:
    """Build job 2 recovery checkpoint from a completed-through index (idx may be -1)."""
    if idx < 0:
        return {"last_processed": -1, "saved_at": _utc_now_iso()}
    return build_card_list_recovery_checkpoint(
        rejection=rejected_list[idx],
        idx=idx,
        total=len(rejected_list),
    )


def build_card_list_checkpoint_at_idx(
    expansions: list[dict[str, Any]],
    idx: int,
) -> dict[str, Any]:
    """Build job 2 checkpoint from a completed-through index (idx may be -1)."""
    if idx < 0:
        return {"last_expansion_idx": -1, "saved_at": _utc_now_iso()}
    return build_card_list_checkpoint(
        expansion=expansions[idx],
        idx=idx,
        total=len(expansions),
        expansions=expansions,
    )


def build_card_details_checkpoint_at_idx(
    cards: list[dict[str, Any]],
    idx: int,
    *,
    phase1_complete: bool,
) -> dict[str, Any]:
    """Build job 3 checkpoint from a completed-through index (idx may be -1)."""
    if idx < 0:
        return {
            "last_processed_index": -1,
            "phase1_complete": phase1_complete,
            "saved_at": _utc_now_iso(),
        }
    return build_card_details_checkpoint(
        card=cards[idx],
        idx=idx,
        total=len(cards),
        phase1_complete=phase1_complete,
        cards=cards,
    )


def build_card_list_checkpoint(
    *,
    expansion: dict[str, Any],
    idx: int,
    total: int,
    expansions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build job 2 phase-1 checkpoint (keeps legacy last_expansion_idx)."""
    summary = _expansion_summary(expansion)
    remaining = max(0, total - idx - 1)
    payload: dict[str, Any] = {
        "last_expansion_idx": idx,
        "last_expansion_id": summary["expansion_id"],
        "last_expansion_name": summary["expansion_name"],
        "saved_at": _utc_now_iso(),
        "progress": {
            "completed_through_idx": idx,
            "total_expansions": total,
            "remaining": remaining,
        },
    }
    if summary["expansion_code"]:
        payload["last_expansion_code"] = summary["expansion_code"]

    if expansions is not None and idx + 1 < len(expansions):
        nxt = expansions[idx + 1]
        next_summary = _expansion_summary(nxt)
        payload["next_expansion"] = {
            "idx": idx + 1,
            **next_summary,
        }
        if not payload["next_expansion"].get("expansion_code"):
            payload["next_expansion"].pop("expansion_code", None)

    return payload


def build_card_list_recovery_checkpoint(
    *,
    rejection: dict[str, Any],
    idx: int,
    total: int,
) -> dict[str, Any]:
    """Build job 2 phase-2 recovery checkpoint (keeps legacy last_processed)."""
    eid = int(rejection["expansion_id"])
    return {
        "last_processed": idx,
        "last_expansion_id": eid,
        "last_expansion_name": rejection.get("expansion_name", ""),
        "saved_at": _utc_now_iso(),
        "progress": {
            "completed_through_idx": idx,
            "total_rejections": total,
            "remaining": max(0, total - idx - 1),
        },
    }


def build_card_details_checkpoint(
    *,
    card: dict[str, Any],
    idx: int,
    total: int,
    phase1_complete: bool,
    cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build job 3 phase-1 checkpoint (keeps legacy last_processed_index)."""
    summary = _card_summary(card)
    remaining = max(0, total - idx - 1)
    payload: dict[str, Any] = {
        "last_processed_index": idx,
        "last_card_id": summary["card_id"],
        "last_card_name": summary["card_name"],
        "last_expansion_id": summary["expansion_id"],
        "last_expansion_name": summary["expansion_name"],
        "phase1_complete": phase1_complete,
        "saved_at": _utc_now_iso(),
        "progress": {
            "completed_through_idx": idx,
            "total_cards": total,
            "remaining": remaining,
        },
    }
    if summary["expansion_code"]:
        payload["last_expansion_code"] = summary["expansion_code"]

    if cards is not None and idx + 1 < len(cards):
        nxt = cards[idx + 1]
        next_summary = _card_summary(nxt)
        payload["next_card"] = {
            "idx": idx + 1,
            **next_summary,
        }
        if not payload["next_card"].get("expansion_code"):
            payload["next_card"].pop("expansion_code", None)

    return payload


def resolve_card_list_resume_index(
    checkpoint: dict[str, Any],
    expansions: list[dict[str, Any]],
) -> int:
    """Return start index for job 2 resume (index of next expansion to scrape)."""
    resume_id = checkpoint.get("last_expansion_id")
    if resume_id is not None:
        for i, expansion in enumerate(expansions):
            if int(expansion["expansion_id"]) == int(resume_id):
                return i + 1

    old_idx = checkpoint.get("last_expansion_idx", -1)
    if isinstance(old_idx, int) and 0 <= old_idx < len(expansions):
        return old_idx + 1

    return 0


def resolve_card_list_recovery_start(
    checkpoint: dict[str, Any],
    rejected_list: list[dict[str, Any]],
) -> int:
    """Return start index for job 2 phase-2 recovery."""
    resume_id = checkpoint.get("last_expansion_id")
    if resume_id is not None:
        for i, rejection in enumerate(rejected_list):
            if int(rejection["expansion_id"]) == int(resume_id):
                return i + 1

    last_processed = checkpoint.get("last_processed", -1)
    if isinstance(last_processed, int) and last_processed >= 0:
        return last_processed + 1

    return 0


def resolve_card_details_resume_index(
    checkpoint: dict[str, Any],
    cards: list[dict[str, Any]],
) -> int:
    """Return start index for job 3 resume (index of next card to scrape)."""
    resume_id = checkpoint.get("last_card_id")
    if resume_id is not None:
        for i, card in enumerate(cards):
            if int(card["card_id"]) == int(resume_id):
                return i + 1

    last_idx = checkpoint.get("last_processed_index", -1)
    if isinstance(last_idx, int) and last_idx >= 0:
        return last_idx + 1

    return 0


def resolve_card_list_checkpoint(
    checkpoint: dict[str, Any],
    expansions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve job 2 checkpoint to last completed expansion and optional next."""
    if not checkpoint:
        return None

    idx = checkpoint.get("last_expansion_idx")
    expansion: dict[str, Any] | None = None

    resume_id = checkpoint.get("last_expansion_id")
    if resume_id is not None:
        for i, row in enumerate(expansions):
            if int(row["expansion_id"]) == int(resume_id):
                expansion = row
                idx = i
                break

    if expansion is None and isinstance(idx, int) and 0 <= idx < len(expansions):
        expansion = expansions[idx]

    if expansion is None:
        return None

    result: dict[str, Any] = {
        "idx": idx,
        "expansion": dict(expansion),
        "saved_at": checkpoint.get("saved_at"),
        "progress": checkpoint.get("progress"),
    }

    next_idx = (idx if isinstance(idx, int) else -1) + 1
    if 0 <= next_idx < len(expansions):
        result["next"] = {"idx": next_idx, "expansion": expansions[next_idx]}

    return result


def audit_processed_expansions(
    expansions: list[dict[str, Any]],
    *,
    through_idx: int,
    card_list_expansion_ids: set[int],
    empty_ids: set[int],
    rejected_ids: set[int],
) -> dict[str, list[Any]]:
    """Classify expansions at indices 0..through_idx by scrape outcome."""
    cats: dict[str, list[Any]] = {
        "has_cards": [],
        "empty": [],
        "rejected": [],
        "unaccounted": [],
    }
    for i in range(through_idx + 1):
        if i >= len(expansions):
            break
        row = expansions[i]
        eid = int(row["expansion_id"])
        if eid in card_list_expansion_ids:
            cats["has_cards"].append(i)
        elif eid in empty_ids:
            cats["empty"].append(i)
        elif eid in rejected_ids:
            cats["rejected"].append(i)
        else:
            cats["unaccounted"].append(
                (i, eid, row.get("expansion_name", ""), row.get("total_number_of_cards"))
            )
    return cats


def format_catalog_status_report(
    *,
    expansion_list: list[dict[str, Any]] | None,
    card_list: list[dict[str, Any]] | None,
    empty_expansions: list[dict[str, Any]] | None,
    rejected_expansions: list[dict[str, Any]] | None,
    card_list_checkpoint: dict[str, Any] | None,
    recovery_checkpoint: dict[str, Any] | None,
    card_details: list[dict[str, Any]] | None,
    card_details_rejections: list[dict[str, Any]] | None,
    card_details_checkpoint: dict[str, Any] | None,
) -> str:
    """Format a human-readable Cardmarket pipeline status report."""
    lines: list[str] = []

    lines.append("=== Cardmarket catalog status ===")
    lines.append("")

    # Job 1
    lines.append("--- Job 1: expansion list ---")
    if expansion_list is None:
        lines.append("  cardmarket_expansion_list.json: MISSING")
    else:
        lines.append(f"  expansions: {len(expansion_list)}")
    lines.append("")

    # Job 2 phase 1
    lines.append("--- Job 2: card list (phase 1) ---")
    if card_list is None:
        lines.append("  cardmarket_card_list.json: MISSING")
    else:
        exp_ids_in_cards = {int(c["expansion_id"]) for c in card_list}
        lines.append(
            f"  cards: {len(card_list)}, expansions with cards: {len(exp_ids_in_cards)}"
        )

    empty_ids: set[int] = set()
    rejected_ids: set[int] = set()
    if empty_expansions is not None:
        empty_ids = {int(e["expansion_id"]) for e in empty_expansions}
        lines.append(f"  empty expansions: {len(empty_ids)}")
    else:
        lines.append("  cardmarket_empty_expansions.json: MISSING")

    if rejected_expansions is not None:
        rejected_ids = {int(e["expansion_id"]) for e in rejected_expansions}
        lines.append(f"  rejected expansions: {len(rejected_ids)}")
    else:
        lines.append("  cardmarket_rejected_expansions.json: MISSING")

    if card_list_checkpoint and expansion_list:
        resolved = resolve_card_list_checkpoint(card_list_checkpoint, expansion_list)
        if resolved:
            exp = resolved["expansion"]
            idx = resolved["idx"]
            lines.append(
                f"  checkpoint: idx={idx} id={exp['expansion_id']} "
                f"name={exp.get('expansion_name', '')!r}"
            )
            code = exp.get("expansion_code")
            if code:
                lines.append(f"    code: {code}")
            if resolved.get("saved_at"):
                lines.append(f"    saved_at: {resolved['saved_at']}")
            progress = resolved.get("progress")
            if isinstance(progress, dict):
                lines.append(
                    f"    progress: {progress.get('completed_through_idx', idx) + 1}/"
                    f"{progress.get('total_expansions', len(expansion_list))}"
                )
            nxt = resolved.get("next")
            if nxt:
                ne = nxt["expansion"]
                lines.append(
                    f"  next pending: idx={nxt['idx']} id={ne['expansion_id']} "
                    f"name={ne.get('expansion_name', '')!r}"
                )
            cats = audit_processed_expansions(
                expansion_list,
                through_idx=idx,
                card_list_expansion_ids=exp_ids_in_cards if card_list else set(),
                empty_ids=empty_ids,
                rejected_ids=rejected_ids,
            )
            lines.append(
                f"  processed 0..{idx}: has_cards={len(cats['has_cards'])} "
                f"empty={len(cats['empty'])} rejected={len(cats['rejected'])} "
                f"unaccounted={len(cats['unaccounted'])}"
            )
            if cats["unaccounted"]:
                lines.append("  unaccounted (first 10):")
                for row in cats["unaccounted"][:10]:
                    lines.append(
                        f"    idx={row[0]} id={row[1]} total={row[3]} name={row[2]!r}"
                    )
                if len(cats["unaccounted"]) > 10:
                    lines.append(f"    ... and {len(cats['unaccounted']) - 10} more")
        else:
            lines.append("  checkpoint: present but could not resolve against expansion list")
    elif card_list_checkpoint:
        lines.append(
            f"  checkpoint: last_expansion_idx={card_list_checkpoint.get('last_expansion_idx')} "
            f"(expansion list missing — cannot resolve name)"
        )
    else:
        lines.append("  checkpoint: none (job complete or not started)")
    lines.append("")

    # Job 2 phase 2
    lines.append("--- Job 2: card list recovery (phase 2) ---")
    if recovery_checkpoint and rejected_expansions:
        start = resolve_card_list_recovery_start(recovery_checkpoint, rejected_expansions)
        total = len(rejected_expansions)
        lines.append(f"  recovery checkpoint: processed {start}/{total}")
        resume_id = recovery_checkpoint.get("last_expansion_id")
        name = recovery_checkpoint.get("last_expansion_name", "")
        if resume_id is not None:
            lines.append(f"  last recovery item: id={resume_id} name={name!r}")
        if recovery_checkpoint.get("saved_at"):
            lines.append(f"    saved_at: {recovery_checkpoint['saved_at']}")
        if start < total:
            nxt = rejected_expansions[start]
            lines.append(
                f"  next recovery: id={nxt['expansion_id']} name={nxt.get('expansion_name', '')!r}"
            )
    else:
        lines.append("  recovery checkpoint: none")
    lines.append("")

    # Job 3
    lines.append("--- Job 3: card details ---")
    if card_details is None:
        lines.append("  cardmarket_card_details.json: MISSING")
    else:
        lines.append(f"  successful detail rows: {len(card_details)}")
    if card_details_rejections is not None:
        lines.append(f"  rejections: {len(card_details_rejections)}")
    elif card_details is not None:
        lines.append("  cardmarket_card_details_rejection.json: MISSING")

    if card_details_checkpoint and card_list:
        idx = resolve_card_details_resume_index(card_details_checkpoint, card_list) - 1
        if idx >= 0 and idx < len(card_list):
            card = card_list[idx]
            lines.append(
                f"  checkpoint: idx={idx} card_id={card['card_id']} "
                f"name={card.get('card_name', '')!r}"
            )
            lines.append(
                f"    expansion: id={card.get('expansion_id')} "
                f"name={card.get('expansion_name', '')!r}"
            )
            if card_details_checkpoint.get("saved_at"):
                lines.append(f"    saved_at: {card_details_checkpoint['saved_at']}")
            progress = card_details_checkpoint.get("progress")
            if isinstance(progress, dict):
                lines.append(
                    f"    progress: {progress.get('completed_through_idx', idx) + 1}/"
                    f"{progress.get('total_cards', len(card_list))}"
                )
            next_idx = idx + 1
            if next_idx < len(card_list):
                nc = card_list[next_idx]
                lines.append(
                    f"  next pending: idx={next_idx} card_id={nc['card_id']} "
                    f"name={nc.get('card_name', '')!r}"
                )
        elif card_details_checkpoint.get("last_card_id") is not None:
            lines.append(
                f"  checkpoint: last_card_id={card_details_checkpoint['last_card_id']} "
                f"(card not found in current card list)"
            )
        else:
            raw_idx = card_details_checkpoint.get("last_processed_index", -1)
            lines.append(f"  checkpoint: last_processed_index={raw_idx}")
    elif card_details_checkpoint:
        lines.append(
            f"  checkpoint: last_processed_index="
            f"{card_details_checkpoint.get('last_processed_index')} "
            f"(card list missing — cannot resolve card name)"
        )
    else:
        lines.append("  checkpoint: none (job complete or not started)")

    return "\n".join(lines)
