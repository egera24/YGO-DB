"""Structured audit report for Cardmarket catalog pipeline runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from ygo_app.cardmarket.export_schema import ImportGateResult


@dataclass
class CatalogRejection:
    phase: str
    reason: str
    abbr: str | None = None
    set_name: str | None = None
    set_code: str | None = None
    card_name: str | None = None
    yugipedia_count: int | None = None
    cardmarket_count: int | None = None
    expansion_ids: list[int] | None = None
    matched_names: list[str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_expansion_error(cls, detail: dict) -> CatalogRejection:
        return cls(
            phase="expansion_map",
            reason=str(detail.get("reason") or "unknown"),
            abbr=detail.get("abbr"),
            set_name=detail.get("set_name"),
            expansion_ids=detail.get("expansion_ids"),
            matched_names=detail.get("matched_names"),
            extra={
                k: v
                for k, v in detail.items()
                if k
                not in {
                    "reason",
                    "abbr",
                    "set_name",
                    "expansion_ids",
                    "matched_names",
                }
            },
        )

    @classmethod
    def from_printing_error(
        cls,
        *,
        reason: str,
        set_code: str,
        card_name: str,
        yugipedia_count: int | None = None,
        cardmarket_count: int | None = None,
    ) -> CatalogRejection:
        abbr = set_code.split("-", 1)[0] if set_code else None
        return cls(
            phase="printing_match",
            reason=reason,
            abbr=abbr,
            set_code=set_code,
            card_name=card_name,
            yugipedia_count=yugipedia_count,
            cardmarket_count=cardmarket_count,
        )


@dataclass
class PipelineReport:
    run_id: str
    archive_ts: str
    exported_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    skipped_sets: list[dict] = field(default_factory=list)
    rejections: list[CatalogRejection] = field(default_factory=list)
    import_gate: ImportGateResult | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    r2_keys: dict[str, str | None] = field(default_factory=dict)

    @property
    def expansion_rejections(self) -> list[CatalogRejection]:
        return [r for r in self.rejections if r.phase == "expansion_map"]

    @property
    def printing_rejections(self) -> list[CatalogRejection]:
        return [r for r in self.rejections if r.phase == "printing_match"]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.import_gate is not None:
            data["import_gate"] = asdict(self.import_gate)
        return data


def save_pipeline_report(path: Path, report: PipelineReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def load_pipeline_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
