"""Map Yugipedia scrape JSON to catalog import rows."""

from __future__ import annotations

import json

from ygo_app.yugipedia.adapter import yugipedia_card_to_api
from ygo_app.yugipedia.constants import MONSTER_TYPES
from ygo_app.yugipedia.images import passcode_to_int

CARD_CATEGORIES = frozenset({"Spell", "Trap", "Skill"})


def _int_field(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _json_list(values: list[str] | None) -> str | None:
    if not values:
        return None
    return json.dumps(values, ensure_ascii=False)


def _normalize_typeline(entry: dict) -> list[str]:
    typeline = entry.get("typeline") or []
    if isinstance(typeline, str):
        return [t.strip() for t in typeline.split(",") if t.strip()]
    return [str(t).strip() for t in typeline if str(t).strip()]


def _category_from_entry(entry: dict) -> str:
    kind = entry.get("type")
    if kind in CARD_CATEGORIES:
        return kind
    return "Monster"


def _types_from_entry(entry: dict, *, category: str) -> list[str]:
    if category in CARD_CATEGORIES:
        prop = (entry.get("property") or "").strip()
        return [prop] if prop else [category]
    return _normalize_typeline(entry)


def yugipedia_entry_to_import(entry: dict) -> dict | None:
    """Build one import row (Card fields + card_sets + card_images) from scrape JSON."""
    pid = passcode_to_int(entry.get("id"))
    if pid is None:
        return None

    api = yugipedia_card_to_api(entry)
    if api is None:
        return None

    category = _category_from_entry(entry)
    types_list = _types_from_entry(entry, category=category)
    typeline = _normalize_typeline(entry)

    mechanic = None
    rank = None
    link_rating = None
    pendulum_scale = None
    link_markers_json = None
    summoning_condition = None
    attribute = None

    if category == "Monster":
        mechanic = entry.get("mechanic")
        if mechanic is not None:
            mechanic = str(mechanic).strip() or None
        rank = _int_field(entry.get("rank"))
        link_rating = _int_field(entry.get("link_rating"))
        pendulum_scale = _int_field(entry.get("pendulum_scale"))
        markers = entry.get("link_markers")
        if isinstance(markers, list) and markers:
            link_markers_json = _json_list([str(m) for m in markers])
        summoning_condition = entry.get("summoning_condition")
        if summoning_condition is not None:
            summoning_condition = str(summoning_condition).strip() or None
        attribute = entry.get("attribute")

    level = _int_field(entry.get("level"))
    if category == "Monster" and level is None:
        level = _int_field(api.get("level"))
    if category == "Monster" and rank is None:
        rank = _int_field(entry.get("rank"))

    race = entry.get("type")
    if category == "Monster" and race not in MONSTER_TYPES:
        race = next((t for t in typeline if t in MONSTER_TYPES), race)

    return {
        **api,
        "category": category,
        "types": _json_list(types_list),
        "mechanic": mechanic,
        "attribute": attribute if category == "Monster" else api.get("attribute"),
        "race": race if category == "Monster" else api.get("race"),
        "level": level if category == "Monster" else None,
        "rank": rank,
        "link_rating": link_rating,
        "linkval": link_rating if link_rating is not None else api.get("linkval"),
        "pendulum_scale": pendulum_scale,
        "scale": pendulum_scale if pendulum_scale is not None else api.get("scale"),
        "link_markers": link_markers_json,
        "summoning_condition": summoning_condition,
        "atk": _int_field(entry.get("atk")) if category == "Monster" else api.get("atk"),
        "def": _int_field(entry.get("def")) if category == "Monster" else api.get("def"),
    }


def yugipedia_entries_to_import(entries: list[dict]) -> list[dict]:
    """Convert scraped list to import rows; skips entries without English printings."""
    out: list[dict] = []
    skipped_no_printings = 0
    skipped_invalid = 0
    for entry in entries:
        if not entry.get("card_sets"):
            skipped_no_printings += 1
            continue
        mapped = yugipedia_entry_to_import(entry)
        if mapped:
            out.append(mapped)
        else:
            skipped_invalid += 1
    if skipped_no_printings:
        print(f"Skipped {skipped_no_printings} entries with no English printings")
    if skipped_invalid:
        print(f"Skipped {skipped_invalid} entries with invalid passcode")
    return out


def enrich_ygopro_entry(entry: dict) -> dict:
    """Best-effort Yugipedia fields for YGOProDeck API-shaped entries."""
    frame = (entry.get("frameType") or "").lower()
    card_type = entry.get("type") or ""

    if frame == "spell" or "Spell" in card_type:
        category = "Spell"
    elif frame == "trap" or "Trap" in card_type:
        category = "Trap"
    elif "Skill" in card_type:
        category = "Skill"
    else:
        category = "Monster"

    types_list: list[str] = []
    if category in CARD_CATEGORIES:
        race = entry.get("race") or ""
        types_list = [race] if race else [category]
    else:
        race = entry.get("race")
        if race:
            types_list.append(race)
        frame_map = {
            "normal": "Normal",
            "effect": "Effect",
            "fusion": "Fusion",
            "synchro": "Synchro",
            "xyz": "Xyz",
            "link": "Link",
            "ritual": "Ritual",
            "normal_pendulum": "Pendulum",
            "effect_pendulum": "Pendulum",
        }
        label = frame_map.get(frame)
        if label and label not in types_list:
            types_list.append(label)
        if "Effect" in (card_type or "") and "Effect" not in types_list:
            types_list.append("Effect")

    mechanic = None
    if category == "Monster" and frame:
        pendulum = "pendulum" in frame
        if frame in ("fusion", "synchro", "xyz", "link", "ritual"):
            mechanic = frame.replace("_pendulum", "").title()
            if mechanic == "Xyz":
                mechanic = "Xyz"
            elif mechanic == "Link":
                mechanic = "Link"
        elif pendulum:
            mechanic = "Pendulum"

    link_rating = _int_field(entry.get("linkval"))
    pendulum_scale = _int_field(entry.get("scale"))
    rank = _int_field(entry.get("rank"))
    level = _int_field(entry.get("level"))
    if category == "Monster" and frame == "xyz" and level is not None and rank is None:
        rank = level
        level = None

    entry = dict(entry)
    entry["level"] = level
    entry["category"] = category
    entry["types"] = _json_list(types_list)
    entry["mechanic"] = mechanic
    entry["rank"] = rank
    entry["link_rating"] = link_rating
    entry["pendulum_scale"] = pendulum_scale
    if link_rating is not None:
        entry["linkval"] = link_rating
    if pendulum_scale is not None:
        entry["scale"] = pendulum_scale
    return entry
