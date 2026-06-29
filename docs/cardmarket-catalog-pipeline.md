# Cardmarket catalog pipeline

Official Cardmarket product catalog and price guide JSON files replace the legacy web scraper.

## Flow

1. **Download** — `downloads.s3.cardmarket.com` Yu-Gi-Oh JSON (game id `3`)
2. **Archive** — zip raw files + manifest → R2 `ygo-cardmarket/archives/{timestamp}.zip`
3. **Map expansions** — `tcg_sets.name` contained in `products_nonsingles` product names → `idExpansion`
4. **Match printings** — singles by expansion + card name; rarity guessed from price order vs `rarity_price_ranks`
5. **Import** — SCD Type 2 rows in `printing_market_prices`

## Local commands

```powershell
# Dry run: download + match + export (no DB import, no R2)
python -m ygo_app.jobs.sync_cardmarket_catalog --skip-import --skip-r2

# Full local sync (requires DATABASE_URL + optional S3_* for R2)
python -m ygo_app.jobs.sync_cardmarket_catalog

# Import existing export JSON only
python -m ygo_app.jobs.import_cardmarket_prices --file data/catalog/cardmarket_prices.json
```

## GitHub Actions

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| [`sync-cardmarket-catalog.yml`](../.github/workflows/sync-cardmarket-catalog.yml) | Weekly Sun 04:00 UTC | Full pipeline |
| [`import-cardmarket-prices.yml`](../.github/workflows/import-cardmarket-prices.yml) | Manual | Re-import latest R2 export only |

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
  - If card names overlap across candidates → require compatible prices (`trend`, `avg`, `low`; equal or complementary nulls); conflicting non-null values → **fatal error** unless one expansion has strictly more priced Yugipedia card matches (dominant expansion keeps the price at printing-match time)
  - If validation passes → keep **all** remaining candidate `idExpansion` values (printing match unions singles across them)
- Zero matches or unresolved conflicts → **fatal error** (job fails)

### Card + rarity

Per Yugipedia set, group `printings` by card. Match Cardmarket singles (`idCategory = 5`) by any mapped `idExpansion` + normalized card name.

- Count of CM products must equal count of Yugipedia printings for that card in the set
- Sort CM by `trend`, then `avg`, then `idProduct` ascending
- Sort Yugipedia printings by `rarity_price_ranks.sort_order`
- Pair 1:1; tied CM prices → **fatal error**

## Error checklist

| Error | Action |
|-------|--------|
| `ExpansionMappingError` | Check set name vs nonsingle product names; add/adjust `tcg_sets.name` or report Cardmarket data issue |
| `PrintingCountMismatchError` | Yugipedia printings ≠ CM singles for a card — verify catalog freshness or set contents |
| `AmbiguousPriceOrderError` | Two CM variants with identical sort keys — manual review required |
| Download failure | S3 URL may have changed; update `DEFAULT_URLS` or HTML discovery fixtures |

## Legacy scraper

The browser/HTTP scraper is archived under [`archive/legacy_cardmarket_scrape/`](../archive/legacy_cardmarket_scrape/).
