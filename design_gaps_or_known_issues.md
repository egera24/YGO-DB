# Design gaps and known issues

Documented limitations of the current application design — behaviors that are intentional for now but can surprise users or lose data fidelity. Use this when debugging collection imports, planning features, or scoping fixes.

**Last updated:** 2026-07-10

---

## Topic index

| Section | Topic |
|---------|--------|
| [1. Card edition (printing) is not a first-class dimension](#1-card-edition-printing-is-not-a-first-class-dimension) | Reprints with the same card number merge; edition is overwritten |

---

## 1. Card edition (printing) is not a first-class dimension

### Summary

The app treats physical ownership as **one row per user + card number (`set_code`) + rarity**. The **edition** field (DragonShield **Printing**: Unlimited, 1st Edition, Limited Edition) is stored as metadata but **does not** split rows, drive matching, or appear in the My Collection table.

If you own both a **1st Edition** and an **Unlimited** copy of the same card number and rarity, the app cannot represent them as separate inventory lines today.

### How matching and identity work

Collection items are keyed by:

- `user_id`
- `set_code` (card number printed on the card, e.g. `LOB-EN005`)
- `rarity_code` (e.g. `UR`, `ScR`)

See `CollectionItem` in [`ygo_app/models.py`](ygo_app/models.py) and CSV import merge logic in [`ygo_app/import_data.py`](ygo_app/import_data.py) (`key = (stored_set_code, rarity_code)`).

Catalog printings in the database are also unique per **card + set code + rarity** — there is no separate catalog printing per edition.

### What happens on import (reprint scenario)

**Example:** You import `LOB-EN005` / `UR` as **1st Edition**, quantity 1. Later you import the same `LOB-EN005` / `UR` as **Unlimited**, quantity 1.

| Step | Result |
|------|--------|
| First import | One row: qty 1, edition `1st Edition` |
| Second import (append) | **Same row merged**: qty 2, edition **`Unlimited`** |

On append/merge, quantity and trade quantity are **added**. Edition is **replaced** if the new CSV row has a non-empty `Printing` cell (last merged row wins). The 1st Edition vs Unlimited distinction is lost in the stored edition field even though both copies are counted in quantity.

The same merge applies when adding via the UI if a row with the same set code and rarity already exists (identity is not edition-aware).

### Where edition is stored vs used

| Area | Edition behavior |
|------|------------------|
| Database | `collection_items.edition` column exists |
| API | Exposed as `printing` (DragonShield naming) in [`ygo_app/schemas.py`](ygo_app/schemas.py) |
| CSV import | Reads `Printing` → `edition`; default `Unlimited` |
| CSV export | Writes `edition` → `Printing` (round-trip for single-edition rows) |
| My Collection UI | **Not shown** in the table; **not editable** in the edit modal (only the add-to-collection modal sets edition) |
| Card modal owned badges | Quantities aggregated by `(set_code, rarity_code)` only — edition ignored ([`ygo_app/services.py`](ygo_app/services.py) `get_card_detail`) |
| Duplicate detection | `(set_code, rarity_code)` per user — edition not considered |

### User-visible symptoms

- My Collection shows one line per card number + rarity, not per edition.
- Importing a reprint (Unlimited) after a 1st Edition copy **increases quantity** and may **change the displayed/stored edition** to Unlimited.
- Export may show only one `Printing` value for what are physically different editions.
- Owned quantity on the card detail modal cannot distinguish 1st Edition from Unlimited copies.

### Likely fix directions (not implemented)

These are design options for a future change; none are scheduled here.

1. **Include edition in the collection unique key** — `(user_id, set_code, rarity_code, edition)` so 1st Edition and Unlimited are separate rows. Requires import merge rules, UI columns, and owned-badge aggregation updates.
2. **Keep single row but track edition quantities** — e.g. sub-counts or child allocations per edition (heavier schema/UI).
3. **UI-only improvement** — show `printing` in My Collection and allow edit, without splitting rows (does not fix the merge/overwrite problem).

### Related docs

- [`docs/importing-physical-cards.md`](docs/importing-physical-cards.md) — documents that import matching uses **Card Number + Rarity** only.
- [`next_steps.md`](next_steps.md) §9 — append merge rules for `edition` on CSV import (overwrite when cell is non-empty).
