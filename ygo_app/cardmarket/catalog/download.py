"""Discover and download Cardmarket Yu-Gi-Oh catalog JSON from S3."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ygo_app.cardmarket.catalog.errors import CatalogDownloadError
from ygo_app.cardmarket.paths import (
    CARDMARKET_PRICE_GUIDE_RAW_PATH,
    CARDMARKET_PRODUCTS_NONSINGLES_RAW_PATH,
    CARDMARKET_PRODUCTS_SINGLES_RAW_PATH,
    CARDMARKET_RAW_DIR,
)

YGO_GAME_ID = 3

DEFAULT_URLS = {
    "singles": (
        "https://downloads.s3.cardmarket.com/productCatalog/productList/"
        f"products_singles_{YGO_GAME_ID}.json"
    ),
    "nonsingles": (
        "https://downloads.s3.cardmarket.com/productCatalog/productList/"
        f"products_nonsingles_{YGO_GAME_ID}.json"
    ),
    "price_guide": (
        "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/"
        f"price_guide_{YGO_GAME_ID}.json"
    ),
}

_S3_LINK_RE = re.compile(
    r"https://downloads\.s3\.cardmarket\.com/productCatalog/[^\s\"'<>]+",
    re.IGNORECASE,
)


@dataclass
class DownloadResult:
    singles_path: Path
    nonsingles_path: Path
    price_guide_path: Path
    urls: dict[str, str]
    sha256: dict[str, str]
    row_counts: dict[str, int]


def discover_urls_from_html(html: str) -> dict[str, str]:
    links = _S3_LINK_RE.findall(html or "")
    out: dict[str, str] = {}
    for link in links:
        lower = link.lower()
        if "products_singles_" in lower and f"_{YGO_GAME_ID}.json" in lower:
            out["singles"] = link
        elif "products_nonsingles_" in lower and f"_{YGO_GAME_ID}.json" in lower:
            out["nonsingles"] = link
        elif "price_guide_" in lower and f"_{YGO_GAME_ID}.json" in lower:
            out["price_guide"] = link
    return out


def resolve_download_urls(*html_sources: str | None) -> dict[str, str]:
    urls = dict(DEFAULT_URLS)
    for html in html_sources:
        if not html:
            continue
        discovered = discover_urls_from_html(html)
        urls.update({k: v for k, v in discovered.items() if k in urls})
    return urls


def _fetch_json(url: str, timeout: int = 120) -> Any:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise CatalogDownloadError(f"Failed to download or parse {url}: {exc}") from exc


def _validate_products_payload(data: Any, label: str) -> list[dict]:
    if isinstance(data, list):
        products = data
    elif isinstance(data, dict):
        products = data.get("products")
    else:
        raise CatalogDownloadError(f"{label}: root must be an object or list")
    if not isinstance(products, list):
        raise CatalogDownloadError(f"{label}: missing 'products' list")
    for i, item in enumerate(products[:5]):
        if not isinstance(item, dict) or "idProduct" not in item:
            raise CatalogDownloadError(f"{label}: products[{i}] missing idProduct")
    return products


def _validate_price_guide_payload(data: Any) -> list[dict]:
    if isinstance(data, dict):
        guide = data.get("priceGuides") or data.get("price_guide") or data.get("products")
    elif isinstance(data, list):
        guide = data
    else:
        raise CatalogDownloadError("price_guide: unexpected root type")
    if not isinstance(guide, list):
        raise CatalogDownloadError("price_guide: expected list payload")
    for i, item in enumerate(guide[:5]):
        if not isinstance(item, dict) or "idProduct" not in item:
            raise CatalogDownloadError(f"price_guide[{i}] missing idProduct")
    return guide


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_catalog(
    *,
    output_dir: Path = CARDMARKET_RAW_DIR,
    html_sources: list[str] | None = None,
    urls: dict[str, str] | None = None,
) -> DownloadResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved = urls or resolve_download_urls(*(html_sources or []))

    singles_data = _fetch_json(resolved["singles"])
    nonsingles_data = _fetch_json(resolved["nonsingles"])
    price_data = _fetch_json(resolved["price_guide"])

    singles = _validate_products_payload(singles_data, "singles")
    nonsingles = _validate_products_payload(nonsingles_data, "nonsingles")
    prices = _validate_price_guide_payload(price_data)

    paths = {
        "singles": output_dir / CARDMARKET_PRODUCTS_SINGLES_RAW_PATH.name,
        "nonsingles": output_dir / CARDMARKET_PRODUCTS_NONSINGLES_RAW_PATH.name,
        "price_guide": output_dir / CARDMARKET_PRICE_GUIDE_RAW_PATH.name,
    }
    paths["singles"].write_text(json.dumps(singles_data, ensure_ascii=False), encoding="utf-8")
    paths["nonsingles"].write_text(json.dumps(nonsingles_data, ensure_ascii=False), encoding="utf-8")
    paths["price_guide"].write_text(json.dumps(price_data, ensure_ascii=False), encoding="utf-8")

    return DownloadResult(
        singles_path=paths["singles"],
        nonsingles_path=paths["nonsingles"],
        price_guide_path=paths["price_guide"],
        urls=resolved,
        sha256={key: _sha256_file(path) for key, path in paths.items()},
        row_counts={
            "singles": len(singles),
            "nonsingles": len(nonsingles),
            "price_guide": len(prices),
        },
    )


def load_products_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _validate_products_payload(data, path.name)


def load_price_guide_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _validate_price_guide_payload(data)
