# Agent handoff — YGO Collection & Deck Builder

> **For the next agent.** Read this first for token-efficient context instead of replaying chat history.
> Keep it current when architecture, deploy, or conventions change. Body stays **timeless**; put dated work in [§9 Changelog](#9-changelog).
>
> **Last updated:** 2026-06-04

---

## 1. TL;DR

| | |
|------|--------|
| **What** | Browser UI + FastAPI API for Yu-Gi-Oh! card search, per-user collection (set code + rarity), decks, favorites, tags. |
| **Stack** | Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic 2 · Alembic · static HTML/JS · BeautifulSoup + cloudscraper (scrape) · JWT auth (bcrypt). |
| **Run locally** | `pip install -r requirements.txt` → `alembic upgrade head` → `python run.py` (opens browser; API docs at `/docs`). |
| **Test** | `python -m unittest discover -s tests` |
| **DB** | PostgreSQL on **Neon** (pooled URL, `sslmode=require`). Falls back to SQLite `data/ygo.db` only when `DATABASE_URL` is unset. **Not** Render Postgres. |
| **Catalog source** | **Yugipedia** scrape (primary) → JSON → Neon. YGOProDeck API = emergency fallback only. |
| **Card images** | **CDN only** (`ms.yugipedia.com` URLs stored in DB; browser loads at view time). Nothing is downloaded. |
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
    P[prepare] --> PC[passcodes] --> B0[scrape_batch_0..5] --> IM[import]
    PC --> Art["artifact catalog-state"]
    B0 --> Art --> IM
  end
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
  Browser --> CDN["ms.yugipedia.com"]
```

**Stages** (orchestrator: `python -m ygo_app.jobs.scrape_yugipedia_catalog --full`; supports `--details-only --resume`):

| Step | Module / job | Output |
|------|----------------|--------|
| 1 | [`yugipedia/passcodes.py`](ygo_app/yugipedia/passcodes.py) | `data/catalog/yugipedia_passcode_list.json` (all `Concept:CG cards`) |
| 2 | [`yugipedia/details.py`](ygo_app/yugipedia/details.py) + [`parsing.py`](ygo_app/yugipedia/parsing.py) | `yugipedia_all_cards.json` (metadata + `image_url`/`image_url_small`); `yugipedia_rejected_cards.json` |
| 3 | [`jobs/import_catalog_yugipedia.py`](ygo_app/jobs/import_catalog_yugipedia.py) + [`adapter.py`](ygo_app/yugipedia/adapter.py) | Neon `cards` + `printings` |

**Key behaviors:**

- **Import = full replace.** `import_cards_entries` deletes all `cards` + `printings`, then reloads from JSON. Never truncate manually.
- **Import side effects.** `users` / `collection_items` are kept; deleting `cards` cascades **favorites**, **tags**, **deck_cards**. [`import_data.py`](ygo_app/import_data.py) detaches `collection_items.printing_id` before the delete, then re-links by `(set_code, rarity_code)` after import (avoids FK violation on `printings`).
- **TCG-only filter.** Cards with no English printings (empty/missing `cts--EN` → no `card_sets`) are rejected in [`details._process_card`](ygo_app/yugipedia/details.py) and skipped in [`adapter.yugipedia_entries_to_api`](ygo_app/yugipedia/adapter.py). OCG-only entries land in `yugipedia_rejected_cards.json`. Final card count is **below** the ~14k passcode total.
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

Yugipedia URLs only — no downloads, no server storage.

| Piece | Role |
|-------|------|
| [`parsing.extract_card_image`](ygo_app/yugipedia/parsing.py) | Picks largest card-art `<img>` on `ms.yugipedia.com` from the same page fetch as metadata; skips `noviewer`, `.svg`, UI/attribute icons |
| [`images.py`](ygo_app/yugipedia/images.py) | Thumb → full URL normalization; 150px small thumb. `image_urls_for_passcode()` is **only** for the YGOProDeck API fallback |
| [`adapter._resolve_images`](ygo_app/yugipedia/adapter.py) | Maps scrape JSON → `card_images`; **no** YGOProDeck CDN fallback (null if scrape found no art) |
| Browser ([`app.js`](ygo_app/static/js/app.js)) | Loads `image_url`/`image_url_small`; shows `IMG_PLACEHOLDER` when null |

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

## 6. Card search (`q` on `/api/cards/search`)

Google-style text query compiled to case-insensitive `ILIKE` on `name` / `desc` / `archetype` (with `coalesce` so `NOT` works when archetype is null).

| Piece | Role |
|-------|------|
| [`search_query.py`](ygo_app/search_query.py) | Tokenizer + AST (`Phrase`, `Term`, `And`, `Or`, `Not`); `compile_filter` / `text_search_filter` → SQLAlchemy `WHERE` |
| [`services.search_cards`](ygo_app/services.py) | Same compiled filter for rows **and** `COUNT`; invalid syntax falls back to plain term |
| UI field | [`static/index.html`](ygo_app/static/index.html) — `#q` + `?` button (`#search-help-btn`) |
| UI help | `#search-help-modal` — overlay dialog; [`app.js`](ygo_app/static/js/app.js) `openSearchHelpModal`/`closeSearchHelpModal`; `<table>` cols **Example** \| **Description** |

**Syntax (case-insensitive):** `reveal` (substring) · `"You can reveal"` (contiguous phrase) · `reveal hand` (implicit AND) · `reveal OR hand` · `reveal -hand` / `NOT` · `millenn?um` · `reveal*`. All-digit `q` → passcode lookup only. Full list lives in the help modal, not inline on the form.

**Removed:** `search_index.py`, the `cards_fts` SQLite FTS5 table, and Postgres `plainto_tsquery`. Offline SQLite app mode (`data/ygo.db`) uses the same `ILIKE` compiler.

Tests: [`test_search_query.py`](tests/test_search_query.py), [`test_search_cards.py`](tests/test_search_cards.py).

---

## 7. GitHub Actions & deploy

| Workflow | UI name | Notes |
|----------|---------|-------|
| [`import-catalog-yugipedia.yml`](.github/workflows/import-catalog-yugipedia.yml) | Import Yugipedia catalog | `prepare → passcodes → scrape_batch_0..5 → import`; `BATCH_COUNT=6`; inputs `test_mode` + `card_limit` (default 500); **environment** `dev`\|`production`; scheduled 1st & 15th → prod |
| [`import-catalog-ygoprodeck.yml`](.github/workflows/import-catalog-ygoprodeck.yml) | Import YGO catalog (YGOProDeck fallback) | Manual emergency only |
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
alembic upgrade head
python run.py                                   # local app (SQLite if DATABASE_URL unset)
python -m unittest discover -s tests            # full test suite
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

### GHA from CLI
```powershell
gh workflow run "Import Yugipedia catalog" --ref develop -f environment=dev
gh workflow run "Import Yugipedia catalog" --ref develop -f environment=dev -f test_mode=true -f card_limit=500
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
| `ENV` | `production` (parity) or unset → SQLite | `production` |
| `SECRET_KEY` | any local value | per Render service |

**GitHub secrets must be the raw Neon pooled URL only** — `postgresql://user:pass@ep-xxx-pooler.../neondb?sslmode=require`. No quotes, no `DATABASE_URL=` prefix, no whitespace. [`config.py`](ygo_app/config.py) `_normalize_database_url()` strips these defensively, but fix the secret at the source.

---

## 9. Changelog

Recent work, newest first. Keep the body above timeless; record dated changes here.

**2026-06-04**
- **Advanced search** — `search_query.py` tokenizer + AST → `ILIKE` filter; `search_cards` uses one compiled filter for rows + count; removed `search_index.py` / `cards_fts` / `plainto_tsquery`.
- **Search help UI** — `?` button + `#search-help-modal` (Example/Description table); `syncModalOpenClass()` for `body.modal-open`; assets bumped to `style.css?v=10`, `app.js?v=12`.
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

---

## 11. Repository layout

```
ygo_app/
  api/                 # FastAPI: main.py + routes/{auth,cards,collection,decks,meta}.py
  yugipedia/           # passcodes, details, parsing, card_sets, adapter, images,
                       #   http_client, scrape_progress, constants, paths
  jobs/
    scrape_yugipedia_catalog.py
    import_catalog_yugipedia.py
    import_catalog.py          # YGOProDeck API fallback
  import_data.py               # import_cards_entries (full catalog replace)
  search_query.py              # q parser + ILIKE compiler
  services.py  models.py  schemas.py  auth.py  config.py  database.py  catalog.py  utils.py
  static/                      # index.html, css/style.css, js/app.js
alembic/versions/  001_initial_multiuser.py  002_widen_rarity_code.py
tests/                         # 12 unittest modules (see §6 / §9 for key ones)
.github/workflows/             # import-catalog-yugipedia.yml, import-catalog-ygoprodeck.yml, db-keepalive.yml
.cursor/rules/                 # github-actions-yugipedia-workflow-sync.mdc
docs/                          # LOCAL_DEV.md, ENVIRONMENTS.md, DEPLOY_FREE.md
yugipedia/                     # legacy standalone scrapers (NOT ygo_app/yugipedia)
data/catalog/                  # gitignored scrape JSON
```

---

## 12. Verification checklist

| Check | Expected |
|-------|----------|
| `GET /api/health` | `{"ok": true}` |
| `GET /api/status` | `ready: true`; `cards` count TCG-printed only (< ~14k passcodes; ~500 in test_mode) |
| `python -m unittest discover -s tests` | All pass |
| GHA scrape (full) | Green `passcodes` + `scrape_batch_0..5` + `import`; each batch `[BATCH_RESULT] missing=0` |
| GHA scrape (test) | Green `passcodes` + `scrape_batch_0` + `import`; batches 1–5 skipped; ~500 cards on dev |
| `GET /api/cards/{passcode}` | `image_url` host is `ms.yugipedia.com` (not `images.ygoprodeck.com`) |
| `GET /api/cards/search?q=reveal` | Cards whose name/desc/archetype contain `reveal` |
| `GET /api/cards/search?q="You can reveal"` | Only the contiguous phrase (case-insensitive) |
| Multi-rarity | Same `set_code`, different `set_rarity` (e.g. `RA03-EN172`) |
| Search UI `?` button | Opens help modal (Example/Description); Close / Escape / backdrop dismiss |
