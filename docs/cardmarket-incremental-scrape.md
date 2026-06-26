# Cardmarket incremental scrape — step-by-step guide

> **Scenario:** You completed a **full** Cardmarket scrape earlier (e.g. July 2026). Months later (e.g. October 2026), Cardmarket has **new expansions**. You want to scrape only those expansions, their cards, and prices — then update the database — without re-running the entire catalog.

**Last updated:** 2026-06-23

---

## What incremental mode does

1. Fetches the **live** expansion dropdown from Cardmarket (one HTTP request).
2. **Diffs** it against your stored `cardmarket_expansion_list.json`.
3. Scrapes **card lists** only for **new** expansion IDs (and expansions detected as **ID migrations**).
4. Scrapes **detail pages / prices** only for **new cards** in those expansions.
5. **Merges** results into your existing JSON artifacts with validation (no duplicate parent expansions or ambiguous price mappings).
6. Writes a **full** `cardmarket_prices.json` ready for import (old + new prices).

**Out of scope (v1):** refreshing prices for cards you already scraped. For that, see [Full price re-sync](#optional-full-price-re-sync-all-cards) at the end.

---

## Prerequisites

### 1. Prior full scrape artifacts (required)

Incremental mode reads local JSON under `data/catalog/`. **Neon/DB alone is not enough.**

Confirm these files exist from your earlier full run:

| File | Role |
|------|------|
| `data/catalog/cardmarket_expansion_list.json` | Baseline expansion IDs |
| `data/catalog/cardmarket_card_list.json` | Baseline product list rows |
| `data/catalog/cardmarket_card_details.json` | Baseline detail/price rows |

If any are missing, run the [full 4-step pipeline](LOCAL_DEV.md#cardmarket-prices-local-scrape) first.

### 2. Yugipedia catalog (for export)

Export joins Cardmarket details with Yugipedia printings:

- `data/catalog/yugipedia_all_cards.json`

Refresh this if your app catalog changed since July (new sets in Yugipedia).

### 3. Environment

From the project root, with dependencies installed:

```powershell
cd "C:\Python Projects\YGO App Cursor"
pip install -r requirements.txt
```

Optional one-time Cloudflare cookie login (if browser sessions expire):

```powershell
python -m ygo_app.jobs.scrape_cardmarket_expansions --cf-login
```

### 4. Cardmarket reachable

Open https://www.cardmarket.com in your **normal browser** (not the scrape Chrome). If you see Cloudflare Error 1015 or constant 429s, wait or switch egress IP before scraping. See [docs/cloudflare/README.md](cloudflare/README.md).

---

## Recommended: one-command orchestrator

Use the same browser flags that work for you on job 2. Job 3 (prices) uses `--rps`; jobs 1–2 use `--discovery-rps`.

### Step 1 — Run incremental scrape

```powershell
python -m ygo_app.jobs.scrape_cardmarket_incremental `
  --browser --headed --polite `
  --browser-profiles default,alt1,alt2,alt3
```

**What you should see:**

- `[INCREMENTAL] scraping N expansion(s)` — if `N = 0`, nothing new was found (see [Nothing new](#step-3--review-the-run-report)).
- `[CARD_LIST] targeted scrape …` — product lists for new expansions only.
- `[DETAILS] …` — price pages for new cards only.
- `[EXPORT] wrote … cardmarket_prices.json`
- `[INCREMENTAL] complete — report at … cardmarket_incremental_report.json`

**Exit codes:** `0` success · `1` validation conflict or missing files · `2` rate-limit abort (wait, then re-run the same command).

### Step 2 — Upload prices to R2 (optional)

If you use R2 + GitHub Actions for import:

```powershell
python -m ygo_app.jobs.upload_cardmarket_prices
```

Then trigger the **Import Cardmarket prices** workflow in GitHub (or use Step 3 locally).

### Step 3 — Import into the database

**Local / Neon dev shortcut:**

```powershell
python -m ygo_app.jobs.import_cardmarket_prices -f data/catalog/cardmarket_prices.json
```

Ensure `.env` `DATABASE_URL` points at the branch you want (dev vs production).

### Step 4 — Review the run report

Open `data/catalog/cardmarket_incremental_report.json`:

```json
{
  "new_ids": [ … ],
  "migrations": [ { "old_id": …, "new_id": …, "reason": "…" } ],
  "orphaned_ids": [ … ],
  "scrape_ids": [ … ],
  "cards_scraped": 123,
  "details_scraped": 45,
  "status": "ok"
}
```

| Field | Meaning |
|-------|---------|
| `new_ids` | Expansion IDs on Cardmarket that were not in your July list |
| `migrations` | Cardmarket replaced an expansion ID (old cards purged, new ID scraped) |
| `orphaned_ids` | IDs removed from Cardmarket with no clear replacement (cards kept in JSON) |
| `cards_scraped` | New rows added to `cardmarket_card_list.json` |
| `details_scraped` | New detail/price rows added |

---

## Manual step-by-step (four jobs)

Use this if you want control between phases. **Do not** combine `--incremental` with `--resume`.

Shared browser flags (adjust to taste):

```powershell
$FLAGS = "--browser --headed --polite --browser-profiles default,alt1,alt2,alt3"
$PRICE_FLAGS = "--browser --headed --polite --browser-profiles default,alt1,alt2,alt3"
```

### Step A — Merge expansion list

Fetches live expansions and merges into your stored list (no full overwrite).

```powershell
python -m ygo_app.jobs.scrape_cardmarket_expansions --incremental $FLAGS
```

### Step B — Scrape card lists for new expansions only

```powershell
python -m ygo_app.jobs.scrape_cardmarket_card_list --incremental $FLAGS
```

### Step C — Scrape prices for new cards only

```powershell
python -m ygo_app.jobs.scrape_cardmarket_card_details --incremental $PRICE_FLAGS
```

### Step D — Export and import

```powershell
python -m ygo_app.jobs.export_cardmarket_prices --incremental
python -m ygo_app.jobs.import_cardmarket_prices -f data/catalog/cardmarket_prices.json
```

(`--incremental` on export runs duplicate match-key validation before writing.)

---

## If something goes wrong

### Validation conflict (exit code 1)

Read `data/catalog/cardmarket_incremental_conflicts.json`. Common types:

| Type | Meaning |
|------|---------|
| `duplicate_card_id` | Same Cardmarket product ID tied to two expansions |
| `duplicate_printing_key` | Same set number + rarity, different product IDs |
| `duplicate_match_key` | Two products would map to one Yugipedia printing in export |
| `ambiguous_migration` | A removed expansion matches multiple new IDs (manual review) |

Fix the underlying data or resolve on Cardmarket, then re-run Step 1.

### Rate limit / IP ban (exit code 2)

1. Stop scraping until https://www.cardmarket.com loads in your normal browser.
2. Optionally reset profile state: edit or delete `data/catalog/cardmarket_profile_state.json`.
3. Re-run the same incremental command (slower if needed: `--discovery-rps 0.05 --rps 0.05`).

Details: [cardmarket-scraper-behavior.md](cloudflare/cardmarket-scraper-behavior.md).

### Nothing new (`scrape_ids` empty)

Cardmarket’s dropdown matches your stored expansion list. The orchestrator still rebuilds `cardmarket_prices.json` from existing details. No new HTTP scraping for lists/details.

---

## Optional: full price re-sync (all cards)

To refresh **every** card’s prices (not incremental), re-run job 3 on the **full** card list without `--incremental`. Expect a long run (same order of magnitude as your original full details scrape).

```powershell
python -m ygo_app.jobs.scrape_cardmarket_card_details `
  --browser --headed --polite --resume `
  --browser-profiles default,alt1,alt2,alt3

python -m ygo_app.jobs.export_cardmarket_prices
python -m ygo_app.jobs.import_cardmarket_prices -f data/catalog/cardmarket_prices.json
```

---

## Quick command cheat sheet (October update scenario)

```powershell
# 1. Incremental scrape (new expansions + new prices + export)
python -m ygo_app.jobs.scrape_cardmarket_incremental --browser --headed --polite --browser-profiles default,alt1,alt2,alt3

# 2. Import to DB
python -m ygo_app.jobs.import_cardmarket_prices -f data/catalog/cardmarket_prices.json

# 3. Check report
# data/catalog/cardmarket_incremental_report.json
```

---

## Related docs

- [LOCAL_DEV.md — Cardmarket prices](LOCAL_DEV.md#cardmarket-prices-local-scrape)
- [cloudflare/cardmarket-scraper-behavior.md](cloudflare/cardmarket-scraper-behavior.md)
- [agent_handoff.md](../agent_handoff.md) — pipeline overview
