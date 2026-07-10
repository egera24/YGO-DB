# Design gaps and known issues

Documented limitations of the current application design — behaviors that are intentional for now but can surprise users or lose data fidelity. Use this when debugging collection imports, planning features, or scoping fixes.

**Last updated:** 2026-07-10

---

## Topic index

| Section | Topic |
|---------|--------|
| [1. Card edition (printing) is not a first-class dimension](#1-card-edition-printing-is-not-a-first-class-dimension) | Reprints with the same card number merge; edition is overwritten |
| [2. Card condition is not a first-class dimension](#2-card-condition-is-not-a-first-class-dimension) | Same card + rarity with different conditions merge; condition is overwritten |

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
- [§2. Card condition is not a first-class dimension](#2-card-condition-is-not-a-first-class-dimension) — same merge pattern for condition.

---

## 2. Card condition is not a first-class dimension

### Summary

The app stores **condition** (Near Mint, Light Played, etc.) on each collection row, but condition **does not** split rows or participate in import matching. Identity is still **one row per user + card number (`set_code`) + rarity**.

If you own one **Near Mint** and one **Light Played** copy of the same card number and rarity, the app cannot represent them as separate inventory lines today.

### How matching and identity work

Collection items are keyed by:

- `user_id`
- `set_code` (card number printed on the card, e.g. `LOB-EN005`)
- `rarity_code` (e.g. `UR`, `ScR`)

Condition is **not** part of this key. See CSV import merge logic in [`ygo_app/import_data.py`](ygo_app/import_data.py) (`key = (stored_set_code, rarity_code)`).

### What happens on import (different conditions)

**Example:** You import two CSV rows for the same card:

```csv
Card Number,Rarity,Quantity,Condition
LOB-001,UR,1,NearMint
LOB-001,UR,1,LightPlayed
```

| Step | Result |
|------|--------|
| First row | One row: qty 1, condition `NearMint` |
| Second row (same file or append) | **Same row merged**: qty 2, condition **`LightPlayed`** |

On merge, quantity and trade quantity are **added**. Condition is **replaced** if the new CSV row has a non-empty `Condition` cell (last merged row wins). Both physical copies are counted in quantity, but only one condition value is kept.

The same merge applies within a single CSV file: duplicate `(Card Number, Rarity)` rows in one import are deduplicated in memory before insert, with the same overwrite rules.

### Where condition is stored vs used

| Area | Condition behavior |
|------|-------------------|
| Database | `collection_items.condition` column exists |
| API | Validated against canonical values in [`ygo_app/schemas.py`](ygo_app/schemas.py) (`NearMint`, `LightPlayed`, etc.) |
| CSV import | Reads `Condition` as-is; **no validation**; overwrites on merge when cell is non-empty |
| CSV export | Writes stored `condition` → `Condition` |
| My Collection UI | **Shown** in the table as a condition badge; **editable** in the edit modal |
| Card modal owned badges | Quantities aggregated by `(set_code, rarity_code)` only — condition ignored |
| Duplicate detection | `(set_code, rarity_code)` per user — condition not considered |

### User-visible symptoms

- Importing the same card twice with different conditions **increases quantity** and may **change the displayed condition** to the last imported value.
- Export shows only one `Condition` for what are physically different copies.
- Owned quantity on the card detail modal cannot distinguish Near Mint from Light Played copies.
- CSV abbreviations like `NM` or `LP` import without error but display as unknown badges until edited to canonical values (`NearMint`, `LightPlayed`).

### Workarounds (today)

- Use **one row** with `Quantity` set to the total copy count and pick the condition you care about most.
- Or leave `Condition` blank on import and set it manually in the app afterward.
- Or record the split in **Notes** (e.g. `1 NM, 1 LP`) — the app does not enforce this, but it preserves the information.

### Likely fix directions (not implemented)

These are design options for a future change; none are scheduled here.

1. **Include condition in the collection unique key** — `(user_id, set_code, rarity_code, condition)` so NM and LP are separate rows. Requires import merge rules, UI, and owned-badge aggregation updates.
2. **Keep single row but track condition quantities** — e.g. sub-counts per condition (heavier schema/UI).
3. **CSV alias normalization** — map `NM`/`LP`/etc. to canonical values on import (does not fix the merge/overwrite problem).

### Related docs

- [`docs/importing-physical-cards.md`](docs/importing-physical-cards.md) — documents that import matching uses **Card Number + Rarity** only; recommends collapsing duplicates with `Quantity`.
- [§1. Card edition (printing) is not a first-class dimension](#1-card-edition-printing-is-not-a-first-class-dimension) — same merge pattern for edition.
