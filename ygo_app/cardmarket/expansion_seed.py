"""Bundled expansion_id → expansion_code seed for Cardmarket discovery."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.models import CardmarketExpansion
from ygo_app.yugipedia.scrape_progress import log_line

DEFAULT_SEED_PATH = Path(__file__).resolve().parent / "expansion_seed.json"


def load_seed_codes(path: Path | None = None) -> dict[int, str]:
    seed_path = path or DEFAULT_SEED_PATH
    if not seed_path.is_file():
        return {}
    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for row in raw:
        eid = row.get("expansion_id")
        code = (row.get("expansion_code") or "").strip()
        if eid is not None and code:
            out[int(eid)] = code.upper()
    return out


def apply_seed_to_cache(
    session: Session,
    seed: dict[int, str] | None = None,
    *,
    seed_path: Path | None = None,
) -> int:
    """Fill null expansion_code rows from bundled seed. Returns rows updated."""
    if seed is None:
        seed = load_seed_codes(seed_path)
    if not seed:
        return 0

    updated = 0
    for row in session.scalars(select(CardmarketExpansion)).all():
        if row.expansion_code:
            continue
        code = seed.get(row.expansion_id)
        if not code:
            continue
        row.expansion_code = code.upper()
        updated += 1

    if updated:
        session.commit()
        log_line(f"[EXPANSIONS] applied seed codes to {updated} cached rows")
    return updated


def regenerate_expansion_seed(
    expansion_list_path: Path,
    *,
    seed_path: Path | None = None,
) -> Path:
    """Write bundled expansion_id → expansion_code seed from a scraped expansion list."""
    out_path = seed_path or DEFAULT_SEED_PATH
    if not expansion_list_path.is_file():
        raise FileNotFoundError(f"Expansion list not found: {expansion_list_path}")

    raw = json.loads(expansion_list_path.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    seen: set[int] = set()
    for item in raw:
        eid = item.get("expansion_id")
        code = (item.get("expansion_code") or "").strip()
        if eid is None or not code:
            continue
        eid_int = int(eid)
        if eid_int in seen:
            continue
        seen.add(eid_int)
        rows.append({"expansion_id": eid_int, "expansion_code": code.upper()})

    rows.sort(key=lambda r: int(r["expansion_id"]))  # type: ignore[arg-type]
    out_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    log_line(f"[EXPANSIONS] regenerated seed with {len(rows)} codes -> {out_path}")
    return out_path
