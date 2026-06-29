"""Parse Cardmarket product detail pages for price fields."""

from __future__ import annotations

from bs4 import BeautifulSoup


def parse_price(price_text: str | None) -> tuple[float | None, bool]:
    """Return (value, is_na). is_na=True when the field is explicitly N/A."""
    try:
        if not price_text:
            return None, False

        lower = price_text.lower().strip()
        if lower in ("n/a", "n.a.", "na", "--", "---", "–", "—"):
            return None, True

        cleaned = "".join(c for c in price_text if c.isdigit() or c in ".,-")
        if not cleaned or cleaned in (".", ",", "-", ".-", ",-"):
            return None, False

        dot_count = cleaned.count(".")
        comma_count = cleaned.count(",")

        if comma_count == 0 and dot_count <= 1:
            return float(cleaned), False
        if comma_count == 1 and dot_count == 0:
            return float(cleaned.replace(",", ".")), False

        if dot_count > 0 and comma_count > 0:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif dot_count > 1:
            cleaned = cleaned.replace(".", "")
        elif comma_count > 1:
            cleaned = cleaned.replace(",", "")

        return float(cleaned), False
    except (TypeError, ValueError):
        return None, False


def extract_price_data(html: str) -> dict[str, float | None]:
    """
    Extract LOW, TREND, and 30-day AVG from a product detail page.
    Partial results are returned (missing fields stay None).
    """
    soup = BeautifulSoup(html, "html.parser")
    prices: dict[str, float | None] = {
        "low_price": None,
        "trend_price": None,
        "avg_price": None,
    }

    label_map = {
        "from": "low_price",
        "price trend": "trend_price",
        "30-day": "avg_price",
    }

    for dt in soup.find_all("dt"):
        dt_text = dt.get_text(strip=True).lower()
        for label, price_key in label_map.items():
            if label not in dt_text:
                continue
            dd = dt.find_next_sibling("dd")
            if not dd:
                break
            price_value, is_na = parse_price(dd.get_text(strip=True))
            if not is_na and price_value is not None:
                prices[price_key] = price_value
            break

    return prices


_FULL_PRICE_LABELS = {
    "from": "low_price",
    "price trend": "trend_price",
    "30-day": "avg_30_price",
    "7-day": "avg_7_price",
    "1-day": "avg_1_price",
}


def extract_full_price_data(html: str) -> tuple[dict[str, float] | None, bool]:
    """
    Strict legacy extraction: all 5 price fields required.
    Returns (prices_dict, has_na). has_na=True when any field is explicitly N/A.
    """
    soup = BeautifulSoup(html, "html.parser")
    prices: dict[str, float | None] = {
        "low_price": None,
        "trend_price": None,
        "avg_30_price": None,
        "avg_7_price": None,
        "avg_1_price": None,
    }

    na_count = 0
    found_count = 0
    valid_count = 0

    for dt in soup.find_all("dt"):
        dt_text = dt.get_text(strip=True).lower()
        for label, price_key in _FULL_PRICE_LABELS.items():
            if label not in dt_text:
                continue
            dd = dt.find_next_sibling("dd")
            if not dd:
                break
            price_value, is_na = parse_price(dd.get_text(strip=True))
            found_count += 1
            if is_na:
                na_count += 1
            elif price_value is not None:
                prices[price_key] = price_value
                valid_count += 1
            break

    if na_count > 0:
        return None, True
    if found_count < 5 or valid_count < 5:
        return None, False

    return prices, False  # type: ignore[return-value]
