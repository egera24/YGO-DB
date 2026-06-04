# Agent handoff — YGO Collection & Deck Builder

**Last updated:** 2026-06-04 (advanced card search: Google-style query parser; removed SQLite FTS5 / Postgres `plainto_tsquery` path)
**Purpose:** Onboard the next agent/session without re-reading full chat history. Keep this file updated when architecture or deploy steps change.

**New agents:** Read this file at session start for token-efficient context.

---

## 1. Project summary

| Item | Detail |
|------|--------|
| **What** | Browser UI + FastAPI API for Yu-Gi-Oh! card search, per-user collection (set code + rarity), decks, favorites, tags |
| **Stack** | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic, static HTML/JS, Alembic, `python-dotenv`, BeautifulSoup, cloudscraper |
| **Local DB (fallback)** | SQLite `data/ygo.db` when `DATABASE_URL` unset in `.env` |
| **Recommended local** | Neon **dev** branch via `.env` (`ENV=production`) — [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md) |
| **Cloud DB** | PostgreSQL on **Neon** (pooled URL, `sslmode=require`) — not Render Postgres |
| **Catalog source** | **Yugipedia** scrape (primary); fallback: YGOProDeck API |
| **Card images** | **CDN only** — Yugipedia URLs (`ms.yugipedia.com`) scraped into JSON/DB; browser loads at view time. YGOProDeck CDN only for API fallback import. |
| **Auth** | JWT (`SECRET_KEY`; bcrypt for passwords) |
| **Text search** | [`ygo_app/search_query.py`](ygo_app/search_query.py) — phrases `"..."`, `AND`/`OR`/`NOT`/`-`, wildcards `*`/`?`; compiled to case-insensitive `ILIKE` on name, desc, archetype (Neon/Postgres primary) |

### Environments (three tiers)

| Tier | Git branch | Render service | Neon branch |
|------|------------|----------------|-------------|
| **Local** | any | — (`python run.py`) | **dev** (`.env`) |
| **Staging** | `develop` | `ygo-app-dev` | **dev** |
| **Production** | `main` | `ygo-app` | **main** (production) |

Full workflow: [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md).

### Git / deploy state (typical after Yugipedia setup)

| Branch | Often contains |
|--------|----------------|
| **`develop`** | Full Yugipedia app code (`ygo_app/yugipedia/`, jobs, tests) + workflows |
| **`main`** | Workflow YAML (+ `import_data.py` FK fix); full `ygo_app/yugipedia/` still on **`develop`** until merge |

Branches can **diverge** (e.g. workflow-only commit on `main`, app commits on `develop`). That is intentional for “test on dev without merging app to prod.”

---

## 2. Architecture

```mermaid
flowchart TB
  subgraph scrape [Scrape ephemeral]
    Wiki[Yugipedia API + wiki pages]
    JSON["data/catalog/*.json"]
    Wiki --> JSON
  end
  subgraph gha [GitHub Actions chained jobs]
    WF["import-catalog-yugipedia.yml"]
    P[prepare]
    PC[passcodes]
    B0[scrape_batch_0..5]
    IM[import]
    Art["artifact catalog-state"]
    WF --> P --> PC --> B0 --> IM
    PC --> Art
    B0 --> Art
    Art --> IM
  end
  subgraph neon [Neon Postgres]
    Cards[cards + printings]
  end
  subgraph render [Render]
    DevWeb["ygo-app-dev ← develop"]
    ProdWeb["ygo-app ← main"]
  end
  JSON --> IM
  IM --> Cards
  DevWeb --> Cards
  ProdWeb --> Cards
  Browser --> DevWeb
  Browser --> ProdWeb
  Browser --> CDN["ms.yugipedia.com"]
```

### Catalog pipeline

| Step | Module / job | Output / target |
|------|----------------|-----------------|
| 1 | [`ygo_app/yugipedia/passcodes.py`](ygo_app/yugipedia/passcodes.py) | `data/catalog/yugipedia_passcode_list.json` |
| 2 | [`ygo_app/yugipedia/details.py`](ygo_app/yugipedia/details.py) + [`parsing.py`](ygo_app/yugipedia/parsing.py) | `yugipedia_all_cards.json` (metadata + `image_url` / `image_url_small`), `yugipedia_rejected_cards.json` |
| 3 | [`ygo_app/jobs/import_catalog_yugipedia.py`](ygo_app/jobs/import_catalog_yugipedia.py) + [`adapter.py`](ygo_app/yugipedia/adapter.py) | Neon `cards` + `printings` (`cards.image_url*` from scrape) |

Orchestrator: `python -m ygo_app.jobs.scrape_yugipedia_catalog --full` (`--details-only --resume` supported). GHA uses **6 batched details jobs** (`--batch-index` / `--batch-count`); see workflow below.

**Multi-rarity printings:** [`ygo_app/yugipedia/card_sets.py`](ygo_app/yugipedia/card_sets.py) — all `<a>` tags in rarity cell (not `<br>` split). Only the English timeline table (`id` contains `cts--EN`).

**TCG-only catalog:** Cards with no English printings (empty / missing `cts--EN` → no `card_sets` in scrape JSON) are **rejected** in [`details._process_card`](ygo_app/yugipedia/details.py) (`No English (TCG) printings (empty cts--EN)`) and **skipped** again in [`adapter.yugipedia_entries_to_api`](ygo_app/yugipedia/adapter.py). Passcode index still lists all `Concept:CG cards`; OCG-only entries land in `yugipedia_rejected_cards.json`, not `cards`. Card count after full import is **below** the old ~14k passcode total (exact count after one full scrape + import).

**Import replaces catalog:** `import_cards_entries` deletes all `cards` and `printings` then reloads. Do **not** manually truncate Neon catalog tables.

**Import side effects:** `users` / `collection_items` kept; deleting `cards` cascades **favorites**, **tags**, **deck_cards**. Before catalog delete, [`import_data.py`](ygo_app/import_data.py) clears `collection_items.printing_id`, then re-links by `(set_code, rarity_code)` after import (avoids FK violation on `printings`). Catalog import no longer rebuilds a search index (FTS removed).

### Card search (text `q` on `/api/cards/search`)

| Piece | Role |
|-------|------|
| [`search_query.py`](ygo_app/search_query.py) | Parse `q` → AST; `compile_filter` / `text_search_filter` → SQLAlchemy `WHERE` |
| [`services.search_cards`](ygo_app/services.py) | Applies same filter to results **and** `COUNT` (no capped FTS ID list) |
| UI | [`static/index.html`](ygo_app/static/index.html) — placeholder + `<details>` syntax help |

**Syntax (case-insensitive):** `reveal` (substring) · `"You can reveal"` (contiguous phrase) · `reveal hand` (implicit AND) · `reveal OR hand` · `reveal -hand` / `NOT` · `millenn?um` · `reveal*`. All-digit `q` → passcode lookup only.

**Removed:** `ygo_app/search_index.py` (SQLite FTS5 `cards_fts`, Postgres `plainto_tsquery`). Optional offline SQLite **app** mode (`data/ygo.db`) unchanged; search uses the same `ILIKE` compiler there.

**Tests:** [`test_search_query.py`](tests/test_search_query.py), [`test_search_cards.py`](tests/test_search_cards.py).

### Card images (Yugipedia URLs, no downloads)

| Piece | Role |
|-------|------|
| [`parsing.extract_card_image`](ygo_app/yugipedia/parsing.py) | On each wiki page fetch, picks largest card-art `<img>` on `ms.yugipedia.com`; skips `noviewer`, `.svg`, UI icons (link markers, attribute icons) |
| [`images.py`](ygo_app/yugipedia/images.py) | Thumb → full URL normalization; 150px small thumb; `image_urls_for_passcode()` **only** for YGOProDeck API fallback import |
| [`adapter._resolve_images`](ygo_app/yugipedia/adapter.py) | Maps scrape JSON → `card_images`; **no YGOPRODeck CDN fallback** — null if scrape found no art |
| Browser / [`app.js`](ygo_app/static/js/app.js) | Loads `image_url` / `image_url_small` from DB; `IMG_PLACEHOLDER` when null |

**JSON shape** (per card in `yugipedia_all_cards.json`):

```json
{
  "id": "85087012",
  "name": "Card Trooper",
  "image_url": "https://ms.yugipedia.com//6/65/CardTrooper-25YC-EN-SR-LE.png",
  "image_url_small": "https://ms.yugipedia.com//thumb/6/65/CardTrooper-25YC-EN-SR-LE.png/150px-CardTrooper-25YC-EN-SR-LE.png"
}
```

**Not used:** [`yugipedia/get_images.py`](yugipedia/get_images.py) — legacy script that **downloaded** from YGOPRODeck by passcode; never scraped Yugipedia.

**Re-scrape required:** DB/JSON created before this change still have YGOPRODeck URLs or null images until scrape + `import_catalog_yugipedia` run again.

**Fallback import** (`python -m ygo_app.jobs.import_catalog`): still uses YGOPRODeck API + `images.ygoprodeck.com`.

### Where catalog data lives

| Stage | Location | In git? | Lifetime |
|-------|----------|---------|----------|
| Scrape JSON | `data/catalog/*.json` (local or GHA runner) | **No** (`data/` gitignored) | Ephemeral on runner; local until deleted |
| GHA backup | Artifact `yugipedia-catalog-<run_id>` | **No** | 14 days ([`retention-days: 14`](.github/workflows/import-catalog-yugipedia.yml)) |
| **Row data** | Neon Postgres **`cards`** + **`printings`** | N/A | Permanent (dev or prod branch per `DATABASE_URL`) |

- **`cards`:** one row per card; `id` = Yugipedia passcode (8 digits).
- **`printings`:** one row per set code + rarity; FK `card_id` → `cards.id`.
- GHA **environment `dev`** → secret `DATABASE_URL_DEV` → Neon **dev** branch. **production** → `DATABASE_URL` → Neon **main**.

GHA scrape is **chained jobs** (passcodes + 6 detail batches + import). Each job has its own timeout (60–90 min); total workflow wall clock **~2–4 h** full · **~30–60 min** with **`test_mode`** (500 cards, batches 1–5 skipped, single details batch). Artifact **`catalog-state`** passes JSON between batches. `PYTHONUNBUFFERED=1` on the workflow.

**GHA `test_mode` (workflow_dispatch):** inputs `test_mode` + `card_limit` (default 500); **dev only** (blocked on `production`). Scrape `--max-cards`; import `--limit`; `import` job uses `always()` so it still runs when `scrape_batch_5` is skipped. Use **Run workflow** (new run) — **Re-run failed jobs** reuses the old commit and breaks fixes.

**Resilience** ([`scrape_progress.py`](ygo_app/yugipedia/scrape_progress.py), [`details.py`](ygo_app/yugipedia/details.py)):

| Layer | Behavior |
|-------|----------|
| HTTP | 5× retry per card; `[WARN]` on slow/Cloudflare/retryable errors ([`http_client.py`](ygo_app/yugipedia/http_client.py)) |
| Pool | Max 8 in-flight; 240s pool idle → re-queue |
| Batch | Up to **2** `[BATCH_RETRY]` rounds for transient failures + pool timeouts (`FAILED_RETRY_ROUNDS` in [`constants.py`](ygo_app/yugipedia/constants.py)) |
| Stall | `[HEARTBEAT]` every 60s; warn at 120s idle; abort at 600s → exit **2** |

**Logs to watch:** `[HEARTBEAT]`, `[FAIL] will-retry|final`, `[BATCH_RETRY]`, `[BATCH_RESULT] expected=… saved=… rejected=… missing=…` (each batch job must end with **`missing=0`**).

**CLI exit codes** ([`scrape_yugipedia_catalog.py`](ygo_app/jobs/scrape_yugipedia_catalog.py)): **0** ok · **1** config/file · **2** stall (re-run `--resume`) · **3** batch incomplete (`BatchIncompleteError`, GHA job fails).

Cancel message `The operation was canceled` usually means **per-job timeout**, not a Python exception.

### GitHub Actions workflows

| Workflow file | Name in UI | On `main`? | Notes |
|---------------|------------|------------|--------|
| [`import-catalog-yugipedia.yml`](.github/workflows/import-catalog-yugipedia.yml) | Import Yugipedia catalog | Yes | `prepare` → `passcodes` → `scrape_batch_0..5` → `import`; `test_mode` + `card_limit`; `BATCH_COUNT=6`; **environment** `dev` \| `production`; schedule 1st & 15th → prod |
| [`import-catalog-ygoprodeck.yml`](.github/workflows/import-catalog-ygoprodeck.yml) | Import YGO catalog (YGOProDeck API fallback) | Yes | Manual emergency only |
| [`db-keepalive.yml`](.github/workflows/db-keepalive.yml) | Neon DB keep-alive | Yes | Both secrets |

**`import-catalog-yugipedia-dev.yml`:** optional convenience (dev DB only). **Not required** — use main workflow with branch **`develop`** + environment **`dev`**.

Workflows appear in Actions when present on **default branch (`main`)**. Running with branch **`develop`** uses **code from `develop`** (must include `ygo_app/yugipedia/`).

**Keep workflow YAML in sync:** `.github/workflows/import-catalog-yugipedia.yml` must be **identical** on `main` and `develop`. Cursor rule: [`.cursor/rules/github-actions-yugipedia-workflow-sync.mdc`](.cursor/rules/github-actions-yugipedia-workflow-sync.mdc). After editing on `develop`, sync to `main` with a workflow-only commit (below)—do **not** full-merge `develop` just for the YAML.

### Push workflow files to `main` without merging app (documented pattern)

```powershell
git fetch origin
git checkout main
git pull origin main
git checkout origin/develop -- .github/workflows/import-catalog-yugipedia.yml
git commit -m "ci: sync Yugipedia import workflow from develop"
git push origin main
git checkout develop
```

Same pattern for `import-catalog-ygoprodeck.yml` if that file changes. Verify sync:

```powershell
git fetch origin
git diff origin/main origin/develop -- .github/workflows/import-catalog-yugipedia.yml
```

(No output = in sync.)

Does **not** deploy new app code to prod unless `ygo_app/` changed on `main`. Render **ygo-app** only rebuilds when `main` app files change.

### Free permanent cloud

| Piece | File / service |
|-------|----------------|
| Staging | `ygo-app-dev` — branch **`develop`** |
| Production | `ygo-app` — branch **`main`** |
| Blueprint | [`render.yaml`](render.yaml) |
| Docs | [`docs/DEPLOY_FREE.md`](docs/DEPLOY_FREE.md), [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md), [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md) |

---

## 3. Repository layout

```
ygo_app/
  yugipedia/           # passcodes, details, scrape_progress, card_sets, parsing, adapter, images
  jobs/
    scrape_yugipedia_catalog.py
    import_catalog_yugipedia.py
    import_catalog.py          # YGOProDeck API fallback
  import_data.py       # import_cards_entries (full catalog replace)
  search_query.py      # Google-style q parser + ILIKE filter compiler
  api/, services/, static/js/app.js
data/catalog/          # gitignored scrape JSON
tests/
  test_search_query.py
  test_search_cards.py
  test_yugipedia_card_sets.py
  test_yugipedia_adapter.py
  test_yugipedia_details.py
  test_yugipedia_images.py
  test_yugipedia_batch_slice.py
  test_scrape_progress.py
  test_batch_completion.py
  test_import_catalog_replace.py
  test_import_catalog_yugipedia.py
  test_yugipedia_passcode_limit.py
.github/workflows/
  import-catalog-yugipedia.yml
  import-catalog-ygoprodeck.yml
  db-keepalive.yml
.cursor/rules/
  github-actions-yugipedia-workflow-sync.mdc
yugipedia/             # legacy CLI wrappers → ygo_app jobs
```

---

## 4. What was implemented

### Advanced card search (2026-06-04)

1. **`search_query.py`** — tokenizer + AST (`Phrase`, `Term`, `And`, `Or`, `Not`); `ILIKE` on `name` / `desc` / `archetype` with `coalesce` (fixes `NOT` when archetype is null).
2. **`search_cards`** — single compiled filter for rows and total count; invalid syntax falls back to plain term.
3. **Removed** `search_index.py`, `cards_fts` rebuild on import, Postgres `plainto_tsquery` / broken per-token FTS quoting.
4. UI syntax help on search panel; tests above.

**Phrase semantics:** quoted text must appear **contiguously** in card text (e.g. `"You can reveal"` does not match “You can either … or reveal”).

### TCG-only catalog filter (2026-06-04)

1. [`details._process_card`](ygo_app/yugipedia/details.py) — reject when parse succeeds but `card_sets` is empty.
2. [`adapter.yugipedia_entries_to_api`](ygo_app/yugipedia/adapter.py) — skip entries without `card_sets` on import.
3. Tests: [`test_yugipedia_details.py`](tests/test_yugipedia_details.py), adapter test for skipped OCG-only entries.
4. **Apply to existing DB:** full details re-scrape + `python -m ygo_app.jobs.import_catalog_yugipedia` (import alone drops OCG-only rows still in old JSON).

### Yugipedia card images (2026-06-04)

1. **`extract_card_image`** in [`parsing.py`](ygo_app/yugipedia/parsing.py) — card art from same wiki HTML as metadata (no extra HTTP, no downloads).
2. **`images.py`** — `normalize_yugipedia_image_url`, `yugipedia_thumb_url`; YGOPRODeck helpers retained for API fallback only.
3. **`adapter.py`** — uses scraped `image_url` / `image_url_small`; no YGOPRODeck CDN fallback on Yugipedia import.
4. Tests: [`test_yugipedia_images.py`](tests/test_yugipedia_images.py); adapter tests updated.
5. Docs: README, LOCAL_DEV, DEPLOY_FREE; `yugipedia/get_images.py` docstring clarifies it was YGOPRODeck-only.

### Yugipedia catalog (2026-06-03)

1. Scrape package under `ygo_app/yugipedia/`.
2. Multi-rarity `card_sets` extraction + tests (e.g. RA03-EN172).
3. GHA: batched scrape (6 detail jobs) + import; bi-monthly prod schedule; fixes 180 min single-job timeout.
4. Workflows on `main` for Actions UI; **run from branch `develop`** until app merged to prod.
5. **`config.py`:** `_normalize_database_url()` — strips whitespace, wrapping quotes, `DATABASE_URL=` prefix; validates URL before engine creation (fixes malformed GitHub secrets).
6. **Cursor rule** + `.gitignore` exception: `.cursor/rules/` tracked in git; rest of `.cursor/` ignored.
7. **GHA Yugipedia import verified** on Neon dev (`DATABASE_URL` + `DATABASE_URL_DEV` secrets; branch `develop`, environment `dev`).
8. **Batch resilience (2026-06-03):** `scrape_progress.py` (heartbeat/stall); bounded scrape pool; transient failure batch retries; `audit_slice_completion()` + exit **3** on incomplete batch; tests `test_batch_completion.py`, `test_scrape_progress.py`.
9. **Catalog import FK fix (2026-06-04):** detach `collection_items.printing_id` before delete; delete `cards` only (printings cascade); bulk re-link after import (`e4c939d`).
10. **500-card test mode (2026-06-04):** `--max-cards` / `--limit`; GHA `test_mode` + `card_limit`; `resolve_min_cards()` (80% of limit); **verified** end-to-end on Neon dev (`65758d3`, import fix `3ef9be1`).
11. **Prior image behavior (pre-2026-06-04):** adapter synthesized `images.ygoprodeck.com` URLs from passcode; JSON had no image fields — replaced by Yugipedia scrape URLs above.

### Earlier (still relevant)

5. Three-tier Render + Neon dev/prod; search pagination + `card_summaries_batch` (UI `limit=500` per page).  
6. Alembic `001`/`002`, `pool_pre_ping`, CSV `Path` fix, JWT multi-user.

---

## 5. Commands cheat sheet

### Test catalog on dev (no merge to `main`)

**GitHub Actions (full):** **Import Yugipedia catalog** → **Run workflow** → branch **`develop`** → environment **`dev`**.

**GitHub Actions (500-card test, ~30–60 min):** same workflow → `test_mode=true`, `card_limit=500`. Confirm `import` job runs (not skipped) after `scrape_batch_0`.

**CLI alternative:**

```powershell
gh workflow run "Import Yugipedia catalog" --ref develop -f environment=dev
gh workflow run "Import Yugipedia catalog" --ref develop -f environment=dev -f test_mode=true -f card_limit=500
```

**Local:**

```powershell
# .env → DATABASE_URL = Neon dev
python -m ygo_app.jobs.scrape_yugipedia_catalog --full
python -m ygo_app.jobs.import_catalog_yugipedia
```

**Local single GHA-equivalent batch:**

```powershell
python -m ygo_app.jobs.scrape_yugipedia_catalog --passcodes-only
python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only --resume --batch-index 0 --batch-count 6
python -m ygo_app.jobs.import_catalog_yugipedia
```

### Full local / release

```powershell
pip install -r requirements.txt
alembic upgrade head
python -m ygo_app.jobs.scrape_yugipedia_catalog --full
python -m ygo_app.jobs.import_catalog_yugipedia
python run.py
```

### Git (typical)

```powershell
git checkout develop
# ... work, push → staging deploy
# when ready:
git checkout main && git merge develop && git push   # prod app + full code on main
```

### Yugipedia catalog — full vs test (500 cards)

| Mode | Scrape | Import | Neon |
|------|--------|--------|------|
| **Full** | 6 GHA batches / `--full` locally | all JSON → **replaces** entire catalog | ~14k cards |
| **Test** | `--max-cards 500` or GHA `test_mode` | `--limit 500` (min 400 mapped) | **dev only** — DB ends with 500 cards until full import |

```powershell
# Local test on Neon dev (~500 cards, not full scrape)
python -m ygo_app.jobs.scrape_yugipedia_catalog --passcodes-only --max-cards 500
python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only --resume --batch-index 0 --batch-count 1
python -m ygo_app.jobs.import_catalog_yugipedia --limit 500
```

GHA test: **Run workflow** (new run, **not** Re-run failed jobs) → branch **`develop`** → `environment=dev` → `test_mode=true` → `card_limit=500`. Skips scrape batches 1–5; import uses `always()` in workflow `if`. After test, run a **full** import to restore ~14k cards on dev.

### Fallback catalog

```powershell
python -m ygo_app.jobs.import_catalog
```

---

## 6. Environment variables

| Variable | Local | Render / GHA |
|----------|-------|----------------|
| `DATABASE_URL` | Neon **dev** (`.env`) | Render **ygo-app** (prod) · GHA when `environment=production` |
| `DATABASE_URL_DEV` | — | GHA when `environment=dev` |
| `ENV` | `production` (parity) or unset → SQLite | `production` |
| `SECRET_KEY` | any local | Render per service |

**GitHub secrets (GHA):** value must be the **raw Neon pooled URL** only — `postgresql://user:pass@ep-xxx-pooler.../neondb?sslmode=require`. No quotes, no `DATABASE_URL=` prefix, no extra whitespace. Copy from Neon Console → **Pooled connection**.

---

## 7. Deploy / catalog checklist

| Step | Action |
|------|--------|
| 1 | Neon **main** + **dev**; GitHub secrets `DATABASE_URL`, `DATABASE_URL_DEV` (raw pooled URLs) |
| 2 | Workflows on `main`; **same** `import-catalog-yugipedia.yml` on `develop` (sync after edits) |
| 3 | **Import Yugipedia catalog** — branch **`develop`**, environment **`dev`**; full **~2–4 h** or **test_mode** ~30–60 min; each active batch `[BATCH_RESULT] missing=0` |
| 4 | Verify Neon dev (`SELECT COUNT(*) FROM cards` — ~500 test or ~14k full); spot-check `image_url LIKE '%ms.yugipedia.com%'`; UI loads art from Yugipedia CDN |
| 5 | Merge **`develop` → `main`** when ready for prod **app** |
| 6 | **Import Yugipedia catalog** — branch **`main`**, environment **production** |

---

## 8. Resolved issues (reference)

| Issue | Fix |
|-------|-----|
| GHA `Could not parse SQLAlchemy URL` | Malformed GitHub secret; fix secret format or use `config.py` normalization |
| One printing per set (multi-rarity) | `extract_rarities_from_cell` — all `<a>` in rarity cell |
| Actions missing Yugipedia workflow | Workflows must exist on `main`; run with branch `develop` for code |
| Workflow YAML out of sync on `main`/`develop` | Workflow-only sync commit; see Cursor rule + §2 |
| `pathspec ...-dev.yml did not match` | Dev workflow file never on remote; use main workflow + `environment=dev` |
| Search stuck on Render | Paginated search + batch summaries |
| Quoted phrase still matched scattered words | Replaced FTS/`plainto_tsquery` with `search_query` ILIKE phrase compiler |
| Search `total` wrong on large result sets | `COUNT` uses same `compile_filter` as results (no FTS `LIMIT` on ID list) |
| `varchar(16)` | Migration `002` |
| GHA scrape canceled at 180 min | Split into chained jobs (`BATCH_COUNT=6`); per-job timeouts 60–90 min |
| Scrape appeared stuck / no visibility | `[HEARTBEAT]`, `[FAIL]`, `[BATCH_RESULT]`; pool + batch retries |
| GHA import `ForeignKeyViolation` on `printings` | Detach/re-link `collection_items.printing_id` in `import_cards_entries`; run workflow from **`develop`** (not Re-run old job) |
| GHA import skipped after test `scrape_batch_0` | `import` job needs `always()` when `scrape_batch_5` skipped (`3ef9be1`) |
| Re-run still runs old `Printing.delete()` code | **Run workflow** picks new commit; Re-run reuses original SHA |
| JSON has no `image_url` / UI shows YGOPRODeck art | Pre-2026-06-04 scrape; re-run details scrape + import; confirm `yugipedia_all_cards.json` entries include `image_url` |
| Confusion with `yugipedia/get_images.py` | That script downloaded YGOPRODeck files locally; real URLs come from `parsing.extract_card_image` |

---

## 9. Do not do without user ask

- Edit `.cursor/plans/*.plan.md`
- Run deprecated `yugipedia/get_images.py` — it downloaded from YGOPRODeck, not Yugipedia; use `ygo_app/yugipedia/parsing.py` + import job instead
- Manually delete Neon `cards`/`printings` before import
- Run Yugipedia GHA with branch **`main`** before `ygo_app/yugipedia/` is on `main`
- Commit `.env`, secrets, or `data/catalog/*.json`
- Edit `import-catalog-yugipedia.yml` on one branch only without syncing the other
- Use Render free Postgres

---

## 10. Quick verification

| Check | Expected |
|-------|----------|
| `GET /api/health` | `{"ok": true}` |
| `GET /api/status` | `ready: true`, `cards` TCG-printed only (full count &lt; old ~14k passcodes; ~500 in `test_mode`) |
| GHA log | `Catalog import complete: N cards, M printings` |
| GHA scrape (full) | Green: `passcodes`, `scrape_batch_0`…`5`, `import`; ~2–4 h; each batch `[BATCH_RESULT] missing=0` |
| GHA scrape (test) | Green: `passcodes`, `scrape_batch_0`, `import`; batches 1–5 skipped; ~500 cards in Neon dev |
| Multi-rarity | Same `set_code`, different `set_rarity` (e.g. RA03-EN172) |
| `yugipedia_all_cards.json` | Entries include `image_url` + `image_url_small` on `ms.yugipedia.com` after re-scrape |
| `GET /api/cards/{passcode}` | `image_url` host is `ms.yugipedia.com` (not `images.ygoprodeck.com`) post re-import |
| `GET /api/cards/search?q=reveal` | Cards whose name/desc/archetype contain `reveal` |
| `GET /api/cards/search?q="You can reveal"` | Only cards with that contiguous phrase (case-insensitive) |
| `python -m unittest discover -s tests` | All pass (includes `test_search_query.py`, `test_search_cards.py`, `test_yugipedia_images.py`) |
