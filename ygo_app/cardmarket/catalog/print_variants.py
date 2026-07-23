"""Collapse Cardmarket print-design variant batches before price pairing."""

from __future__ import annotations

from statistics import median


MAX_MAJOR_GAP = 5000


def _major_gap_threshold(gaps: list[int]) -> int:
    if not gaps:
        return 2
    # Median-based threshold works well when there are many ids, but with only a
    # couple ids the median can be huge (e.g. jumbo/oversized variants with a big
    # idProduct gap). Cap it so obvious separate batches split reliably.
    return min(MAX_MAJOR_GAP, max(2, int(median(gaps)) * 2))


def split_consecutive_id_runs(
    rows: list[dict],
    *,
    major_gap_threshold: int | None = None,
) -> list[list[dict]]:
    """Split CM rows into consecutive idProduct runs separated by major gaps."""
    if not rows:
        return []
    sorted_rows = sorted(rows, key=lambda row: int(row["idProduct"]))
    if len(sorted_rows) == 1:
        return [sorted_rows]

    gaps = [
        int(sorted_rows[index + 1]["idProduct"]) - int(sorted_rows[index]["idProduct"])
        for index in range(len(sorted_rows) - 1)
    ]
    threshold = (
        major_gap_threshold if major_gap_threshold is not None else _major_gap_threshold(gaps)
    )

    runs: list[list[dict]] = [[sorted_rows[0]]]
    for index, gap in enumerate(gaps):
        if gap > threshold:
            runs.append([sorted_rows[index + 1]])
        else:
            runs[-1].append(sorted_rows[index + 1])
    return runs


def _run_avg_sum(run: list[dict], price_index: dict[int, dict]) -> float:
    total = 0.0
    for row in run:
        avg = price_index.get(int(row["idProduct"]), {}).get("avg")
        if avg is None:
            return float("inf")
        total += float(avg)
    return total


def _select_run(
    runs: list[list[dict]],
    *,
    target_count: int,
    price_index: dict[int, dict],
) -> list[dict] | None:
    if not runs:
        return None

    matching = [run for run in runs if len(run) == target_count]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1:
        return min(matching, key=lambda run: _run_avg_sum(run, price_index))

    if len(runs) == 2 and all(len(run) == target_count for run in runs):
        return min(runs, key=lambda run: _run_avg_sum(run, price_index))

    if len(runs) == 2 and len(runs[1]) == target_count:
        return runs[1]

    if len(runs) == 2 and len(runs[0]) == target_count:
        return runs[0]

    return None


def collapse_cm_print_variants(
    rows: list[dict],
    *,
    target_count: int,
    price_index: dict[int, dict],
) -> list[dict]:
    """
    Reduce CM rows to one design batch when Cardmarket lists multiple idProducts
    per Yugipedia printing slot (e.g. normal vs emblazoned).
    """
    if target_count <= 0 or len(rows) <= target_count:
        return rows

    selected = _select_run(
        split_consecutive_id_runs(rows),
        target_count=target_count,
        price_index=price_index,
    )
    if selected is not None:
        return selected
    return rows
