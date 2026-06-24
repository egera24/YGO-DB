"""Cardmarket job-2 catalog coverage audit (expansion list vs card/empty/rejected)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ExpansionOutcome = Literal[
    "has_cards",
    "empty",
    "rejected",
    "never_scraped",
    "ghost_processed",
    "unaccounted",
]

IssueKind = Literal[
    "unaccounted",
    "never_scraped",
    "ghost_processed",
    "orphan_card_expansion",
    "duplicate_card_id",
]


class CardListCoverageError(Exception):
    """Raised when job-2 artifacts fail the full expansion coverage audit."""


@dataclass
class ExpansionCoverageIssue:
    expansion_id: int
    expansion_name: str
    idx: int
    kind: IssueKind
    details: dict[str, Any] | None = None


@dataclass
class CardListCoverageReport:
    total_expansions: int
    has_cards: int
    empty: int
    rejected_tcg: int
    unaccounted: int
    never_scraped: int
    ghost_processed: int
    orphan_card_expansion_ids: list[int] = field(default_factory=list)
    duplicate_card_ids: list[int] = field(default_factory=list)
    issues: list[ExpansionCoverageIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.unaccounted == 0
            and self.never_scraped == 0
            and self.ghost_processed == 0
            and not self.orphan_card_expansion_ids
            and not self.duplicate_card_ids
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


def classify_expansion_outcome(
    row: dict[str, Any],
    *,
    card_list_expansion_ids: set[int],
    empty_ids: set[int],
    rejected_ids: set[int],
) -> ExpansionOutcome:
    """Classify one expansion list row by scrape outcome."""
    eid = int(row["expansion_id"])
    if eid in card_list_expansion_ids:
        return "has_cards"
    if eid in empty_ids:
        return "empty"
    if eid in rejected_ids:
        return "rejected"
    if row.get("total_number_of_cards") is None:
        return "never_scraped"
    if "total_number_of_cards" in row:
        return "ghost_processed"
    return "unaccounted"


def audit_card_list_coverage(
    *,
    expansion_list: list[dict[str, Any]],
    card_list: list[dict[str, Any]],
    empty_expansions: list[dict[str, Any]],
    rejected_expansions: list[dict[str, Any]],
) -> CardListCoverageReport:
    """Audit full TCG expansion list coverage against job-2 sidecar artifacts."""
    card_list_expansion_ids = {int(c["expansion_id"]) for c in card_list}
    empty_ids = {int(e["expansion_id"]) for e in empty_expansions}
    rejected_ids = {int(e["expansion_id"]) for e in rejected_expansions}
    expansion_ids = {int(e["expansion_id"]) for e in expansion_list}

    counts = {
        "has_cards": 0,
        "empty": 0,
        "rejected_tcg": 0,
        "never_scraped": 0,
        "ghost_processed": 0,
        "unaccounted": 0,
    }
    issues: list[ExpansionCoverageIssue] = []

    for idx, row in enumerate(expansion_list):
        outcome = classify_expansion_outcome(
            row,
            card_list_expansion_ids=card_list_expansion_ids,
            empty_ids=empty_ids,
            rejected_ids=rejected_ids,
        )
        if outcome == "has_cards":
            counts["has_cards"] += 1
        elif outcome == "empty":
            counts["empty"] += 1
        elif outcome == "rejected":
            counts["rejected_tcg"] += 1
        elif outcome == "never_scraped":
            counts["never_scraped"] += 1
            issues.append(
                ExpansionCoverageIssue(
                    expansion_id=int(row["expansion_id"]),
                    expansion_name=row.get("expansion_name", ""),
                    idx=idx,
                    kind="never_scraped",
                    details={"total_number_of_cards": row.get("total_number_of_cards")},
                )
            )
        elif outcome == "ghost_processed":
            counts["ghost_processed"] += 1
            issues.append(
                ExpansionCoverageIssue(
                    expansion_id=int(row["expansion_id"]),
                    expansion_name=row.get("expansion_name", ""),
                    idx=idx,
                    kind="ghost_processed",
                    details={"total_number_of_cards": row.get("total_number_of_cards")},
                )
            )
        else:
            counts["unaccounted"] += 1
            issues.append(
                ExpansionCoverageIssue(
                    expansion_id=int(row["expansion_id"]),
                    expansion_name=row.get("expansion_name", ""),
                    idx=idx,
                    kind="unaccounted",
                    details={"total_number_of_cards": row.get("total_number_of_cards")},
                )
            )

    orphan_card_expansion_ids = sorted(card_list_expansion_ids - expansion_ids)
    for eid in orphan_card_expansion_ids:
        names = {
            c.get("expansion_name", "")
            for c in card_list
            if int(c.get("expansion_id", -1)) == eid
        }
        issues.append(
            ExpansionCoverageIssue(
                expansion_id=eid,
                expansion_name=next(iter(names), ""),
                idx=-1,
                kind="orphan_card_expansion",
                details={"card_count": sum(1 for c in card_list if int(c["expansion_id"]) == eid)},
            )
        )

    duplicate_card_ids = sorted(
        cid for cid, n in Counter(int(c["card_id"]) for c in card_list).items() if n > 1
    )
    for cid in duplicate_card_ids:
        issues.append(
            ExpansionCoverageIssue(
                expansion_id=-1,
                expansion_name="",
                idx=-1,
                kind="duplicate_card_id",
                details={"card_id": cid},
            )
        )

    return CardListCoverageReport(
        total_expansions=len(expansion_list),
        has_cards=counts["has_cards"],
        empty=counts["empty"],
        rejected_tcg=counts["rejected_tcg"],
        unaccounted=counts["unaccounted"],
        never_scraped=counts["never_scraped"],
        ghost_processed=counts["ghost_processed"],
        orphan_card_expansion_ids=orphan_card_expansion_ids,
        duplicate_card_ids=duplicate_card_ids,
        issues=issues,
    )


def format_coverage_report_section(
    report: CardListCoverageReport,
    *,
    max_issues: int = 10,
) -> str:
    """Format the job-2 full coverage section for human-readable status output."""
    lines = [
        "--- Job 2: full coverage ---",
        f"  expansions: {report.total_expansions}",
        f"  has_cards: {report.has_cards}",
        f"  empty: {report.empty}",
        f"  rejected (TCG): {report.rejected_tcg}",
        f"  gaps: {report.unaccounted + report.never_scraped + report.ghost_processed} "
        f"(never_scraped={report.never_scraped}, ghost_processed={report.ghost_processed}, "
        f"unaccounted={report.unaccounted})",
        f"  orphan card expansions: {len(report.orphan_card_expansion_ids)}",
        f"  duplicate card_ids: {len(report.duplicate_card_ids)}",
        f"  ok: {report.ok}",
    ]
    if report.issues:
        expansion_issues = [
            issue
            for issue in report.issues
            if issue.kind in ("unaccounted", "never_scraped", "ghost_processed")
        ]
        if expansion_issues:
            lines.append(f"  issues (first {max_issues}):")
            for issue in expansion_issues[:max_issues]:
                total = (issue.details or {}).get("total_number_of_cards")
                lines.append(
                    f"    idx={issue.idx} id={issue.expansion_id} kind={issue.kind} "
                    f"total={total} name={issue.expansion_name!r}"
                )
            remaining = len(expansion_issues) - max_issues
            if remaining > 0:
                lines.append(f"    ... and {remaining} more")
        if report.orphan_card_expansion_ids:
            lines.append("  orphan expansion_ids:")
            for eid in report.orphan_card_expansion_ids[:max_issues]:
                lines.append(f"    id={eid}")
            if len(report.orphan_card_expansion_ids) > max_issues:
                lines.append(
                    f"    ... and {len(report.orphan_card_expansion_ids) - max_issues} more"
                )
        if report.duplicate_card_ids:
            lines.append("  duplicate card_ids:")
            for cid in report.duplicate_card_ids[:max_issues]:
                lines.append(f"    card_id={cid}")
            if len(report.duplicate_card_ids) > max_issues:
                lines.append(
                    f"    ... and {len(report.duplicate_card_ids) - max_issues} more"
                )
    return "\n".join(lines)


GAP_ISSUE_KINDS = frozenset({"unaccounted", "never_scraped", "ghost_processed"})


def gap_expansion_ids(report: CardListCoverageReport) -> set[int]:
    """Expansion IDs that need job-2 scraping to resolve coverage gaps."""
    return {
        issue.expansion_id
        for issue in report.issues
        if issue.kind in GAP_ISSUE_KINDS
    }


def purge_orphan_card_rows(
    card_list: list[dict[str, Any]],
    expansion_list: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Drop card rows whose expansion_id is not in the TCG expansion list."""
    expansion_ids = {int(e["expansion_id"]) for e in expansion_list}
    kept: list[dict[str, Any]] = []
    removed_ids: set[int] = set()
    for card in card_list:
        eid = int(card["expansion_id"])
        if eid in expansion_ids:
            kept.append(card)
        else:
            removed_ids.add(eid)
    return kept, sorted(removed_ids)
