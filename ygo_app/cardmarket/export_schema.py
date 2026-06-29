"""Cardmarket price export JSON schema (catalog pipeline → Neon import).

File: data/catalog/cardmarket_prices.json (gitignored)
R2 key: catalog/cardmarket_prices.json (private)

Schema version 1 fields:
  schema_version, exported_at, source, currency, stats, prices[]
  Each price row: set_code, rarity_code (PK), optional cardmarket_product_id,
  cardmarket_url, low_price, avg_price, trend_price, discovery_status
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH

SCHEMA_VERSION = 1
SOURCE_LABEL = "cardmarket-catalog"
DEFAULT_CURRENCY = "EUR"

REQUIRED_TOP_KEYS = frozenset(
    {"schema_version", "exported_at", "source", "currency", "stats", "prices"}
)
REQUIRED_PRICE_KEYS = frozenset({"set_code", "rarity_code", "discovery_status"})


class CardmarketExportError(ValueError):
    pass


@dataclass
class ImportGateResult:
    ok: bool
    duplicates: list[dict[str, Any]]
    missing_required: list[dict[str, Any]]
    warnings: list[str]


def validate_import_readiness(payload: dict[str, Any]) -> ImportGateResult:
    """Pre-import DQ gate: block on duplicate keys or missing required fields."""
    warnings: list[str] = []
    try:
        validate_export_payload(payload)
    except CardmarketExportError as exc:
        return ImportGateResult(
            ok=False,
            duplicates=[],
            missing_required=[{"message": str(exc)}],
            warnings=warnings,
        )

    prices = payload["prices"]
    if not prices:
        warnings.append("export contains zero price rows")

    missing_required: list[dict[str, Any]] = []
    for i, item in enumerate(prices):
        for key in REQUIRED_PRICE_KEYS:
            value = item.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_required.append({"index": i, "key": key, "set_code": item.get("set_code")})

    key_to_indices: dict[tuple[str, str], list[int]] = {}
    for i, item in enumerate(prices):
        pk = (str(item["set_code"]), str(item["rarity_code"]))
        key_to_indices.setdefault(pk, []).append(i)

    duplicates = [
        {"set_code": pk[0], "rarity_code": pk[1], "indices": indices}
        for pk, indices in key_to_indices.items()
        if len(indices) > 1
    ]

    ok = not duplicates and not missing_required
    return ImportGateResult(
        ok=ok,
        duplicates=duplicates,
        missing_required=missing_required,
        warnings=warnings,
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_export_payload(
    prices: list[dict[str, Any]],
    *,
    currency: str = DEFAULT_CURRENCY,
) -> dict[str, Any]:
    matched = sum(1 for p in prices if p.get("discovery_status") == "matched")
    unmatched = sum(1 for p in prices if p.get("discovery_status") != "matched")
    with_prices = sum(
        1
        for p in prices
        if any(p.get(k) is not None for k in ("low_price", "avg_price", "trend_price"))
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _utc_now_iso(),
        "source": SOURCE_LABEL,
        "currency": currency,
        "stats": {
            "matched": matched,
            "unmatched": unmatched,
            "with_prices": with_prices,
            "total": len(prices),
        },
        "prices": prices,
    }


def row_from_db(
    *,
    set_code: str,
    rarity_code: str,
    cardmarket_product_id: int | None = None,
    cardmarket_url: str | None = None,
    low_price: float | None = None,
    avg_price: float | None = None,
    trend_price: float | None = None,
    discovery_status: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "set_code": set_code,
        "rarity_code": rarity_code,
        "discovery_status": discovery_status or "matched",
    }
    if cardmarket_product_id is not None:
        row["cardmarket_product_id"] = cardmarket_product_id
    if cardmarket_url:
        row["cardmarket_url"] = cardmarket_url
    if low_price is not None:
        row["low_price"] = low_price
    if avg_price is not None:
        row["avg_price"] = avg_price
    if trend_price is not None:
        row["trend_price"] = trend_price
    return row


def validate_export_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CardmarketExportError("Export root must be a JSON object")
    missing = REQUIRED_TOP_KEYS - data.keys()
    if missing:
        raise CardmarketExportError(f"Missing top-level keys: {sorted(missing)}")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise CardmarketExportError(
            f"Unsupported schema_version {version!r} (expected {SCHEMA_VERSION})"
        )
    prices = data.get("prices")
    if not isinstance(prices, list):
        raise CardmarketExportError("'prices' must be a list")
    for i, item in enumerate(prices):
        if not isinstance(item, dict):
            raise CardmarketExportError(f"prices[{i}] must be an object")
        row_missing = REQUIRED_PRICE_KEYS - item.keys()
        if row_missing:
            raise CardmarketExportError(f"prices[{i}] missing keys: {sorted(row_missing)}")
    return data


def save_export(path: Path, payload: dict[str, Any]) -> None:
    validate_export_payload(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_export(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise CardmarketExportError(f"Export file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CardmarketExportError(f"Invalid export JSON: {path}") from exc
    return validate_export_payload(data)
