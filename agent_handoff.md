# Agent handoff — YGO Collection & Deck Builder

> **For the next agent.** Read this first for token-efficient context instead of replaying chat history.
> Keep it current when architecture, deploy, or conventions change. Body stays **timeless**; put dated work in [§9 Changelog](#9-changelog).
>
> **Last updated:** 2026-06-23

---

## 1. TL;DR

| | |
|------|--------|
| **What** | Browser UI + FastAPI API for Yu-Gi-Oh! card search, per-user owned collection (set code + rarity), decks, favorites, tags, **named search presets**. **My Collection** tab for browse/edit; Search **Owned only** + header CSV import/export. |
| **Stack** | Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic 2 · Alembic · static HTML/JS · BeautifulSoup + cloudscraper (scrape) · JWT auth (bcrypt). |
| **Run locally** | `pip install -r requirements.txt` → `alembic upgrade head` → `python run.py` (opens browser; API docs at `/docs`). |
| **Test** | `python -m unittest discover -s tests` |
| **DB** | PostgreSQL on **Neon** (pooled URL, `sslmode=require`). Falls back to SQLite `data/ygo.db` only when `DATABASE_URL` is unset. **Not** Render Postgres. |
| **Catalog source** | **Yugipedia** scrape (primary) → JSON → Neon. YGOProDeck API = emergency fallback only. |
| **Card images** | **Cloudflare R2 mirror** (WebP, `IMAGE_BASE_URL` URLs in DB) with `ms.yugipedia.com` fallback for unmirrored cards (see [§5](#5-card-images)). |
| **Deeper docs** | [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md) · [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md) · [`docs/DEPLOY_FREE.md`](docs/DEPLOY_FREE.md) · [`README.md`](README.md) |

**Recommended local setup:** point `.env` `DATABASE_URL` at the Neon **dev** branch with `ENV=production` for prod parity (see [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md)).

---

## 2. Guardrails — do NOT do without explicit user ask

- **Do not** commit `.env`, secrets, or `data/catalog/*.json` (all gitignored).
- **Do not** manually truncate/delete Neon `cards` / `printings` — the import job replaces them safely (see [§4](#4-catalog-pipeline)).
- **Do not** run the Yugipedia GHA workflow from branch **`main`** before `ygo_app/yugipedia/` exists on `main`.
- **Do not** edit `import-catalog-yugipedia.yml` on one branch without syncing the other (see [§6](#6-environments--deploy)). Enforced by [`.cursor/rules/github-actions-yugipedia-workflow-sync.mdc`](.cursor/rules/github-actions-yugipedia-workflow-sync.mdc).
- **Do not** run `yugipedia/get_images.py` — legacy script that *downloaded* from YGOProDeck; real images come from the scrape (see [§5](#5-card-images)).
- **Do not** use Render free Postgres; **do not** edit `.cursor/plans/*.plan.md`.

---

## 3. Environments & branches

Three tiers — local, staging, production. Full workflow: [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md).

| Tier | Git branch | Render service | Neon branch | DB env var |
|------|------------|----------------|-------------|------------|
| **Local** | any | — (`python run.py`) | **dev** | `DATABASE_URL` in `.env` |
| **Staging** | `develop` | `ygo-app-dev` | **dev** | `DATABASE_URL_DEV` (GHA) |
| **Production** | `main` | `ygo-app` | **main** | `DATABASE_URL` (GHA `environment=production`) |

**Branches intentionally diverge.** Full app code (`ygo_app/yugipedia/`, jobs, tests) typically lives on `develop`; `main` may carry only workflow YAML (+ the `import_data.py` FK fix) until a deliberate merge. This enables "test on dev without merging app to prod."

---

## 4. Catalog pipeline

```mermaid
flowchart TB
  subgraph scrape [Scrape - ephemeral]
    Wiki[Yugipedia API + wiki pages] --> JSON["data/catalog/*.json"]
  end
  subgraph gha [GitHub Actions - chained jobs]
    P[prepare] --> PC[passcodes] --> B0[scrape_batch_0..5] --> IMG[images] --> IM[import]
    PC --> Art["artifact catalog-state"]
    B0 --> Art --> IM
    IMG --> Man["artifact images-manifest"] --> IM
  end
  IMG --> R2[(R2 bucket)]
  subgraph neon [Neon Postgres]
    Cards[cards + printings]
  end
  subgraph render [Render]
    DevWeb["ygo-app-dev <- develop"]
    ProdWeb["ygo-app <- main"]
  end
  JSON --> IM --> Cards
  DevWeb --> Cards
  ProdWeb --> Cards
  Browser --> DevWeb
  Browser --> ProdWeb
  Browser --> CDN["IMAGE_BASE_URL (R2 public domain)"]
```

**Stages** (orchestrator: `python -m ygo_app.jobs.scrape_yugipedia_catalog --full`; supports `--details-only --resume`):

| Step | Module / job | Output |
|------|----------------|--------|
| 1 | [`yugipedia/passcodes.py`](ygo_app/yugipedia/passcodes.py) | `data/catalog/yugipedia_passcode_list.json` (all `Concept:CG cards`) |
| 2 | [`yugipedia/details.py`](ygo_app/yugipedia/details.py) + [`parsing.py`](ygo_app/yugipedia/parsing.py) | `yugipedia_all_cards.json` (metadata + `image_url`/`image_url_small`); `yugipedia_rejected_cards.json` |
| 2b | [`jobs/scrape_yugipedia_set_chronology.py`](ygo_app/jobs/scrape_yugipedia_set_chronology.py) | `yugipedia_set_chronology.json` → upsert `tcg_sets` |
| 2c | [`jobs/scrape_yugipedia_supplements.py`](ygo_app/jobs/scrape_yugipedia_supplements.py) | merges `errata` + `tips` into `yugipedia_all_cards.json` |
| 3 | [`jobs/import_catalog_yugipedia.py`](ygo_app/jobs/import_catalog_yugipedia.py) + [`card_import.py`](ygo_app/yugipedia/card_import.py) (+ [`adapter.py`](ygo_app/yugipedia/adapter.py) for images/legacy fields) | Neon `cards` + `printings` + `card_errata_versions` |

**Key behaviors:**

- **Import = full replace.** `import_cards_entries` deletes all `cards` + `printings`, then reloads from JSON. Never truncate manually.
- **Import side effects.** `users` / `collection_items` are kept; deleting `cards` cascades **favorites**, **tags**, **deck_cards**. [`import_data.py`](ygo_app/import_data.py) detaches `collection_items.printing_id` before the delete, then re-links by `(set_code, rarity_code)` after import (avoids FK violation on `printings`).
- **TCG-only filter.** Cards with no English printings (empty/missing `cts--EN` → no `card_sets`) are rejected in [`details._process_card`](ygo_app/yugipedia/details.py) and skipped in [`card_import.yugipedia_entries_to_import`](ygo_app/yugipedia/card_import.py). OCG-only entries land in `yugipedia_rejected_cards.json`. Final card count is **below** the ~14k passcode total.
- **Schema vs data.** **Alembic** (`alembic upgrade head`) adds/updates table columns only. **Import** fills card rows. After new `cards` columns (e.g. migration `003`), run a **full re-import** on that DB — GHA `prepare` already runs Alembic; workflow YAML need not change.
- **Multi-rarity printings.** [`card_sets.py`](ygo_app/yugipedia/card_sets.py) reads all `<a>` tags in the rarity cell (not `<br>` split), English timeline table only (`id` contains `cts--EN`). E.g. `RA03-EN172` yields multiple rarities.
- **No search index rebuild** on import (FTS removed — see [§7](#7-card-search)).

**Row model:** `cards` = one row per card, `id` = 8-digit Yugipedia passcode. `printings` = one row per (set code + rarity), FK `card_id → cards.id`.

**Where data lives:**

| Stage | Location | In git? | Lifetime |
|-------|----------|---------|----------|
| Scrape JSON | `data/catalog/*.json` | No (gitignored) | Ephemeral on runner; local until deleted |
| GHA backup | Artifact `yugipedia-catalog-<run_id>` | No | 14 days (`retention-days: 14`) |
| Row data | Neon `cards` + `printings` | N/A | Permanent (dev or main branch per `DATABASE_URL`) |

### GHA scrape resilience & signals

Chained jobs each have a 60–90 min timeout; full run is **~2–4 h** wall clock, **~30–60 min** in `test_mode`. Artifact `catalog-state` passes JSON between jobs. `PYTHONUNBUFFERED=1` is set.

| Layer | Behavior | Source |
|-------|----------|--------|
| HTTP | 5× retry per card; `[WARN]` on slow/Cloudflare/retryable errors | [`http_client.py`](ygo_app/yugipedia/http_client.py) |
| Pool | Max 8 in-flight; 240s idle → re-queue | [`details.py`](ygo_app/yugipedia/details.py) |
| Batch | Up to 2 `[BATCH_RETRY]` rounds (`FAILED_RETRY_ROUNDS` in [`constants.py`](ygo_app/yugipedia/constants.py)) | |
| Stall | `[HEARTBEAT]` every 60s; warn at 120s idle; abort at 600s → exit 2 | [`scrape_progress.py`](ygo_app/yugipedia/scrape_progress.py) |

- **Logs to watch:** `[HEARTBEAT]`, `[FAIL] will-retry\|final`, `[BATCH_RETRY]`, `[BATCH_RESULT] expected=… saved=… rejected=… missing=…`. **Every active batch job must end with `missing=0`.**
- **CLI exit codes** ([`scrape_yugipedia_catalog.py`](ygo_app/jobs/scrape_yugipedia_catalog.py)): `0` ok · `1` config/file · `2` stall (re-run `--resume`) · `3` batch incomplete (`BatchIncompleteError`, job fails).
- `The operation was canceled` usually = per-job timeout, **not** a Python exception.

---

## 5. Card images

Scrape finds Yugipedia art URLs; a GHA `images` job mirrors them as WebP to a **Cloudflare R2** bucket (S3 API, vendor-portable); import writes mirrored URLs into the DB with Yugipedia fallback.

**Mirror scheme:** keys `cards/{passcode}.webp` (full, quality 82) + `cards/{passcode}-small.webp` (150px), `Cache-Control: immutable`. Served from `IMAGE_BASE_URL` (r2.dev subdomain or custom domain). `data/catalog/images_manifest.json` lists mirrored passcodes (artifact `images-manifest` in GHA). Bucket/credentials via `S3_ENDPOINT_URL` / `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` / `S3_BUCKET` (boto3, `region_name="auto"`). Migration to another S3 vendor = `rclone sync` + change `S3_*`/`IMAGE_BASE_URL` + re-import.

| Piece | Role |
|-------|------|
| [`parsing.extract_card_image`](ygo_app/yugipedia/parsing.py) | Picks largest card-art `<img>` on `ms.yugipedia.com` from the same page fetch as metadata; skips `noviewer`, `.svg`, UI/attribute icons |
| [`images.py`](ygo_app/yugipedia/images.py) | Thumb → full URL normalization; 150px small thumb. `image_urls_for_passcode()` is **only** for the YGOProDeck API fallback |
| [`jobs/sync_card_images.py`](ygo_app/jobs/sync_card_images.py) | Mirror job: lists bucket, downloads missing art (rate-limited cloudscraper, 3 req/s), WebP via Pillow, uploads via boto3, writes manifest. Flags: `--limit`, `--force`, `--workers` (default 6), `--manifest-only` (rebuild manifest from bucket listing, used by `import_only`). **Incremental** — safe to re-run; full `--force` remirror ~1.5–2h with 6 workers |
| [`image_mirror.py`](ygo_app/image_mirror.py) | Vendor-neutral keys/URLs, manifest load/save, `rewrite_image_urls()` (mirrored pid + `IMAGE_BASE_URL` set → bucket URLs, else original) |
| [`adapter._resolve_images`](ygo_app/yugipedia/adapter.py) | Maps scrape JSON → `card_images`, then applies `rewrite_image_urls`; **no** YGOProDeck CDN fallback (null if scrape found no art) |
| Browser ([`app.js`](ygo_app/static/js/app.js)) | Loads `image_url`/`image_url_small`; shows `IMG_PLACEHOLDER` when null |

- **No manifest / no secrets → graceful fallback:** the `images` job skips itself when `S3_BUCKET` is unset and import keeps Yugipedia URLs. URL changes require a **re-import** (URLs live in `cards` rows).
- Tests: `test_image_mirror.py`, `test_sync_card_images.py`.

JSON shape per card in `yugipedia_all_cards.json`:

```json
{
  "id": "85087012",
  "name": "Card Trooper",
  "image_url": "https://ms.yugipedia.com//6/65/CardTrooper-25YC-EN-SR-LE.png",
  "image_url_small": "https://ms.yugipedia.com//thumb/6/65/CardTrooper-25YC-EN-SR-LE.png/150px-CardTrooper-25YC-EN-SR-LE.png"
}
```

- **Re-scrape required** for any DB/JSON created before this scheme — old rows have YGOProDeck URLs or null images until details scrape + import re-run.
- The **YGOProDeck fallback** (`python -m ygo_app.jobs.import_catalog`) still uses `images.ygoprodeck.com`.

---

## 6. Card search

### Text (`q` on `/api/cards/search`)

Google-style query → case-insensitive `ILIKE` on `name` / `desc` / `archetype` via [`search_query.py`](ygo_app/search_query.py) (`Phrase`, `Term`, `And`, `Or`, `Not`, `?`, `*`). All-digit `q` → passcode only. Help: `#search-help-modal` + `?` button. Invalid syntax → plain term. FTS/`cards_fts` removed.

### Yugipedia filters (advanced panel in UI)

Stored on `cards` from scrape JSON via [`card_import.py`](ygo_app/yugipedia/card_import.py) (migration [`003_yugipedia_card_fields.py`](alembic/versions/003_yugipedia_card_fields.py)):

| UI / API | DB / scrape | Notes |
|----------|-------------|--------|
| Category | `category` | `Spell`/`Trap`/`Skill` from JSON `type`, else `Monster` |
| Type | `types` (JSON array) | Monsters: `typeline[]`; ST/Skill: `[property]` — filter **OR** |
| Mechanic, Attribute | `mechanic`, `attribute` | Monsters only; multi-value **OR** |
| Archetype | `archetype` | Substring `ILIKE` |
| ATK/DEF/Level/Rank/Link/Pendulum | matching columns | Inclusive min/max query params; UI uses `<select>` for Level/Rank/Link/Pendulum, number inputs for ATK/DEF |
| Link markers (3×3 grid) | `link_markers` (JSON) | Selected markers **AND** (subset match) |
| Summoning condition | `summoning_condition` | `ILIKE`; autocomplete `GET /api/cards/summoning-suggestions` |

| Piece | Role |
|-------|------|
| [`card_filters.py`](ygo_app/card_filters.py) | JSON list parse; `types` / `link_markers` SQL helpers |
| [`services.search_cards`](ygo_app/services.py) | `q` + all filter params; one `COUNT` query |
| [`meta.filters`](ygo_app/api/routes/meta.py) | `GET /api/filters` — catalog options **require auth**; `folders[]` = distinct folder names for the logged-in user (legacy; My Collection uses `/api/collection/stats` instead) |
| UI | Tabs: **Search**, **My Collection**, **Decks** (visible only when logged in). Unauthenticated visitors see a login/register landing page; no catalog API calls until JWT is valid. [`app.js?v=47`](ygo_app/static/js/app.js) — hash routing, preset toolbar, `initStatRangeSelects()`, `loadCollectionView()` / folder sidebar / paginated table. Header **Import/Export my collection**. Static [`style.css?v=36`](ygo_app/static/css/style.css). |

**Advanced panel layout (static/CSS):** Category–Attribute = compact multi-selects (`.filter-group--compact`). Level/Rank/Link/Pendulum = min/max `<select>` (options from `initStatRangeSelects()`; Level 1–12, Rank 1–13, Link 1–6, Pendulum 0–13). ATK/DEF = number inputs. Stat fieldsets in `.filter-ranges` (flex wrap, `gap: 1.5rem`, `width: fit-content`). Bump `style.css` / `app.js` `?v=` in `index.html` after static edits.

Legacy `frame_type` / `race` columns remain for YGOProDeck fallback import; **not** exposed in search UI.

Tests: `test_search_query.py`, `test_search_cards.py`, `test_search_yugipedia_filters.py`, `test_summoning_suggestions.py`, `test_yugipedia_card_import.py`, `test_search_presets.py`, `test_api_auth.py`.

### Search presets (logged-in, Search tab only)

**Data model:** `search_presets` — one row per user per unique `name`; `params` = JSON object mirroring `/api/cards/search` query keys from `buildSearchParams()` (no pagination). Migration [`004_search_presets.py`](alembic/versions/004_search_presets.py). Cascade delete with user.

| Piece | Role |
|-------|------|
| **Save / load** | `#search-presets-bar` — dropdown + Save + ⋯ menu (Rename / Delete); no Clear button (hidden when logged out) |
| **Serialize** | `buildSearchParams()` → snapshot; `applySearchParams()` restores DOM + `runSearch()` |
| **Edit workflow** | Load preset → edit filters → **Save** → modal asks `Update "{name}" or save as a new preset?` → **Update preset** or **Save as new** |
| **New preset** | No selection → name prompt; duplicate name → confirm → POST with `overwrite: true` |

**Search presets API** ([`api/routes/search_presets.py`](ygo_app/api/routes/search_presets.py)) — all require auth:

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/search-presets` | List presets (includes `params` for client load) |
| POST | `/api/search-presets` | Body `{ name, params, overwrite? }`; **409** if name exists and `overwrite=false` |
| PATCH | `/api/search-presets/{id}` | Update `name` and/or `params`; **409** on rename conflict |
| DELETE | `/api/search-presets/{id}` | Remove preset |

Param allowlist validated in [`schemas.py`](ygo_app/schemas.py) (`SEARCH_PRESET_PARAM_KEYS`). CRUD in [`services.py`](ygo_app/services.py) (`SearchPresetConflictError` on duplicate name).

**Out of scope:** My Collection tab filters; API-only `tag` param (no UI).

### User collection (owned)

**Data model:** `collection_items` — one row per user per `(set_code, rarity_code)` with quantity, condition, edition, language, notes, prices. **`collection_folders`** + **`collection_item_folders`** (split qty per folder; `folder_id NULL` = No Folder). Optional `printing_id` FK → `printings`. Migration `005`.

**Physical folders:** `collection_folders` entity + `collection_item_folders` junction (split qty per folder). Sidebar filters by folder id or `folder=__no_folder__` (`NO_FOLDER` in [`services.py`](ygo_app/services.py)) for allocations with `folder_id IS NULL`. UI: **+ New folder**, double-click rename, delete (moves copies to No Folder). Per-row multi-folder picker with qty split validation (All view only). Inside a folder view the Folder column is hidden (`collection-table--in-folder` class) and each row gets **Move** / **Copy** buttons next to Delete: Move reallocates up to the per-folder quantity to another folder (total unchanged); Copy raises total quantity and allocates the new copies to the target folder. Both are client-side via the existing `PATCH /api/collection/{id}` (`quantity` + `folder_allocations`); popover `openMoveCopyPopover()` in `app.js`.

| Piece | Role |
|-------|------|
| **Owned filter** | `owned_only` on `GET /api/cards/search` — join `collection_items` ↔ `printings` on set code **and** rarity |
| **My Collection tab** | `#view-collection` — folder sidebar, stats bar, search/set-code/sort toolbar, paginated table (100/page), read-only Quantity column, per-row **Edit** modal (Set/Rarity from card printings, Quantity, fixed 7-value DragonShield Condition list), inline folder edit, delete, row click → card modal |
| **CSV import** | Header **Import my collection** → `POST /api/collection/import-csv` (NDJSON + `#import-progress`). DragonShield via [`import_collection_csv`](ygo_app/import_data.py). `replace=true` wipes user rows first |
| **CSV export** | Header **Export my collection** → modal → `GET /api/collection/export-csv?format=dragonshield`. [`collection_export.py`](ygo_app/collection_export.py) round-trips with import |
| **Matching** | `_match_printing`: row must match `printings` or **rejected**; `done` includes `rejected_csv` |
| **Manual add** | Card modal **Add to collection** → `POST /api/collection` |

**Collection API** ([`api/routes/collection.py`](ygo_app/api/routes/collection.py)):

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/collection` | Paginated `{ items, total, limit, offset }`. Query: `q`, `folder`, `set_code`, `sort` (`set_code`\|`card_name`\|`folder_name`\|`quantity`) |
| GET | `/api/collection/stats` | Totals + `folders[]` (with `id`) + `no_folder_count` / `no_folder_quantity` |
| GET/POST/PATCH/DELETE | `/api/collection/folders` | Folder CRUD; delete moves allocations to No Folder |
| GET | `/api/collection/export-formats` | List export format ids |
| GET | `/api/collection/export-csv` | DragonShield CSV download |
| POST | `/api/collection` | Add single row |
| PATCH | `/api/collection/{id}` | Update qty, folder, condition, notes, etc. |
| DELETE | `/api/collection/{id}` | Remove row |
| POST | `/api/collection/import-csv` | NDJSON stream |

**`list_collection`** ([`services.py`](ygo_app/services.py)): `joinedload(CollectionItem.linked_printing).joinedload(Printing.card)` + batched `_cards_by_set_codes` fallback for rows missing `printing_id`. Returns `rarity_display` per row. **No per-row N+1.**

Progress throttle: [`import_progress.py`](ygo_app/import_progress.py).

Tests: [`test_import_collection_csv.py`](tests/test_import_collection_csv.py), [`test_export_collection_csv.py`](tests/test_export_collection_csv.py), [`test_list_collection.py`](tests/test_list_collection.py), [`test_collection_stats.py`](tests/test_collection_stats.py), [`test_collection_folder_rename.py`](tests/test_collection_folder_rename.py).

---

## 7. GitHub Actions & deploy

| Workflow | UI name | Notes |
|----------|---------|-------|
| [`import-catalog-yugipedia.yml`](.github/workflows/import-catalog-yugipedia.yml) | Import Yugipedia catalog | `prepare → passcodes → scrape_batch_0..5 → images → import`; `BATCH_COUNT=6`; inputs `test_mode` + `card_limit` (default 500); **environment** `dev`\|`production`; scheduled 1st & 15th → prod. `images` mirrors card art to R2 (skips without `S3_BUCKET` secret; import tolerates its failure) |
| [`import-catalog-ygoprodeck.yml`](.github/workflows/import-catalog-ygoprodeck.yml) | Import YGO catalog (YGOProDeck fallback) | Manual emergency only |
| [`import-cardmarket-prices.yml`](.github/workflows/import-cardmarket-prices.yml) | Import Cardmarket prices | **Import only** — downloads `catalog/cardmarket_prices.json` from R2, upserts `printing_market_prices`. Scrape runs **locally** (Cardmarket blocks datacenter IPs). `workflow_dispatch` + `environment` `dev`\|`production` |
| [`db-keepalive.yml`](.github/workflows/db-keepalive.yml) | Neon DB keep-alive | Both secrets |

- Workflows only appear in the Actions UI when present on the **default branch (`main`)**. Running with branch `develop` uses **code from `develop`** (must include `ygo_app/yugipedia/`).
- `test_mode` (workflow_dispatch): `--max-cards` on scrape, `--limit` on import; **dev only** (blocked on production); the `import` job uses `always()` so it runs even when batches 1–5 are skipped. Use **Run workflow** (new run) — **Re-run failed jobs** reuses the old commit and breaks fixes.
- `import-catalog-yugipedia-dev.yml` is optional/not required — use the main workflow with branch `develop` + environment `dev`.

**Workflow YAML must be identical on `main` and `develop`.** Sync without full-merging app code:

```powershell
git fetch origin
git checkout main && git pull origin main
git checkout origin/develop -- .github/workflows/import-catalog-yugipedia.yml
git commit -m "ci: sync Yugipedia import workflow from develop"
git push origin main
git checkout develop
# verify in sync (no output = synced):
git diff origin/main origin/develop -- .github/workflows/import-catalog-yugipedia.yml
```

This does **not** redeploy prod app code — Render `ygo-app` only rebuilds when `main` `ygo_app/` files change. Deploy assets: [`render.yaml`](render.yaml), [`docs/DEPLOY_FREE.md`](docs/DEPLOY_FREE.md).

---

## 8. Commands & env vars

### Run / test
```powershell
pip install -r requirements.txt
alembic upgrade head                            # schema only (see §4: re-import fills new columns)
python run.py                                   # local app (SQLite if DATABASE_URL unset)
python -m unittest discover -s tests            # full test suite
python -m ygo_app.import_data --skip-cards --collection my_collection.csv --user-id 1   # CLI collection import
```

### Catalog — full vs 500-card test

| Mode | Scrape | Import | Result on Neon |
|------|--------|--------|----------------|
| **Full** | 6 GHA batches, or `--full` locally | replaces entire catalog | ~14k cards (TCG-printed) |
| **Test** | `--max-cards 500` / GHA `test_mode` | `--limit 500` (min ~400 mapped) | **dev only**, ends at ~500 until a full import |

```powershell
# Full local catalog (.env DATABASE_URL = Neon dev)
python -m ygo_app.jobs.scrape_yugipedia_catalog --full
python -m ygo_app.jobs.import_catalog_yugipedia

# 500-card test on Neon dev
python -m ygo_app.jobs.scrape_yugipedia_catalog --passcodes-only --max-cards 500
python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only --resume --batch-index 0 --batch-count 1
python -m ygo_app.jobs.import_catalog_yugipedia --limit 500

# YGOProDeck emergency fallback
python -m ygo_app.jobs.import_catalog
```

### Cardmarket prices (local scrape → R2 → GHA import)

Cardmarket blocks cloud/datacenter IPs (HTTP 403/429 / Cloudflare Error 1015). **Scrape only on your PC** in four steps; import via R2 + GHA or direct local import. Rate-limit reference: [`docs/cloudflare/README.md`](docs/cloudflare/README.md); browser scraper behavior: [`docs/cloudflare/cardmarket-scraper-behavior.md`](docs/cloudflare/cardmarket-scraper-behavior.md).

Default HTTP backend is **`curl_cffi`** (Chrome TLS impersonation) when installed; falls back to `cloudscraper`. Optional `CARDMARKET_HTTP_PROXY` in `.env` for a residential proxy (`http://user:pass@host:port`). Use **`--polite`** for recommended browser pacing (~0.12 discovery RPS).

One-time Playwright setup (for `--backend playwright` when rate-limited): `pip install -r requirements.txt` then `python -m playwright install chromium`.

```powershell
# 1. Scrape Cardmarket (full TCG catalog; step 4 needs yugipedia_all_cards.json)
python -m ygo_app.jobs.scrape_cardmarket_expansions --cf-login   # one-time Cloudflare
python -m ygo_app.jobs.scrape_cardmarket_expansions --polite
python -m ygo_app.jobs.scrape_cardmarket_card_list --browser --headed --polite --resume
python -m ygo_app.jobs.scrape_cardmarket_card_details --polite --resume
python -m ygo_app.jobs.export_cardmarket_prices

# Dev test: --limit 5 on jobs 2–3, --limit 500 on export
python -m ygo_app.jobs.scrape_cardmarket_card_list --polite --limit 5
python -m ygo_app.jobs.scrape_cardmarket_card_details --polite --limit 5
python -m ygo_app.jobs.export_cardmarket_prices --limit 500

# After IP ban: wait, then resume slower (--discovery-rps 0.08)
python -m ygo_app.jobs.scrape_cardmarket_card_list --browser --headed --polite --resume --discovery-rps 0.08

# 2a. Upload to R2 (S3_* in .env), then GHA "Import Cardmarket prices"
python -m ygo_app.jobs.upload_cardmarket_prices

# 2b. Dev shortcut — import directly (DATABASE_URL = Neon dev)
python -m ygo_app.jobs.import_cardmarket_prices --file data/catalog/cardmarket_prices.json

# Incremental update (after initial full scrape — new expansions / ID migrations only)
python -m ygo_app.jobs.scrape_cardmarket_incremental --polite
python -m ygo_app.jobs.upload_cardmarket_prices
python -m ygo_app.jobs.import_cardmarket_prices --file data/catalog/cardmarket_prices.json
```

Artifacts under `data/catalog/`: `cardmarket_expansion_list.json`, `cardmarket_card_list.json`, `cardmarket_card_details.json`, checkpoints, export `cardmarket_prices.json`, incremental `cardmarket_incremental_report.json` / `cardmarket_incremental_conflicts.json`. R2 key: `catalog/cardmarket_prices.json` (private). `expansion_seed.json` auto-regenerates after job 2.

### GHA from CLI
```powershell
gh workflow run "Import Yugipedia catalog" --ref develop -f environment=dev
gh workflow run "Import Yugipedia catalog" --ref develop -f environment=dev -f test_mode=true -f card_limit=500
gh workflow run "Import Cardmarket prices" --ref develop -f environment=dev
```
> Test on dev without touching prod: **Run workflow** (not Re-run) → branch `develop` → `environment=dev`. After a test run, do a full import to restore ~14k cards on dev.

### Git (typical promotion)
```powershell
git checkout develop          # work, push → staging deploy
git checkout main && git merge develop && git push   # promote app to prod
```

### Environment variables

| Variable | Local | Render / GHA |
|----------|-------|--------------|
| `DATABASE_URL` | Neon **dev** (`.env`) | Render `ygo-app` (prod) · GHA `environment=production` |
| `DATABASE_URL_DEV` | — | GHA `environment=dev` |
| `DATABASE_URL_MIGRATIONS` | optional direct Neon URL (no `-pooler`) | optional; overrides auto strip of `-pooler` in [`database_url_for_migrations()`](ygo_app/config.py) |
| `ENV` | `production` (parity) or unset → SQLite | `production` |
| `SECRET_KEY` | any local value | per Render service |
| `EMAIL_BACKEND` | `console` (OTP in terminal) | `brevo` |
| `BREVO_API_KEY` / `EMAIL_FROM` | optional | Brevo API key + verified sender |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | optional | optional bot protection on register |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` / `S3_BUCKET` | optional in `.env` for local image sync | GHA repo secrets (image mirror; job skips when unset) |
| `IMAGE_BASE_URL` | optional (import-time URL rewrite) | GHA repo secret (import jobs); **not** needed on Render |
| `CARDMARKET_HTTP_PROXY` | optional residential proxy for local Cardmarket scrape | not used on Render/GHA |

**Alembic on Neon:** [`alembic/env.py`](alembic/env.py) uses `database_url_for_migrations()` (direct host when pooled URL is set) and **`connection.commit()`** after `run_migrations()` so DDL + `alembic_version` persist. Without commit, `alembic upgrade head` can log success but leave Neon at the old revision. Verify with `alembic current` or `SELECT version_num FROM alembic_version`.

**GitHub secrets must be the raw Neon pooled URL only** — `postgresql://user:pass@ep-xxx-pooler.../neondb?sslmode=require`. No quotes, no `DATABASE_URL=` prefix, no whitespace. [`config.py`](ygo_app/config.py) `_normalize_database_url()` strips these defensively, but fix the secret at the source.

---

## 9. Changelog

Recent work, newest first. Keep the body above timeless; record dated changes here.

**2026-06-23**
- **Cardmarket incremental scrape** — `scrape_cardmarket_incremental` orchestrator and `--incremental` on jobs 1–4: diff live expansion list, scrape new/migrated expansion IDs only, merge card list + details with validation (`duplicate_card_id`, `duplicate_printing_key`, `duplicate_match_key`, `ambiguous_migration`), export full `cardmarket_prices.json`. Artifacts: `cardmarket_incremental_report.json`, `cardmarket_incremental_conflicts.json`.
- **Cardmarket checkpoint + pacing** — job 2 checkpoints every **5** expansions (was 50) with Ctrl+C save; job 3 every **5** cards (was 100). Browser inter-request delay **2–8 s** centralized in `fetch_url` (was 3–6 s at call sites only).
- **Cardmarket scraper rate-limit docs** — new [docs/cloudflare/cardmarket-scraper-behavior.md](docs/cloudflare/cardmarket-scraper-behavior.md): browser request flow, console output (`[FETCH] OK` vs expansion summary), pagination, IP vs profile pool, troubleshooting. Cross-links in [docs/cloudflare/README.md](docs/cloudflare/README.md), [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md), [cardmarket/README.md](cardmarket/README.md).
- **Cardmarket browser 429 handling** — warmup HTTP 429 fails fast (no profile rotation on same IP); reuse CDP landing tab (`_warmup_page_after_launch`); `[FETCH] OK` per-page logging; `RateLimitAbort` on IP ban at startup.

**2026-06-21**
- **Search preset save choice** — removed redundant **Clear preset** button (deselect via dropdown "— None —"). When a preset is selected, **Save** opens `#search-preset-save-modal` to **Overwrite** the active preset or **Save as new** (name prompt). Static `app.js?v=71`, `style.css?v=57`.

**2026-06-20**
- **Yugipedia errata, set chronology & tips** — Alembic `010`: `tcg_sets`, `card_errata_versions`, `cards.has_errata` / `last_erratum_date` / `tips`. Jobs: `scrape_yugipedia_set_chronology`, `scrape_yugipedia_supplements` (batched errata + tips), `import_set_chronology` (also runs from catalog import). GHA: `set_chronology` + `supplements_batch_0..5` before images/import. API `CardDetail` adds `errata[]` (English UI) + `tips[]`. Card modal: errata teaser + tips button with nested popups. Static `app.js?v=51`, `style.css?v=39`. Tests: `test_yugipedia_set_chronology.py`, `test_yugipedia_errata.py`, `test_yugipedia_tips.py`, `test_card_detail_supplements.py`.

**2026-06-18**
- **Email verification on registration** — two-step signup: `POST /api/auth/register` creates `pending_registrations` row and emails 6-digit OTP (10 min TTL, Brevo or `EMAIL_BACKEND=console` locally); `POST /api/auth/verify-email` creates `users` row with `email_verified_at`. Endpoints: `/auth/resend-code`, `/auth/config` (Turnstile site key). Neon-backed rate limits on auth routes. Alembic `009`. Frontend verify panel + resend cooldown. Env: `EMAIL_BACKEND`, `BREVO_API_KEY`, `EMAIL_FROM`, optional `TURNSTILE_*`. Tests: `test_email_verification.py`. Static `app.js?v=49`, `style.css?v=38`.
- **Login as landing page (no anonymous access)** — catalog read APIs (`GET /api/cards/search`, card detail/printings/suggestions, `GET /api/filters`, `GET /api/status`) now require JWT via `get_current_user`. Frontend shows a login/register landing page until `/api/auth/me` succeeds; app shell (tabs, search, collection, decks) hidden until authenticated. `GET /api/health` and auth login/register stay public. Static `app.js?v=47`, `style.css?v=36`. Tests: `test_api_auth.py`.
- **Hash-based client routing** — URL reflects active tab (`#/search`, `#/collection`, `#/decks`), search filter query params, collection `folder`, deck detail (`#/decks/{id}`), and card modal (`#/card/{passcode}`). Browser back/forward and refresh restore state; tab `aria-*` wiring; `document.title` per view; URL search-param allowlist + length caps. Static `app.js?v=43`, `style.css?v=35`.

**2026-06-13**
- **Cardmarket 3-step scrape refactor** — replaced monolithic `scrape_cardmarket_prices` with four jobs: `scrape_cardmarket_expansions` → `scrape_cardmarket_card_list` → `scrape_cardmarket_card_details` → `export_cardmarket_prices`. Full TCG catalog scrape (legacy 3-step parity), resumable checkpoints, phase-2 recovery, shared `http_client` adaptive throttle/429/CF handling. Job 4 joins details with Yugipedia catalog → existing `cardmarket_prices.json` import schema. `expansion_seed.json` auto-regenerates after job 2.
- **Cardmarket Cloudflare bypass** — `curl_cffi` default backend; adaptive throttle; UA rotation; `--cf-login` opens **Google Chrome** (not Playwright Chromium) to pass Cloudflare and saves `cf_clearance` to `data/catalog/cardmarket_browser_state.json` for reuse by curl_cffi/cloudscraper; `--browser-channel chrome|msedge`; optional `CARDMARKET_HTTP_PROXY`.
- **Cardmarket Playwright scrape** — optional `--browser` on `scrape_cardmarket_prices` uses headless Chromium (Playwright) with conservative 1 worker / ~1 req/s; bundled `expansion_seed.json` seeds expansion codes to cut discovery HTTP; improved 429 backoff (`Retry-After`, circuit breaker). `playwright install chromium` after pip install.
- **Cardmarket export/import pipeline** — scrape runs **locally only** (`scrape_cardmarket_prices` → `data/catalog/cardmarket_prices.json`, local SQLite cache `cardmarket_cache.db`). Upload: `upload_cardmarket_prices` → R2 `catalog/cardmarket_prices.json`. Import: `import_cardmarket_prices` (local `--file` or GHA `--from-r2`). Replaced `sync-cardmarket-prices.yml` with `import-cardmarket-prices.yml` (no cloud scrape). Tests: `test_import_cardmarket_prices.py`, `test_cardmarket_discover.py`.
- **Cardmarket printing prices** — `printing_market_prices` + `cardmarket_expansions` tables (Alembic `007`); card modal printings show LOW/AVG/TREND (EUR). Static `app.js?v=40`, `style.css?v=33`.
- **Instant card modal open** — modal overlay opens immediately on click with seeded name/meta/thumbnail from search results or collection row; skeleton shimmer for description/printings until `GET /api/cards/{id}` hydrates; action buttons disabled until loaded. Card detail route reuses `get_card_detail` owned/favorite data instead of duplicate `card_to_summary` queries. Static `app.js?v=39`, `style.css?v=32`.
- **Webapp speed improvements** — GZip middleware + production `Cache-Control: immutable` on `/static/*` ([`api/main.py`](ygo_app/api/main.py)). In-process TTL cache (10 min) for catalog portion of `GET /api/filters` ([`meta.py`](ygo_app/api/routes/meta.py)); invalidated after catalog import. Alembic `006`: `pg_trgm` GIN indexes on `cards.name`/`desc`/`archetype` + `collection_items.rarity_code`/`printing_id` (Postgres only). `search_cards` uses `load_only()` to skip `desc` and other unused columns. Frontend: search page size 500→100; parallel init (`status`/`filters`/`presets`); event delegation on search grid + collection table; stale-response guards; decks/collection tab memory cache + background refresh; modal favorite/tag local updates + `refreshModalCard()` (no full re-open); decks list cache for modal select; `preconnect` to `ms.yugipedia.com`. Static `app.js?v=38`, `style.css?v=31`.

**2026-06-12**
- **Cloudflare R2 card image mirror** — stop hotlinking `ms.yugipedia.com`: new [`jobs/sync_card_images.py`](ygo_app/jobs/sync_card_images.py) downloads art once, converts to WebP (full + 150px, Pillow), uploads to an S3-compatible bucket (boto3; keys `cards/{pid}.webp` / `cards/{pid}-small.webp`, immutable cache) and writes `data/catalog/images_manifest.json`. [`image_mirror.py`](ygo_app/image_mirror.py) holds vendor-neutral helpers; `adapter._resolve_images` rewrites import URLs for mirrored passcodes when `IMAGE_BASE_URL` is set (Yugipedia fallback otherwise). GHA workflow gains an `images` job (between batches and import; skips without `S3_BUCKET` secret; `import_only` rebuilds the manifest from the bucket via `--manifest-only`). New env/secrets: `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `IMAGE_BASE_URL`. Deps: boto3, Pillow. Tests: `test_image_mirror.py`, `test_sync_card_images.py`. See [§5](#5-card-images).

**2026-06-11**
- **Collection Edit modal + read-only Quantity** — table column renamed Qty → Quantity and made read-only (no inline number input). New per-row **Edit** button (all views) opens `#collection-edit-modal`: Set + Rarity `<select>`s populated from `GET /api/cards/{card_id}` printings (rarity re-filtered per set; disabled for catalog-unmatched rows), Quantity (min 1; folder-aware allocation update inside a folder view), Condition `<select>` limited to the DragonShield scale `Mint`/`NearMint`/`Excellent`/`Good`/`LightPlayed`/`Played`/`Poor` (MT/NM/EX/GD/LP/PL/PO; legacy values shown as extra option until edited). Backend: `CollectionItemUpdate` gains `set_code`/`rarity` (re-links `printing_id`, refreshes set/card fields via `_reassign_collection_item_printing`; 400 on unknown printing or duplicate user row) and validates `condition` against `COLLECTION_CONDITIONS` in [`schemas.py`](ygo_app/schemas.py). Static `app.js?v=35`, `style.css?v=30`. Tests: `test_collection_item_update.py`.
- **Folder view Move/Copy** — inside a folder, the Folder column is hidden and rows get **Move**/**Copy** buttons (popover with target folder select + qty input; Move capped at per-folder qty, Copy unbounded and raises total). No backend changes — uses `PATCH /api/collection/{id}` with `quantity` + `folder_allocations`. Static `app.js?v=33`, `style.css?v=29`. Test: `test_copy_increases_quantity_with_allocations` in `test_collection_folder_allocations.py`.
- **Empty folders + sidebar button** — `collection_stats()` uses LEFT OUTER joins so newly created (empty) folders appear in `folders[]` / sidebar immediately; **+ New folder** redesigned as a prominent full-width dashed accent button under the Folders heading (`style.css?v=28`). Test: `test_empty_folder_appears_in_stats` in `test_collection_stats.py`.
- **Collection folders refactor** — `collection_folders` + `collection_item_folders` (split qty per folder); Alembic `005`. Folder CRUD API (`GET/POST/PATCH/DELETE /api/collection/folders`). Multi-folder dropdown in My Collection; virtual **No Folder** (`__no_folder__`). Import get-or-create folder (case-insensitive); export one CSV row per allocation. Static `app.js?v=32`, `style.css?v=27`. Tests: `test_collection_folders.py`, `test_collection_folder_allocations.py` + updated list/stats/import/export/rename.
- **Search presets** — per-user named snapshots of Search tab filters. Table `search_presets` (Alembic `004`); API `/api/search-presets` CRUD with 409 on duplicate name unless `overwrite`. UI preset toolbar on Search tab (`#search-presets-bar`). `buildSearchParams` / `applySearchParams` in `app.js`. Static `app.js?v=31`, `style.css?v=26`. Tests: `test_search_presets.py`.
- **Alembic Neon commit fix** — [`alembic/env.py`](alembic/env.py) calls `connection.commit()` after online migrations so upgrades persist on Neon (fixes “upgrade logs 003→004 but DB stays 003”).

**2026-06-10**
- **My Collection tab restored** — third tab between Search and Decks. Folder sidebar (All / Unassigned / distinct `folder_name`), stats bar, paginated table (100/page) with thumbnails, inline qty/folder edit, delete, double-click folder rename. APIs: paginated `GET /api/collection`, `GET /api/collection/stats`, `PATCH /api/collection/folders/rename`. `list_collection` N+1 fixed via `joinedload` + batched set-code fallback. Static `app.js?v=30`, `style.css?v=25`. Tests: `test_list_collection.py`, `test_collection_stats.py`, `test_collection_folder_rename.py`.

**2026-06-05**
- **Collection CSV-only UI** — removed My Collection tab/view; header **Import my collection**; browse owned via Search **Owned only**. CSV import rejects unmatched catalog rows (`CollectionImportResult`, `_match_printing`); stream `done` includes `rejected_csv`. Modal add-to-collection kept. `app.js?v=22`. Tests: `test_import_collection_csv.py`.

**2026-06-04**
- **Advanced filter UI layout** — compact Category–Attribute dropdowns; Level/Rank/Link/Pendulum min/max `<select>` + `initStatRangeSelects()`; ATK/DEF numeric; `.filter-ranges` flex wrap (`gap: 1.5rem`). API/query params unchanged. Static-only (`style.css`, `app.js`, `index.html`).
- **Yugipedia-native filters** — Alembic `003`; `card_import.py` maps scrape → `category`, `types`, `mechanic`, `rank`, `link_rating`, `pendulum_scale`, `link_markers`, `summoning_condition`; advanced search UI + `/api/filters` (no auth for catalog lists); `parse_skill_card`; assets `style.css?v=11`, `app.js?v=13`. **Re-import** after deploy to populate new columns (GHA workflow unchanged).
- **Text search (`q`)** — `search_query.py` → `ILIKE`; removed `search_index.py` / `cards_fts` / `plainto_tsquery`.
- **Search help UI** — `?` button + `#search-help-modal`.
- **TCG-only filter** — reject cards with empty `card_sets` in `details._process_card` + `adapter.yugipedia_entries_to_api`.
- **Yugipedia images** — `extract_card_image` scrapes `ms.yugipedia.com` art from the metadata page; adapter uses scraped URLs with no YGOProDeck fallback.
- **Import FK fix** (`e4c939d`) — detach/re-link `collection_items.printing_id` so the catalog delete doesn't violate the `printings` FK.
- **500-card test mode** (`65758d3`, import fix `3ef9be1`) — `--max-cards`/`--limit`, GHA `test_mode`+`card_limit`, `resolve_min_cards()`; verified end-to-end on Neon dev.

**2026-06-03**
- Yugipedia scrape package under `ygo_app/yugipedia/`; multi-rarity `card_sets`; GHA split into 6 batched detail jobs (fixed 180-min single-job timeout) + bi-monthly prod schedule.
- `config.py` `_normalize_database_url()`; `.cursor/rules/` tracked while rest of `.cursor/` is gitignored; GHA import verified on Neon dev.
- Batch resilience: `scrape_progress.py` heartbeat/stall, bounded pool, batch retries, `audit_slice_completion()` + exit 3; tests `test_batch_completion.py`, `test_scrape_progress.py`.

**Earlier (still relevant)**
- Three-tier Render + Neon dev/prod; paginated search + `card_summaries_batch` (UI `limit=500`/page).
- Alembic `001`/`002`, `pool_pre_ping`, CSV `Path` fix, JWT multi-user.

---

## 10. Troubleshooting (resolved issues)

| Symptom | Fix / cause |
|---------|-------------|
| GHA `Could not parse SQLAlchemy URL` | Malformed GitHub secret; fix secret format (relies on `config.py` normalization) |
| Only one printing per multi-rarity set | `extract_rarities_from_cell` reads all `<a>` in the rarity cell |
| Actions missing the Yugipedia workflow | Workflow must exist on `main`; run with branch `develop` for code |
| Workflow YAML out of sync on `main`/`develop` | Workflow-only sync commit ([§7](#7-github-actions--deploy)) |
| `pathspec ...-dev.yml did not match` | The dev workflow file isn't on remote; use main workflow + `environment=dev` |
| Search stuck on Render | Paginated search + batch summaries |
| Quoted phrase matched scattered words | Replaced FTS/`plainto_tsquery` with `search_query` ILIKE phrase compiler |
| Search `total` wrong on large results | `COUNT` uses the same `compile_filter` as results |
| `varchar(16)` too narrow | Migration `002` widens `rarity_code` |
| GHA scrape canceled at 180 min | Chained jobs (`BATCH_COUNT=6`), per-job 60–90 min timeouts |
| Scrape appeared stuck | `[HEARTBEAT]`/`[FAIL]`/`[BATCH_RESULT]` + pool & batch retries |
| GHA import `ForeignKeyViolation` on `printings` | Detach/re-link `collection_items.printing_id`; run from `develop`, not Re-run |
| GHA import skipped after test `scrape_batch_0` | `import` job needs `always()` when later batches skip (`3ef9be1`) |
| Re-run still runs old code | **Run workflow** picks the new commit; Re-run reuses the original SHA |
| UI shows YGOProDeck art / JSON missing `image_url` | Pre-2026-06-04 scrape; re-run details scrape + import |
| Confusion over `yugipedia/get_images.py` | That legacy script downloaded YGOProDeck files; real URLs come from `parsing.extract_card_image` |
| Advanced filters empty / no Type options | DB rows pre-`003` or pre-re-import; run `alembic upgrade head` + full `import_catalog_yugipedia` on that Neon branch |
| GHA import: missing Yugipedia columns, `alembic_version='002'` after upgrade | Neon pooled URL + Alembic may not persist `003`; import job uses direct migration URL + idempotent DDL fallback in `db_migrate.py`. Optional: `DATABASE_URL_MIGRATIONS` = direct Neon URL |
| “Do I need to cherry-pick the GHA workflow?” | Usually no — same YAML; need **app code** on the workflow branch + re-import |
| CSV import: rows missing from **Owned only** | Row rejected at import — fix set code/rarity vs catalog or use `rejected_cards.csv`; only matched `(set_code, rarity_code)` rows are stored |
| Old **My Collection** tab very slow | Fixed: `list_collection` batch-joins via `linked_printing` + `printing_id`; paginated API |
| `alembic upgrade head` logs success but Neon `alembic_version` unchanged | Missing commit after migrations — fixed in [`alembic/env.py`](alembic/env.py) (`connection.commit()` after `run_migrations()`). Re-run `alembic upgrade head`; confirm with `alembic current` → `004` |
| Local Alembic only updates SQLite, not Neon | Set `DATABASE_URL` in `.env` to the Neon **dev** pooled URL before running Alembic (see [§8](#8-commands--env-vars)) |

---

## 11. Repository layout

```
ygo_app/
  api/                 # FastAPI: main.py + routes/{auth,cards,collection,decks,meta,search_presets}.py
  yugipedia/           # passcodes, details, parsing, card_sets, adapter, card_import,
                       #   images, http_client, scrape_progress, constants, paths
  card_filters.py      # advanced search SQL helpers
  jobs/
    scrape_yugipedia_catalog.py
    import_catalog_yugipedia.py
    import_catalog.py          # YGOProDeck API fallback
    sync_card_images.py        # mirror card art to S3-compatible bucket (R2)
    scrape_cardmarket_expansions.py   # job 1: expansion list
    scrape_cardmarket_card_list.py    # job 2: product lists
    scrape_cardmarket_card_details.py # job 3: detail prices
    scrape_cardmarket_incremental.py  # incremental orchestrator (new expansions)
    export_cardmarket_prices.py       # job 4: Yugipedia join → JSON
    scrape_cardmarket_prices.py       # deprecated (migration message)
    import_cardmarket_prices.py   # JSON or R2 → printing_market_prices
    upload_cardmarket_prices.py   # JSON → R2
  cardmarket/                  # scrape, export schema, R2 handoff, matching
  image_mirror.py              # mirrored image keys/URLs + manifest + import rewrite
  import_data.py               # catalog replace + import_collection_csv (CollectionImportResult)
  collection_export.py         # DragonShield CSV export
  import_progress.py           # CSV import progress throttle / ETA
  search_query.py              # q parser + ILIKE compiler
  services.py  models.py  schemas.py  auth.py  config.py  database.py  catalog.py  utils.py
  static/                      # index.html, css/style.css, js/app.js
alembic/versions/  001 … 004_search_presets.py
tests/                         # 23 unittest modules (search, presets, scrape, collection list/stats/rename, import/export CSV, …)
.github/workflows/             # import-catalog-yugipedia.yml, import-cardmarket-prices.yml, …
.cursor/rules/                 # github-actions-yugipedia-workflow-sync.mdc
docs/                          # LOCAL_DEV.md, ENVIRONMENTS.md, DEPLOY_FREE.md
yugipedia/                     # legacy standalone scrapers (NOT ygo_app/yugipedia)
data/catalog/                  # gitignored scrape JSON
```

---

## 12. Verification checklist

| Check | Expected |
|-------|----------|
| `GET /api/health` | `{"ok": true}` (no auth — Render health checks) |
| `GET /api/status` (auth) | `ready: true`; `cards` count TCG-printed only (< ~14k passcodes; ~500 in test_mode) |
| Anonymous `GET /api/filters`, `/api/status`, `/api/cards/*` read routes | **401** Not authenticated |
| `python -m unittest discover -s tests` | All pass |
| GHA scrape (full) | Green `passcodes` + `scrape_batch_0..5` + `import`; each batch `[BATCH_RESULT] missing=0` |
| GHA scrape (test) | Green `passcodes` + `scrape_batch_0` + `import`; batches 1–5 skipped; ~500 cards on dev |
| `GET /api/cards/{passcode}` | `image_url` host is `IMAGE_BASE_URL` (mirrored) or `ms.yugipedia.com` (fallback) — never `images.ygoprodeck.com` |
| `GET /api/cards/search?q=reveal` | Cards whose name/desc/archetype contain `reveal` |
| `GET /api/cards/search?q="You can reveal"` | Only the contiguous phrase (case-insensitive) |
| Multi-rarity | Same `set_code`, different `set_rarity` (e.g. `RA03-EN172`) |
| Search UI `?` button | Opens help modal (Example/Description); Close / Escape / backdrop dismiss |
| `GET /api/filters` (with auth) | Non-empty `types` / `attributes` after re-import on that DB |
| `GET /api/cards/search?category=Monster&types=Fusion` | OR on `types` JSON |
| `GET /api/cards/summoning-suggestions?q=WATER` | Distinct `summoning_condition` substring matches |
| Logged in: **Import my collection** | Header button visible; NDJSON progress on `#import-progress` |
| Logged in: **Export my collection** | Modal lists DragonShield format; downloads UTF-8 BOM CSV |
| Logged in: **My Collection** tab | Folder sidebar, stats line, table with thumbnails; pagination when >100 rows |
| `GET /api/collection/stats` (auth) | `total_items`, `folders[]` (with `id`), `no_folder_count` |
| `folder=__no_folder__` on list | Returns items with No Folder allocation |
| CSV with bad set codes | `rejected_cards.csv` download; matched rows in DB; **Owned only** shows them |
| Logged in: Search **preset** toolbar | `#search-presets-bar` visible; Save/Load/Rename/Delete; `GET /api/search-presets` returns list |
| `alembic current` (Neon dev in `.env`) | `010 (head)` after errata/tips migration |
