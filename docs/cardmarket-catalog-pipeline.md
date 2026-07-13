# Cardmarket catalog pipeline

Official Cardmarket product catalog and price guide JSON files replace the legacy web scraper.

## Flow

1. **Download** — `downloads.s3.cardmarket.com` Yu-Gi-Oh JSON (game id `3`)
2. **Archive** — LZMA zip raw files + manifest → R2 bucket `ygo-cardmarket`, key `archives/{YYYY}/{MM}/{DD}/{HHMM}/catalog_archive.zip`
3. **Run log** — Brotli-compressed job log → R2 key `archives/{YYYY}/{MM}/{DD}/{HHMM}/sync_price_log.log.br` (same UTC run folder as zip)
4. **Pipeline report** — Brotli-compressed rejections + import gate → R2 key `archives/{YYYY}/{MM}/{DD}/{HHMM}/sync_price_report.json.br`
5. **Map expansions** — `tcg_sets.name` contained in `products_nonsingles` product names → `idExpansion`
6. **Match printings** — singles by expansion + card name; rarity guessed from price order vs `rarity_price_ranks`
7. **Import gate** — validate export for duplicate keys and missing required fields before DB write
8. **Import** — SCD Type 2 rows in `printing_market_prices`

Expansion mapping and printing match **reject** individual sets/cards and continue. Only download failures, import-gate failures, and infrastructure errors fail the job.

## Local commands

```powershell
# Dry run: download + match + export (no DB import, no R2)
python -m ygo_app.jobs.sync_cardmarket_catalog --skip-import --skip-r2

# Full local sync (requires DATABASE_URL + optional S3_* for R2)
python -m ygo_app.jobs.sync_cardmarket_catalog

# Import existing export JSON only
python -m ygo_app.jobs.import_cardmarket_prices --file data/catalog/cardmarket_prices.json
```

## Local artifacts

| File | Purpose |
|------|---------|
| `data/logs/sync_cardmarket_catalog_*.log` | Full job trace |
| `data/catalog/cardmarket_raw/sync_summary.json` | Run result (written every run) |
| `data/catalog/cardmarket_raw/pipeline_report.json` | Structured rejections + import gate |

## R2 artifacts

Bucket: `ygo-cardmarket` (`S3_CARDMARKET_BUCKET`). Each sync run uses folder `archives/{YYYY}/{MM}/{DD}/{HHMM}/` (UTC from `YYYYMMDD_HHMM`).

| Key | Content |
|-----|---------|
| `archives/{YYYY}/{MM}/{DD}/{HHMM}/catalog_archive.zip` | Raw catalog JSON + manifest (ZIP_LZMA) |
| `archives/{YYYY}/{MM}/{DD}/{HHMM}/sync_price_log.log.br` | Job log for triage (Brotli) |
| `archives/{YYYY}/{MM}/{DD}/{HHMM}/sync_price_report.json.br` | Rejections and import gate (Brotli) |
| `archives/{YYYY}/{MM}/{DD}/{HHMM}/cardmarket_prices.zip` | Matched export (`cardmarket_prices.json` inside, ZIP_LZMA) |

Legacy flat keys (`archives/cardmarket_prices_{YYYYMMDD}_{HHMM}.zip`, etc.) are still readable until removed from R2.

## GitHub Actions

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| [`sync-cardmarket-catalog.yml`](../.github/workflows/sync-cardmarket-catalog.yml) | Weekly Sun 04:00 UTC | Full pipeline |
| [`import-cardmarket-prices.yml`](../.github/workflows/import-cardmarket-prices.yml) | Manual | Re-import latest `archives/.../cardmarket_prices.zip` from R2 |

Scheduled runs target **production** Neon. Use `workflow_dispatch` with `environment=dev` for testing.

## Matching rules

### Expansion mapping

For each `tcg_sets` row with `region = 'TCG'`:

- **Skip** sets whose name contains **Championship** and **prize card(s)** — not mapped, not fatal
- **Skip** **Collectible Tins** sets entirely — not mapped, not fatal
- **Skip** sets whose name contains **promotional** or **participation** — not mapped, not fatal
- **Skip** sets with **fewer than 2** Yugipedia cards (0 or 1 distinct `card_id` in `printings`) — not mapped, not fatal
- **Ignore** nonsingle products whose name contains `Rush Duel`, a **1–4 letter alphabetic regional code in parentheses** (e.g. `(MIP)`, `(LDD)`), `Booster SP`, `Gold Series 2013`, `Gold Series 2014`, `OCG`, `Japan`, `Deck Build Pack`, `Korean`, `25th Anniversary Edition`, `Sacred Beasts of Chaos`, `promotional`, `participation`, or condition markers (`(non-sealed)`, `(BI`, `(MI`, `(DI`, `(DD`); skip matching products with those markers, and exclude their entire `idExpansion` when the marker is regional/condition (`(BI`–`(DD`) or another expansion-level rule — `(non-sealed)` is row-only and does not poison the expansion
- Drop nonsingle hits when the product name contains **Speed Duel**, **OTS**, or **Structure Deck** but the Yugipedia set name does not
- Normalize Yugipedia set name before matching: Advent Calendar `(YYYY)` → `Advent Calendar YYYY`; strip leading `Yu-Gi-Oh!` and trailing `prize card` / `prize cards`; apply Unicode NFKC (e.g. curly apostrophes)
- For listed abbrs (Gold Series, Hidden Arsenal, Legendary Collection, classic Starter Decks, Starter Deck 5D's, Dragons of Legend, Legendary Duelists base set, **STP5/STP6**, **SDWS**), use **manual Cardmarket name aliases** in [`expansion_aliases.py`](../ygo_app/cardmarket/catalog/expansion_aliases.py) instead of generic set-name containment (STP5/STP6: Cardmarket uses `Speed Duel: Tournament Pack N` instead of `Speed Duel Tournament Pack N`)
- Find remaining nonsingle products whose `name` contains the normalized set name (case-insensitive), with:
  - **Digit boundary** — when the set name ends in a digit, the product must not continue with another digit (e.g. `OTS Tournament Pack 1` ≠ `OTS Tournament Pack 10`)
  - **Colon subtitle guard** — when the set name has no `:`, reject products where the match is immediately followed by `:` and a subtitle (e.g. `Legendary Duelists` ≠ `Legendary Duelists: Ancient Millennium`)
- If no match, retry with alternate needles: **Structure Deck: {Title}**, **Dark Revelation N** (from `Volume N`), **{subtitle}** (from `Legendary Duelists: {subtitle}`), **{Title} Starter Deck** (from `Starter Deck: …`)
- All matches must share the same `idExpansion`, or be **merged** using singles + price guide when multiple expansions belong to one Yugipedia set:
  - Drop candidate expansions with no priced Yugipedia card matches in CM singles
  - If card names overlap across candidates → require compatible prices (`trend`, `avg`, `low`; equal or complementary nulls); conflicting non-null values → **reject set** unless one expansion has strictly more priced Yugipedia card matches (dominant expansion keeps the price at printing-match time)
  - If validation passes → keep **all** remaining candidate `idExpansion` values (printing match unions singles across them)
- Zero matches or unresolved conflicts → **reject set** (logged in `pipeline_report.json`; pipeline continues)

### Card + rarity

Per Yugipedia set, group `printings` by card. Match Cardmarket singles (`idCategory = 5`) by any mapped `idExpansion` + normalized card name.

- **Regional variants** — Yugipedia printings that share the same card, rarity, and collector number but differ only by regional prefix (e.g. `LOD-078` and `LOD-EN078`) are collapsed to one **representative** slot before counting. The representative prefers the `-EN` form. After price pairing, the matched Cardmarket product's prices are **broadcast** to every variant in that slot. Cardmarket does not distinguish these regional codes; one CM single covers all.
- **Print-design variants** — Cardmarket may list multiple `idProduct` rows for the same card name when alternate physical designs exist (e.g. 25LP **Emblazoned** vs normal). The website shows these as V.1–V.4, but the S3 JSON has only the plain card `name`. Before counting, rows are split into consecutive `idProduct` runs separated by a major gap; when structure is unambiguous, one batch is kept:
  - One run matches the Yugipedia representative count → use that run (e.g. RA05 7-block).
  - Two equal-sized runs (e.g. 25LP normal vs emblazoned pairs) → keep the run with lower total `avg` price (normal printing; emblazoned is not a separate Yugipedia slot).
  - Prefix pair + main block (e.g. RA05 9→7) → drop the small prefix, keep the main block.
  - Unrecognized structure → no collapse; existing `count_mismatch` rejection applies.
- **Duplicate CM listings** — when multiple Cardmarket singles share the same `idMetacard`, sparse re-listings without `avg` are dropped in favor of rows with price data. Multi-design resolution is handled by print-variant collapse above.
- Count of CM products must equal count of **representative slots** (after regional collapse) for that card in the set
- Sort CM by `trend`, then `avg`, then `idProduct` ascending
- Sort representative slots by `rarity_price_ranks.sort_order`
- Pair 1:1; tied CM prices → **reject card** (logged; other cards in the set still export)

## Import gate

Before writing to `printing_market_prices`:

| Check | Result |
|-------|--------|
| Duplicate `(set_code, rarity_code)` | **Block import** (exit 1) |
| Missing `set_code`, `rarity_code`, or `discovery_status` | **Block import** |
| All price fields null | **Allow** (metadata-only SCD row) |
| Empty export | **Allow** (no-op import) with warning |

Export JSON is still uploaded to R2 when the gate fails so you can inspect bad rows.

## Error checklist

| Issue | Action |
|-------|--------|
| Expansion mapping rejections | Check `sync_price_log.log.br` and `sync_price_report.json.br` in the run folder under `archives/{YYYY}/{MM}/{DD}/{HHMM}/`; adjust `tcg_sets.name` or aliases |
| Printing count mismatch | Yugipedia printings ≠ CM singles for a card after variant collapse — verify catalog freshness or inspect `extra.cm_id_products` / `extra.id_gaps` in the report |
| Ambiguous price order | Two CM variants with identical sort keys — manual review in report |
| Import gate duplicate keys | Bug in export builder — inspect `cardmarket_prices.json` |
| Download failure | S3 URL may have changed; update `DEFAULT_URLS` or HTML discovery fixtures |

## Legacy scraper

The browser/HTTP scraper is archived under [`archive/legacy_cardmarket_scrape/`](../archive/legacy_cardmarket_scrape/).
