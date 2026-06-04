"""Convert Yugipedia scrape JSON to YGOProDeck-compatible catalog entries."""

from __future__ import annotations

from ygo_app.yugipedia.constants import MONSTER_MECHANICS, MONSTER_TYPES
from ygo_app.yugipedia.images import passcode_to_int, ygoprodeck_card_url


def _int_field(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _monster_frame_type(typeline: list[str]) -> str:
    if "Link" in typeline:
        return "link"
    if "Xyz" in typeline:
        return "xyz"
    if "Synchro" in typeline:
        return "synchro"
    if "Fusion" in typeline:
        return "fusion"
    if "Ritual" in typeline:
        return "ritual"
    if "Pendulum" in typeline:
        return "effect_pendulum" if "Effect" in typeline else "normal_pendulum"
    if "Effect" in typeline:
        return "effect"
    return "normal"


def _monster_type_label(typeline: list[str]) -> str:
    """YGOProDeck `type` field, e.g. 'Effect Monster', 'Synchro Monster'."""
    parts = [t for t in typeline if t in MONSTER_MECHANICS or t == "Effect"]
    if not parts:
        return "Monster"
    if "Effect" in parts and len(parts) > 1:
        mechanics = [p for p in parts if p != "Effect"]
        if mechanics:
            primary = mechanics[-1]
            if primary == "Normal":
                return "Effect Monster"
            return f"{primary} Monster"
    if parts[-1] == "Effect":
        return "Effect Monster"
    return f"{parts[-1]} Monster"


def _human_readable_monster(typeline: list[str], race: str | None) -> str:
    labels = [t for t in typeline if t in MONSTER_MECHANICS or t == "Effect"]
    if not labels:
        return f"{race} Monster" if race else "Monster"
    return " ".join(labels) + " Monster"


def _adapt_card_sets(card_sets: list[dict] | None) -> list[dict]:
    if not card_sets:
        return []
    out = []
    for cs in card_sets:
        code = cs.get("set_rarity_code") or ""
        out.append(
            {
                "set_name": cs.get("set_name"),
                "set_code": cs.get("set_code"),
                "set_rarity": cs.get("set_rarity"),
                "set_rarity_code": code,
                "set_price": cs.get("set_price"),
            }
        )
    return out


def _resolve_images(entry: dict, pid: int) -> dict[str, str | None]:
    """Use Yugipedia URLs from scrape JSON; no YGOPRODeck CDN fallback."""
    image_url = entry.get("image_url")
    image_url_small = entry.get("image_url_small")
    if image_url and not image_url_small:
        image_url_small = image_url
    return {
        "ygoprodeck_url": ygoprodeck_card_url(pid),
        "image_url": image_url,
        "image_url_small": image_url_small,
    }


def yugipedia_card_to_api(entry: dict) -> dict | None:
    """Map one Yugipedia card dict to YGOProDeck API card shape."""
    pid = passcode_to_int(entry.get("id"))
    if pid is None:
        return None

    images = _resolve_images(entry, pid)
    card_sets = _adapt_card_sets(entry.get("card_sets"))
    card_images = [
        {
            "image_url": images["image_url"],
            "image_url_small": images["image_url_small"],
        }
    ]

    # Spell / Trap
    if entry.get("type") in ("Spell", "Trap"):
        prop = entry.get("property") or ""
        kind = entry.get("type")
        return {
            "id": pid,
            "name": entry.get("name", ""),
            "type": f"{kind} Card",
            "humanReadableCardType": f"{prop} {kind} Card".strip() if prop else f"{kind} Card",
            "frameType": kind.lower(),
            "desc": entry.get("description"),
            "race": prop or kind,
            "attribute": None,
            "archetype": entry.get("archetype"),
            "atk": None,
            "def": None,
            "level": None,
            "linkval": None,
            "scale": None,
            "ygoprodeck_url": images["ygoprodeck_url"],
            "card_images": card_images,
            "card_sets": card_sets,
        }

    # Monster
    typeline = entry.get("typeline") or []
    if isinstance(typeline, str):
        typeline = [t.strip() for t in typeline.split(",")]

    race = entry.get("type")
    if race not in MONSTER_TYPES:
        race = next((t for t in typeline if t in MONSTER_TYPES), race)

    level = _int_field(entry.get("level")) or _int_field(entry.get("rank"))

    return {
        "id": pid,
        "name": entry.get("name", ""),
        "type": _monster_type_label(typeline),
        "humanReadableCardType": _human_readable_monster(typeline, race),
        "frameType": _monster_frame_type(typeline),
        "desc": entry.get("description"),
        "atk": _int_field(entry.get("atk")),
        "def": _int_field(entry.get("def")),
        "level": level,
        "race": race,
        "attribute": entry.get("attribute"),
        "archetype": entry.get("archetype"),
        "linkval": _int_field(entry.get("link_rating")),
        "scale": _int_field(entry.get("pendulum_scale")),
        "ygoprodeck_url": images["ygoprodeck_url"],
        "card_images": card_images,
        "card_sets": card_sets,
    }


def yugipedia_entries_to_api(entries: list[dict]) -> list[dict]:
    """Convert scraped Yugipedia list to API-shaped entries for import_cards_entries."""
    api_entries: list[dict] = []
    skipped = 0
    for entry in entries:
        mapped = yugipedia_card_to_api(entry)
        if mapped:
            api_entries.append(mapped)
        else:
            skipped += 1
    if skipped:
        print(f"Skipped {skipped} entries with invalid passcode")
    return api_entries
