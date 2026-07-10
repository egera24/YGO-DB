# Importing physical cards (manual entry)

A workflow for digitizing a large physical collection (10,000+ cards) into a CSV
you can import, without any scanning hardware or third-party tools.

## The one thing that makes this fast

The importer matches every row to the catalog using **only two fields**:

- **`Card Number`** - the set code printed on the card (bottom-right of the card
  frame), e.g. `25LP-EN001`, `LOB-EN005`.
- **`Rarity`** - the rarity code, entered plain (`UR`, `ScR`, `SR`, `C`, ...).

Everything else (card name, set name, prices, artwork) is filled automatically
from the catalog when the row matches. So you do **not** need to type card names,
set names, or prices - those columns are optional and any values you put in the
name/set columns are overridden by the catalog on a successful match. In
particular, **you never have to type the card name** - skip it.

That reduces manual entry to just four columns per card:
`Folder Name`, `Quantity`, `Card Number`, `Rarity`.

## Minimal CSV format

Use [`collection_import_template.csv`](collection_import_template.csv) as your
starting point. Header:

```csv
Folder Name,Quantity,Card Number,Rarity
AAA_COLLECTION,3,25LP-EN002,UR
AAA_COLLECTION,1,25LP-EN004,ScR
AAA_COLLECTION,2,LOB-EN005,UR
```

| Column        | Required?  | Notes                                                           |
| ------------- | ---------- | --------------------------------------------------------------- |
| `Card Number` | Yes        | Printed set code. Part of the match key.                        |
| `Rarity`      | Yes        | Plain rarity code (no parentheses). Part of the match key.      |
| `Quantity`    | Recommended| Defaults to 1 if blank. Use this to collapse duplicates.        |
| `Folder Name` | Optional   | Assigns the card to a collection folder. Blank = no folder.     |

> You do **not** need a card-name column. If you want an extra `Card Name` column
> as a personal sanity-check while typing, you can add one - but it's optional and
> gets overridden by the catalog on a successful match.

> The two match columns matter because a card is looked up by the exact pair
> `(Card Number, Rarity)`. Get the set code and rarity right and the rest sorts
> itself out.

## Step-by-step workflow

### 1. Sort the physical cards first

Sort by **set**, then by **collector number** within each set. This is the single
biggest time saver: cards from the same set share a prefix (e.g. everything in
`LOB-EN###`), so in a spreadsheet you fill the prefix down a column once and only
type the changing number.

### 2. Collapse duplicates with `Quantity`

Do not create one row per physical card. If you have 3 copies of the same card in
the same set and rarity, enter **one** row with `Quantity` = 3. A 10,000-card box
is usually far fewer than 10,000 rows once duplicates are combined.

### 3. Type only the changing fields

For each unique (set code, rarity) card:

- Fill-down `Folder Name` and the set prefix across the batch you're working on.
- Type the collector number and the rarity code.
- Set `Quantity` for the number of copies.

Spreadsheet tips (Excel / Google Sheets / LibreOffice):

- Freeze the header row so it stays visible.
- Select a cell and drag the fill handle to copy `Folder Name` / prefix down.
- If you keep the set prefix in its own helper column, build `Card Number` with a
  formula like `=A2&"-EN"&B2`, then paste-as-values before exporting.
- Save/export as **CSV UTF-8** so accented card names survive.

### 4. Rarity code cheat-sheet

Enter the rarity **plain** - the importer wraps it internally, so type `UR`, not
`(UR)`.

| Code    | Rarity                              |
| ------- | ----------------------------------- |
| `C`     | Common                              |
| `R`     | Rare                                |
| `SR`    | Super Rare                          |
| `UR`    | Ultra Rare                          |
| `ScR`   | Secret Rare                         |
| `UtR`   | Ultimate Rare                       |
| `GR`    | Ghost Rare                          |
| `SP`    | Short Print                         |
| `PlScR` | Platinum Secret Rare                |
| `PScR`  | Prismatic Secret Rare               |
| `DUPR`  | Duel Terminal Ultra Parallel Rare   |
| `QCScR` | Quarter Century Secret Rare         |

The importer recognizes common abbreviations from DragonShield, YGOProDeck, and
other portals. For example, `SP` matches catalog rows stored as Short Print, and
`QCScR` matches `QCSR` / `QCR` variants.

If a rarity is rejected:

- `Unknown rarity '…'` — the abbreviation is not in the registry yet.
- `Rarity '…' (Full Name) not found for set code '…'` — the abbreviation is known
  but that printing is missing from the catalog (sync or Yugipedia import may be
  needed).

### Adding new portal abbreviations

Edit [`ygo_app/data/rarity_aliases.json`](../ygo_app/data/rarity_aliases.json)
and add an entry mapping the alias to the canonical rarity name:

```json
{
  "aliases": [
    { "alias": "NEWCODE", "canonical_name": "Grand Master Rare" }
  ]
}
```

Canonical names and codes are defined in the app's rarity registry (aligned with
Cardmarket rarity tiers). After adding aliases, restart the app (or re-run import)
so the registry reloads.

> **Note:** `PScR` (Prismatic Secret Rare) and `PlScR` (Platinum Secret Rare) are
> different rarities — do not interchange them.

## Importing the CSV

You can import the same file two ways.

### Option A - In the app (recommended)

1. Go to **Collection > Import CSV**.
2. **Turn the "replace" toggle OFF** so the import **appends/merges** into your
   existing collection instead of replacing it. This is what lets you enter cards
   in batches over many sessions.
3. Upload the file and watch the progress bar.

### Option B - Command line

```powershell
python -m ygo_app.import_data --collection path\to\file.csv --skip-cards --user-id N
```

- `--skip-cards` imports only the collection (leaves the card catalog untouched).
- `--user-id N` is the account the cards belong to.

## Batch strategy for 10,000+ cards

Do not try to enter everything into one giant file. Instead:

1. Work **one set or one box at a time**.
2. Import each batch in **append mode** (replace OFF).
3. This keeps progress incremental, keeps the reject list small and easy to fix,
   and means a mistake never risks your whole collection.

## Fixing rejected rows

Rows that don't match are returned as a **rejected CSV** with an extra
`Import Error` column explaining why, for example:

- `Set code 'XXX-EN000' not found in catalog` - the set code is mistyped or the
  set isn't in the catalog yet.
- `Unknown rarity 'ZZZ'` — abbreviation not recognized; add it to
  `ygo_app/data/rarity_aliases.json` or fix the CSV.
- `Rarity 'UR' not found for set code 'XXX-EN000'` — the set code is right but the
  rarity is wrong for that printing, or the printing is missing from the catalog.

Workflow:

1. Download/save the rejected CSV.
2. Fix the `Card Number` or `Rarity` in those rows.
3. Delete the `Import Error` column (optional) and re-import in **append mode**.
4. Repeat until the reject file is empty.

## Edge cases to watch for

- **Old or OCG cards without an English set code** may not match by `Card Number`.
  Check whether the printing exists in the catalog before spending time on them.
- **Rarity is part of the key**, so the same card in a different rarity is a
  different row. When in doubt, confirm the exact rarity in the app.
- **The match is exact on `(Card Number, Rarity)`** after alias resolution — trailing
  spaces or wrong casing on an unrecognized rarity code can cause a reject.
- **Alternate-art suffixes** from DragonShield or Cardmarket (e.g. `LCKC-EN001b`,
  `RA05-EN110_v1`, `RA04-EN108-8`) are resolved to the Yugipedia catalog set code
  when the suffix is a known alt-art marker and the rarity matches. The stored
  collection key uses the catalog set code (e.g. `LCKC-EN001`), not the suffixed
  export value.

## Normalizing existing database rarity codes

If catalog rows were imported before alias support (e.g. stored as `(Short Print)`
instead of `(SP)`), run:

```powershell
python -m ygo_app.jobs.normalize_rarity_codes
```

Use `--dry-run` to preview how many rows would change.
