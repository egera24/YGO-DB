# Design gaps and known issues

Documented limitations of the application design — behaviors that can surprise users or lose data fidelity. Use this when debugging collection imports, planning features, or scoping fixes.

**Last updated:** 2026-07-11

---

## Topic index

| Section | Topic | Status |
|---------|--------|--------|
| [1. Edition and condition as collection identity](#1-edition-and-condition-as-collection-identity) | Separate rows per edition/condition variant | **Resolved** (2026-07-11) |

---

## 1. Edition and condition as collection identity

**Status: Resolved** (2026-07-11)

Collection items are now keyed by:

- `user_id`
- `set_code` (card number, e.g. `LOB-EN005`)
- `rarity_code` (e.g. `UR`, `ScR`)
- `edition` (DragonShield **Printing**: Unlimited, 1st Edition, Limited Edition; empty → Unlimited)
- `condition` (empty → unset / one shared bucket)

Implementation: [`ygo_app/collection_identity.py`](ygo_app/collection_identity.py), CSV import in [`ygo_app/import_data.py`](ygo_app/import_data.py), API upsert in [`ygo_app/services.py`](ygo_app/services.py).

### Behavior

| Scenario | Result |
|----------|--------|
| Same printing + same edition + same condition | **Merge** — quantities summed on import append and UI add |
| Same printing, different edition | **Separate rows** |
| Same printing, different condition | **Separate rows** |
| Card modal owned badge | **Sums** total copies; shows variant count when multiple rows exist |

### My Collection UI

- **Edition** column in the table; editable in the edit modal.
- **Condition** column unchanged (badge + edit).

### Card modal

- Owned quantity is still the total across all variants.
- Click-to-edit works when exactly one variant row exists; multiple variants open My Collection filtered by set code.

### Existing data caveat

Rows already merged under the old `(set_code, rarity_code)` key are **not** auto-split. Re-import from DragonShield with **Overwrite**, or manually split rows in the UI.

Legacy **alias spellings** in the database (e.g. `Light Played` instead of `LightPlayed`) are normalized on API read and on new imports. Run [`python -m ygo_app.jobs.normalize_collection_variants`](ygo_app/jobs/normalize_collection_variants.py) once to persist canonical values and merge alias-duplicate rows.

### Related docs

- [`docs/importing-physical-cards.md`](docs/importing-physical-cards.md) — dedup key includes `Printing` and `Condition`.
- [`next_steps.md`](next_steps.md) §9 — append merge rules.
