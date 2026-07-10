"""Parse Yugipedia card wiki HTML into structured dicts."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ygo_app.yugipedia.card_sets import extract_card_sets
from ygo_app.yugipedia.constants import (
    LINK_MARKER_MAP,
    MONSTER_MECHANICS,
    MONSTER_TYPES,
)
from ygo_app.yugipedia.images import (
    YUGIPEDIA_MEDIA_HOST,
    is_yugipedia_card_art_filename,
    yugipedia_image_urls_from_src,
)
from ygo_app.yugipedia.related_links import extract_related_links


def _merge_related_links(card_data: dict, soup: BeautifulSoup) -> None:
    """Record Errata/Tips wiki URLs from the card page (null when absent or redlink)."""
    card_data.update(extract_related_links(soup))


def extract_text_only(element) -> str:
    if not element:
        return ""
    for br in element.find_all("br"):
        br.replace_with("\n")
    text = element.get_text()
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def find_row_by_header(soup: BeautifulSoup, header_text: str):
    for th in soup.find_all("th"):
        if header_text in th.get_text():
            tr = th.find_parent("tr")
            if tr:
                return tr
    return None


def extract_password_from_page(soup: BeautifulSoup) -> str | None:
    row = find_row_by_header(soup, "Password")
    if row:
        td = row.find("td")
        if td:
            link = td.find("a")
            if link:
                return link.get_text().strip().zfill(8)
    return None


def extract_property(soup: BeautifulSoup) -> str | None:
    row = find_row_by_header(soup, "Property")
    if row:
        td = row.find("td")
        if td:
            link = td.find("a")
            if link:
                return link.get_text().strip()
    return None


def extract_attribute(soup: BeautifulSoup) -> str | None:
    row = find_row_by_header(soup, "Attribute")
    if row:
        td = row.find("td")
        if td:
            link = td.find("a")
            if link:
                return link.get_text().strip()
    return None


def extract_typeline(soup: BeautifulSoup) -> list[str]:
    row = find_row_by_header(soup, "Types")
    if row:
        td = row.find("td")
        if td:
            types = []
            for link in td.find_all("a"):
                type_text = link.get_text().strip()
                if type_text:
                    types.append(type_text)
            return types
    return []


def determine_monster_type(typeline: list[str]) -> str | None:
    for t in typeline:
        if t in MONSTER_TYPES:
            return t
    return None


def determine_mechanics(typeline: list[str]) -> list[str] | None:
    mechanics = [t for t in typeline if t in MONSTER_MECHANICS]
    return mechanics if mechanics else None


def has_effect(typeline: list[str]) -> str:
    return "yes" if "Effect" in typeline else "no"


def extract_level_or_rank(soup: BeautifulSoup) -> dict | None:
    row = find_row_by_header(soup, "Level")
    if row:
        td = row.find("td")
        if td:
            link = td.find("a")
            if link:
                match = re.search(r"\d+", link.get_text())
                if match:
                    return {"level": int(match.group())}
    row = find_row_by_header(soup, "Rank")
    if row:
        td = row.find("td")
        if td:
            link = td.find("a")
            if link:
                match = re.search(r"\d+", link.get_text())
                if match:
                    return {"rank": int(match.group())}
    return None


def extract_pendulum_scale(soup: BeautifulSoup) -> int | None:
    row = find_row_by_header(soup, "Pendulum Scale")
    if row:
        td = row.find("td")
        if td:
            link = td.find("a", href=lambda x: x and "Pendulum_Scale_" in x)
            if link:
                match = re.search(r"\d+", link.get_text())
                if match:
                    return int(match.group())
    return None


def extract_link_markers(soup: BeautifulSoup) -> list[str] | None:
    row = find_row_by_header(soup, "Link Arrow")
    if row:
        td = row.find("td")
        if td:
            markers = []
            hlist = td.find("div", class_="hlist")
            if hlist:
                for li in hlist.find_all("li"):
                    link = li.find("a")
                    if link:
                        arrow_text = link.get_text().strip()
                        if arrow_text in LINK_MARKER_MAP:
                            mapped = LINK_MARKER_MAP[arrow_text]
                            if mapped not in markers:
                                markers.append(mapped)
            return markers if markers else None
    return None


def extract_atk_def(soup: BeautifulSoup, *, is_link: bool = False) -> dict:
    result: dict = {}
    row = find_row_by_header(soup, "ATK")
    if not row:
        return result
    td = row.find("td")
    if not td:
        return result
    links = td.find_all("a")
    if len(links) >= 1:
        atk_text = links[0].get_text().strip()
        match = re.search(r"\d+", atk_text)
        if match:
            result["atk"] = int(match.group())
        else:
            result["atk"] = atk_text
    if len(links) >= 2:
        if is_link:
            match = re.search(r"\d+", links[1].get_text())
            if match:
                result["link_rating"] = int(match.group())
        else:
            def_text = links[1].get_text().strip()
            match = re.search(r"\d+", def_text)
            if match:
                result["def"] = int(match.group())
            else:
                result["def"] = def_text
    return result


def extract_lore_description(soup: BeautifulSoup, *, is_pendulum: bool = False) -> dict | None:
    lore_div = soup.find("div", class_="lore")
    if not lore_div:
        return None
    if is_pendulum:
        result = {}
        dl = lore_div.find("dl")
        if dl:
            current_section = None
            for child in dl.children:
                if child.name == "dt":
                    current_section = child.get_text().strip()
                elif child.name == "dd" and current_section:
                    text = extract_text_only(child)
                    if "Pendulum Effect" in current_section:
                        result["pendulum_description"] = text
                    elif "Monster Effect" in current_section:
                        result["monster_description"] = text
            if "pendulum_description" in result and "monster_description" in result:
                result["description"] = (
                    f"[ Pendulum Effect ]\n{result['pendulum_description']}\n\n"
                    f"[ Monster Effect ]\n{result['monster_description']}"
                )
            return result
    return {"description": extract_text_only(lore_div)}


def extract_summoning_condition(soup: BeautifulSoup, typeline: list[str]) -> str | None:
    special_types = ["Link", "Synchro", "Xyz", "Fusion"]
    if not any(t in typeline for t in special_types):
        return None
    lore_div = soup.find("div", class_="lore")
    if lore_div:
        text = lore_div.get_text()
        lines = text.split("\n")
        if lines:
            first_line = lines[0].strip()
            if "." in first_line:
                first_line = first_line.split(".")[0].strip() + "."
            return first_line
    return None


def _filename_from_img(img) -> str | None:
    parent = img.find_parent("a")
    if parent and parent.get("href", "").startswith("/wiki/File:"):
        return parent["href"].split("/wiki/File:", 1)[-1]
    src = img.get("src") or ""
    if "/thumb/" in src:
        parts = src.rsplit("/", 2)
        if len(parts) >= 2:
            last = parts[-1]
            if "px-" in last:
                return last.split("px-", 1)[-1]
            return last
    if src:
        return src.rsplit("/", 1)[-1]
    return None


def _img_render_width(img) -> int:
    width = img.get("width")
    if width is not None and str(width).isdigit():
        return int(width)
    src = img.get("src") or ""
    match = re.search(r"/(\d+)px-", src)
    if match:
        return int(match.group(1))
    return 0


def extract_card_image(soup: BeautifulSoup) -> dict[str, str | None] | None:
    """Extract main card artwork URLs from a Yugipedia card wiki page."""
    candidates: list[tuple[int, str, str | None]] = []

    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if YUGIPEDIA_MEDIA_HOST not in src:
            continue
        if "noviewer" in (img.get("class") or []):
            continue
        if src.lower().endswith(".svg"):
            continue

        filename = _filename_from_img(img)
        if filename and not is_yugipedia_card_art_filename(filename):
            continue

        width = _img_render_width(img)
        candidates.append((width, src, filename))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_src = candidates[0][1]
    urls = yugipedia_image_urls_from_src(best_src)
    if not urls.get("image_url"):
        return None
    return urls


def _merge_card_image(card_data: dict, soup: BeautifulSoup) -> None:
    images = extract_card_image(soup)
    if images:
        card_data.update(images)


def extract_archetype(soup: BeautifulSoup) -> list[str] | None:
    for dt in soup.find_all("dt"):
        if "Archetype" in dt.get_text():
            dl = dt.find_parent("dl")
            if dl:
                archetypes = []
                for dd in dl.find_all("dd"):
                    link = dd.find("a")
                    if link:
                        archetype_text = link.get_text().strip()
                        if archetype_text and archetype_text not in archetypes:
                            archetypes.append(archetype_text)
                return archetypes if archetypes else None
    return None


def normalize_passcode_card_type(card_type: str) -> str:
    """Map Yugipedia/SMW card-type labels to parse_card_page routing labels.

    SMW passcode rows use values like ``Monster Card``. Passwordless token pages
    may use ``Token`` or ``Monster Token`` when a type is present on the input row.
    """
    text = (card_type or "").strip()
    if not text:
        return ""
    if text in ("Monster Card", "Spell Card", "Trap Card", "Skill Card", "Token Card"):
        return text
    lower = text.lower()
    if "token" in lower:
        return "Token Card"
    for key in ("Monster", "Spell", "Trap", "Skill"):
        if text == key:
            return f"{key} Card"
    return text


def extract_card_type_from_page(soup: BeautifulSoup) -> str | None:
    """Read the 'Card type' infobox row (Monster/Spell/Trap/Skill/Token).

    Used for cards discovered without a card type (passwordless category members),
    returning the same labels the passcode list carries (e.g. 'Monster Card').
    """
    row = find_row_by_header(soup, "Card type")
    if not row:
        return None
    td = row.find("td")
    if not td:
        return None
    text = td.get_text()
    for key in ("Monster", "Spell", "Trap", "Skill"):
        if key in text:
            return f"{key} Card"
    if "Token" in text:
        return "Token Card"
    return None


def _apply_token_category(card_data: dict) -> None:
    """Mark scrape JSON as a Token card (Yugipedia card type, not Monster)."""
    card_data["category"] = "Token"
    typeline = list(card_data.get("typeline") or [])
    if "Token" not in typeline:
        typeline.append("Token")
    card_data["typeline"] = typeline


def parse_token_card(soup: BeautifulSoup, input_card: dict) -> tuple[dict | None, str | None]:
    """Parse a Token card page (monster stats + Token card type)."""
    card_data, error = parse_monster_card(soup, input_card)
    if error or card_data is None:
        return card_data, error
    _apply_token_category(card_data)
    return card_data, None


def _init_card_data(input_card: dict, **extra) -> dict:
    """Seed a card_data dict; passwordless cards carry id=None + a passwordless flag."""
    passwordless = bool(input_card.get("passwordless"))
    data: dict = {
        "id": None if passwordless else input_card["password"],
        "name": input_card["name"],
    }
    if input_card.get("url"):
        data["source_url"] = input_card["url"]
    if passwordless:
        data["passwordless"] = True
    character = (input_card.get("character") or "").strip()
    if character:
        data["character"] = character
    property_val = (input_card.get("property") or "").strip()
    if property_val:
        data["property"] = property_val
    data.update(extra)
    return data


def _password_mismatch_error(soup: BeautifulSoup, input_card: dict) -> str | None:
    """Return an error string when the page password disagrees with the input.

    Skipped entirely for passwordless cards (their pages show 'Password: None').
    """
    if input_card.get("passwordless"):
        return None
    page_password = extract_password_from_page(soup)
    if page_password != input_card["password"]:
        return (
            f"Password mismatch: expected {input_card['password']}, "
            f"found {page_password}"
        )
    return None


def parse_monster_card(soup: BeautifulSoup, input_card: dict) -> tuple[dict | None, str | None]:
    card_data: dict = _init_card_data(input_card)
    try:
        pw_error = _password_mismatch_error(soup, input_card)
        if pw_error:
            return None, pw_error
        typeline = extract_typeline(soup)
        if typeline:
            card_data["typeline"] = typeline
        attribute = extract_attribute(soup)
        if attribute:
            card_data["attribute"] = attribute
        monster_type = determine_monster_type(typeline)
        if monster_type:
            card_data["type"] = monster_type
        mechanics = determine_mechanics(typeline)
        if mechanics:
            card_data["mechanic"] = ", ".join(mechanics) if len(mechanics) > 1 else mechanics[0]
        card_data["effect"] = has_effect(typeline)
        level_rank = extract_level_or_rank(soup)
        if level_rank:
            card_data.update(level_rank)
        is_pendulum = "Pendulum" in typeline
        if is_pendulum:
            pendulum_scale = extract_pendulum_scale(soup)
            if pendulum_scale is not None:
                card_data["pendulum_scale"] = pendulum_scale
        is_link = "Link" in typeline
        if is_link:
            link_markers = extract_link_markers(soup)
            if link_markers:
                card_data["link_markers"] = link_markers
        card_data.update(extract_atk_def(soup, is_link=is_link))
        lore = extract_lore_description(soup, is_pendulum=is_pendulum)
        if lore:
            card_data.update(lore)
        summoning_cond = extract_summoning_condition(soup, typeline)
        if summoning_cond:
            card_data["summoning_condition"] = summoning_cond
        archetype = extract_archetype(soup)
        if archetype:
            card_data["archetype"] = ", ".join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data["card_sets"] = card_sets
        _merge_card_image(card_data, soup)
        _merge_related_links(card_data, soup)
        return card_data, None
    except Exception as e:
        return None, f"Error parsing monster card: {e}"


def parse_spell_card(soup: BeautifulSoup, input_card: dict) -> tuple[dict | None, str | None]:
    card_data: dict = _init_card_data(input_card, type="Spell")
    try:
        pw_error = _password_mismatch_error(soup, input_card)
        if pw_error:
            return None, pw_error
        property_val = extract_property(soup)
        if property_val:
            card_data["property"] = property_val
        lore = extract_lore_description(soup, is_pendulum=False)
        if lore and "description" in lore:
            card_data["description"] = lore["description"]
        archetype = extract_archetype(soup)
        if archetype:
            card_data["archetype"] = ", ".join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data["card_sets"] = card_sets
        _merge_card_image(card_data, soup)
        _merge_related_links(card_data, soup)
        return card_data, None
    except Exception as e:
        return None, f"Error parsing spell card: {e}"


def parse_trap_card(soup: BeautifulSoup, input_card: dict) -> tuple[dict | None, str | None]:
    card_data: dict = _init_card_data(input_card, type="Trap")
    try:
        pw_error = _password_mismatch_error(soup, input_card)
        if pw_error:
            return None, pw_error
        property_val = extract_property(soup)
        if property_val:
            card_data["property"] = property_val
        lore = extract_lore_description(soup, is_pendulum=False)
        if lore and "description" in lore:
            card_data["description"] = lore["description"]
        archetype = extract_archetype(soup)
        if archetype:
            card_data["archetype"] = ", ".join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data["card_sets"] = card_sets
        _merge_card_image(card_data, soup)
        _merge_related_links(card_data, soup)
        return card_data, None
    except Exception as e:
        return None, f"Error parsing trap card: {e}"


def parse_skill_card(soup: BeautifulSoup, input_card: dict) -> tuple[dict | None, str | None]:
    card_data: dict = _init_card_data(input_card, type="Skill")
    try:
        pw_error = _password_mismatch_error(soup, input_card)
        if pw_error:
            return None, pw_error
        property_val = extract_property(soup)
        if property_val:
            card_data["property"] = property_val
        lore = extract_lore_description(soup, is_pendulum=False)
        if lore and "description" in lore:
            card_data["description"] = lore["description"]
        archetype = extract_archetype(soup)
        if archetype:
            card_data["archetype"] = ", ".join(archetype) if len(archetype) > 1 else archetype[0]
        card_sets = extract_card_sets(soup)
        if card_sets:
            card_data["card_sets"] = card_sets
        _merge_card_image(card_data, soup)
        _merge_related_links(card_data, soup)
        return card_data, None
    except Exception as e:
        return None, f"Error parsing skill card: {e}"


def parse_card_page(html: str, input_card: dict) -> tuple[dict | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    card_type = normalize_passcode_card_type(input_card.get("card_type", ""))
    # Passwordless category members arrive without a card type; read it off the page.
    if not card_type:
        card_type = extract_card_type_from_page(soup) or ""
    if card_type == "Monster Card":
        card_data, error = parse_monster_card(soup, input_card)
        if error or card_data is None:
            return card_data, error
        if "Token" in (card_data.get("typeline") or []):
            _apply_token_category(card_data)
        return card_data, None
    if card_type == "Token Card":
        return parse_token_card(soup, input_card)
    if card_type == "Spell Card":
        return parse_spell_card(soup, input_card)
    if card_type == "Trap Card":
        return parse_trap_card(soup, input_card)
    if card_type == "Skill Card":
        return parse_skill_card(soup, input_card)
    return None, f"Unknown card type: {card_type or '(none)'}"
