# Formats, banlists, and deck validation

## Overview

The app supports six Yu-Gi-Oh! formats with warn-only deck validation, format-aware search, and monthly data sync jobs.

| Format | Banlist | Point list | Card pool |
|--------|---------|------------|-----------|
| Advanced TCG | Selectable (latest default) | — | All cards |
| Traditional | Selectable | — | All cards |
| Edison | Fixed March 2010 | — | `card_format_legality` (≤ 2010-04-20) |
| Goat | Fixed April 2005 | — | `card_format_legality` (≤ 2005-02-24) |
| Speed Duel | None | — | `card_format_legality` (Speed Duel printings) |
| Genesys | None | Selectable | All (no Link/Pendulum) |

## Database tables

- `formats` — seeded format metadata and descriptions
- `banlist_revisions` / `banlist_entries` — Konami EU F&L JSON
- `genesys_point_lists` / `genesys_point_entries` — Yugipedia point lists
- `card_format_legality` — precomputed pool flags (Speed Duel, Edison, Goat)
- `decks.format_code`, `decks.banlist_revision_id`, `decks.genesys_point_list_id`

## Jobs

```powershell
# Full banlist backfill (first run)
python -m ygo_app.jobs.sync_banlists

# Monthly incremental (skip stored revisions)
python -m ygo_app.jobs.sync_banlists --skip-existing

# Genesys point lists (live Yugipedia crawl)
python -m ygo_app.jobs.sync_genesys_points

# Genesys from local HTML fixture
python -m ygo_app.jobs.sync_genesys_points --fixture "DO NOT DELETE/genesys_point_list_html_code.html"

# Refresh Speed Duel / Edison / Goat legality (runs after catalog import in GHA)
python -m ygo_app.jobs.refresh_format_legality
```

### Local development

After running Alembic migration `015` (or any fresh catalog import), run `refresh_format_legality` locally. Search for Edison, Goat, and Speed Duel reads from `card_format_legality`; without this job the table is empty and format-filtered search is slow or returns no results.

```powershell
python -m ygo_app.jobs.refresh_format_legality
```

GHA runs this automatically at the end of `import-catalog-yugipedia.yml`; local dev must run it manually once per environment.

## Adding a new format

1. Add row to `FORMAT_ROWS` in `alembic/versions/015_formats_banlists.py` (or new migration).
2. Register rules in `ygo_app/formats/registry.py`.
3. If the format needs a custom card pool, extend `refresh_format_legality.py` or add dynamic pool logic in `ygo_app/formats/pool.py`.
4. Format appears automatically in `GET /api/formats` and the UI dropdowns.

## API

- `GET /api/formats` — list formats with zone tooltips
- `GET /api/formats/{code}/banlists` — banlist revisions
- `GET /api/formats/genesys/point-lists` — Genesys point lists
- Deck endpoints return `validation` payload (errors, warnings, info)
- Search/card detail accept `format`, `banlist_revision_id`, `genesys_point_list_id`, `points_min`, `points_max`

## GitHub Actions

- `sync-banlists.yml` — 1st of month, 03:00 UTC
- `sync-genesys-points.yml` — 1st of month, 04:00 UTC
- `import-catalog-yugipedia.yml` — runs `refresh_format_legality` after catalog import
