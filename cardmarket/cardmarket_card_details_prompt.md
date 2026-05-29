<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Complete Specification for Cardmarket Card Details Scraper

## Overview

Create a Python script named **`cardmarket_card_details_scraper.py`** that extracts detailed price information for Yu-Gi-Oh! cards from Cardmarket.com.

***

## Input File

**File:** `cardmarket_card_list.json`

**Structure:**

```json
[
  {
    "expansion_id": 1433,
    "expansion_name": "2013 Zexal Collection Tin",
    "expansion_code": "ZTIN",
    "card_id": 260903,
    "card_name": "Number 20: Giga-Brilliant",
    "card_number": "V02",
    "card_rarity": "Ultimate Rare",
    "card_url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/2013-Zexal-Collection-Tin/Number-20-GigaBrilliant"
  }
]
```

**Input Validation:**

1. Check file exists - if not, display error and exit
2. Validate JSON is parsable - if not, display error and exit
3. Check file is not empty - if empty, display message and exit
4. Check for duplicate card_ids at startup:
    - If duplicates found: Display all duplicate card_ids (minimal format) and EXIT
    - Always re-check on resume (even if checkpoint exists)
5. Validate required fields exist for each card:
    - Required: `expansion_id`, `expansion_name`, `expansion_code`, `card_id`, `card_name`, `card_number`, `card_rarity`, `card_url`
    - If any field is missing: Reject as "Failed - Missing Input Data"
6. Validate expansion_code and card_number are not empty/null/whitespace:
    - If empty: Reject as "Failed - Missing Input Data"
7. Validate card_url format (starts with https://):
    - If invalid: Reject as "Failed - Missing Input Data"

***

## Data Extraction

**Target URL:** Each card's `card_url` from input file

**HTML Structure to Parse:**

```html
<dt class="col-6 col-xl-5">From</dt>
<dd class="col-6 col-xl-7">0,03 €</dd>

<dt class="col-6 col-xl-5">Price Trend</dt>
<dd class="col-6 col-xl-7"><span>1,35 €</span></dd>

<dt class="col-6 col-xl-5">30-days average price</dt>
<dd class="col-6 col-xl-7"><span>1,26 €</span></dd>

<dt class="col-6 col-xl-5">7-days average price</dt>
<dd class="col-6 col-xl-7"><span>1,33 €</span></dd>

<dt class="col-6 col-xl-5">1-day average price</dt>
<dd class="col-6 col-xl-7"><span>0,80 €</span></dd>
```

**Extraction Logic:**

1. Find `<dt>` tags by text content (case-insensitive partial match)
2. Get next sibling `<dd>` tag
3. Extract text (handles nested `<span>` tags automatically with `.get_text(strip=True)`)
4. Parse price value

**Price Fields to Extract:**

- From → `low_price`
- Price Trend → `trend_price`
- 30-days average price → `avg_30_price`
- 7-days average price → `avg_7_price`
- 1-day average price → `avg_1_price`

**Price Parsing Rules:**

1. Remove spaces and € symbol
2. Handle thousands separators: `9.999,99 €` → Remove dots (thousands)
3. Convert decimal comma to dot: `0,03` → `0.03`
4. Convert to float: `0.03`
5. Accept `0,00 €` as valid 0.00
6. Reject if any of these conditions:
    - Value is "N/A"
    - Value is "--" or "---"
    - Value is not a valid number
    - ANY of the 5 price fields fails parsing

**Rejection Criteria:**

- If ANY price field is missing/N/A/invalid → Reject as "Failed - missing data"
- If site is unreachable (HTTP errors) → Reject as "Failed - site unreachable"
- If expansion_code or card_number is empty → Reject as "Failed - missing input data"

***

## Output Files

### 1. `cardmarket_card_details.json` (Successful Cards)

**Structure:**

```json
[
  {
    "card_data": {
      "card_id": 260903,
      "card_name": "Number 20: Giga-Brilliant",
      "card_rarity": "Ultimate Rare",
      "card_number": "V02",
      "card_set_number": "ZTIN-ENV02"
    },
    "expansion_data": {
      "expansion_id": 1433,
      "expansion_name": "2013 Zexal Collection Tin",
      "expansion_code": "ZTIN"
    },
    "price_data": {
      "url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/2013-Zexal-Collection-Tin/Number-20-GigaBrilliant",
      "low_price": 0.03,
      "trend_price": 1.35,
      "avg_30_price": 1.26,
      "avg_7_price": 1.33,
      "avg_1_price": 0.80,
      "price_date": "2025-10-26",
      "currency": "EUR"
    }
  }
]
```

**Field Details:**

- `card_set_number`: Concatenated as `{expansion_code}-EN{card_number}` (always use "-EN")
- `price_date`: Current date in ISO format (YYYY-MM-DD), no time/timezone
- `currency`: Always "EUR"
- All prices stored as floats (not strings)
- Pretty-printed with 2-space indent
- Preserve input order (don't sort)


### 2. `cardmarket_card_details_rejection.json` (Failed Cards)

**Structure:**

```json
[
  {
    "card_id": 260903,
    "card_name": "Number 20: Giga-Brilliant",
    "card_url": "https://...",
    "expansion_id": 1433,
    "expansion_name": "2013 Zexal Collection Tin",
    "expansion_code": "ZTIN",
    "rejection_reason": "Failed - site unreachable",
    "error_detail": "HTTP 403 Forbidden",
    "timestamp": "2025-10-26T23:30:00",
    "attempts": 3
  }
]
```

**Rejection Reasons:**

1. "Failed - site unreachable" (HTTP errors: 403, 404, 429, 500, 503, timeout)
2. "Failed - missing data" (prices N/A, invalid HTML parsing)
3. "Failed - missing input data" (empty expansion_code/card_number)

**Notes:**

- Phase 2 can update rejection_reason if it changes
- Pretty-printed with 2-space indent
- Preserve processing order


### 3. Checkpoint Files

**`cardmarket_card_details_checkpoint.json`** (Phase 1 progress)

```json
{
  "last_processed_index": 12345,
  "phase1_complete": false
}
```

**`cardmarket_card_details_recovery_checkpoint.json`** (Phase 2 progress)

```json
{
  "last_processed": 50
}
```


***

## Architecture

### Two-Phase Approach

**Phase 1: Fast Main Run**

- **Workers:** 16 parallel workers
- **Speed:** 6 requests/second total
- **Retries:** 2 attempts per card
- **Retry Delay:** 8-12 seconds (random)
- **Expected Time:** ~3-4 hours for 74,000 cards
- **Outcome:** Successful cards, rejected cards (both types)

**Phase 2: Careful Recovery**

- **Workers:** 1 single-threaded
- **Speed:** 1 request/second
- **Retries:** 5 attempts per card
- **Retry Delay:** 10s, 20s, 30s, 40s, 50s (exponential backoff)
- **Session:** Fresh session per card with warmup
- **Scope:** ONLY retry "Failed - site unreachable" rejections
- **Skip:** "Failed - missing data" and "Failed - missing input data" (won't fix with retry)
- **Auto-skip:** If no "site unreachable" rejections, skip Phase 2 entirely


### Session Management

**CloudScraper Configuration:**

- Use CloudScraper (not requests) for anti-bot bypass
- Realistic browser headers (Chrome on Windows)
- Session pooling: One session per worker
- Session reuse: Up to 10 requests per session
- Session refresh: After 403 errors
- No session warmup (go straight to card URLs for speed)


### Rate Limiting

**Phase 1:**

- Global rate limiter: 6 requests/second across all 16 workers
- Random jitter: 0-0.3 seconds added to each request
- No delay between retries (retry delay is separate)

**Phase 2:**

- 1 request/second
- Exponential backoff on retries


### HTTP Error Handling

**403 Forbidden:**

- Refresh session immediately
- Wait 30-45 seconds (random)
- Retry (up to max retries)
- Mark as "Failed - site unreachable" after all retries

**404 Not Found:**

- Reject immediately as "Failed - site unreachable" (invalid URL)
- No retries (URL won't become valid)

**429 Rate Limited:**

- Wait 10 × attempt_number seconds
- Retry automatically
- Does NOT count toward max retries

**500/503 Server Error:**

- Wait 5 seconds
- Retry
- Mark as "Failed - site unreachable" after all retries

**Connection Timeout:**

- Mark as "Failed - site unreachable"
- Retry normally


### Progress Management

**Checkpoint System:**

- Save progress every 100 cards (processed count)
- Track Phase 1 completion flag
- Track Phase 2 progress separately
- On resume: Load checkpoint, skip processed cards
- Handle checkpoint file corruption: Ignore and start fresh with warning

**Incremental Saves:**

- Save successful cards every 100 cards
- Save rejections every 100 cards
- Update checkpoint every 100 cards
- On crash: Only lose <100 cards

**Resume Logic:**

- Always re-check for duplicates (even on resume)
- Load existing output files and merge (avoid duplicate card_ids)
- Skip already-processed card indices
- Continue from last checkpoint

**Keyboard Interrupt (Ctrl+C):**

- Catch KeyboardInterrupt
- Save all current progress immediately
- Display status message
- Exit gracefully


### File I/O Safety

**Thread Lock:**

- Use `threading.Lock()` for all file writes
- Prevents race conditions with parallel workers
- Ensures atomic file operations

***

## Console Output

**Progress Display Format (Every 10 cards):**

```
[12345/74000] Expansion: 1433 | Card: 260903 | Set: ZTIN-ENV02 | ✓ Success | Progress: 16.7% | Speed: 1850/h | Remaining: 2h 45m
```

Or for failures:

```
[12346/74000] Expansion: 1433 | Card: 260904 | Set: ZTIN-ENV03 | ✗ Failed (missing data) | Progress: 16.7% | Speed: 1850/h | Remaining: 2h 45m
```

**Components:**

- **[12345/74000]:** Cards processed / Total cards
- **Expansion:** expansion_id
- **Card:** card_id
- **Set:** card_set_number (concatenated)
- **Status:** ✓ Success / ✗ Failed (with reason)
- **Progress:** Percentage complete
- **Speed:** Cards per hour (current rate)
- **Remaining:** Estimated time remaining (ETA)

**ETA Calculation:**

- First 100 cards: Show "ETA: Calculating..."
- After 100 cards: Calculate based on average speed
- Update every 10 cards

**Final Summary (After completion):**

```
======================================================================
 FINAL SUMMARY
======================================================================
Total cards processed: 74,000
Successful: 68,500
Rejected: 5,500
  - Failed (site unreachable): 1,200
  - Failed (missing data): 3,800
  - Failed (missing input data): 500

Phase 1 rejections: 8,000
Phase 2 recovered: 2,500
Final rejections: 5,500

Duration: 3h 42m
Average speed: 19,945 cards/hour
======================================================================
```

**Statistics Tracked:**

- Total cards processed
- Successful cards
- Total rejections (by type)
- Phase 1 rejections
- Phase 2 recovered count
- Final rejection count
- Total duration
- Average speed (cards/hour)

***

## Technical Implementation Notes

**Use Previous Script Concepts:**

- Session pooling from `cardmarket_card_list_scraper.py`
- Rate limiter class from `cardmarket_card_list_scraper.py`
- Two-phase architecture from `cardmarket_card_list_scraper.py`
- CloudScraper setup from `cardmarket_expansion_list_scraper.py`
- Checkpoint system from `cardmarket_card_list_scraper.py`
- Threading with ThreadPoolExecutor
- File locking for concurrent writes
- Error handling patterns from previous scripts

**Expected Performance:**

- Input: ~74,000 cards
- Phase 1: ~3.5 hours (16 workers, 6 req/sec)
- Phase 2: Variable (depends on rejections)
- Total: ~4-5 hours for complete run

***

## Summary of All Requirements

✅ Input validation (file exists, valid JSON, not empty, required fields, no duplicates)
✅ Two-phase scraping (fast + recovery)
✅ 16 workers, 6 req/sec (aggressive speed)
✅ Price extraction from 5 fields (From, Trend, 30-day, 7-day, 1-day)
✅ Price parsing (comma→dot, remove €, handle thousands, store as float)
✅ Reject if ANY price is N/A or invalid
✅ Reject if expansion_code or card_number is empty
✅ card_set_number format: {code}-EN{number}
✅ Output structure with card_data, expansion_data, price_data
✅ Rejection file with detailed error info
✅ Checkpoint system (save every 100 cards)
✅ Resume capability (merge with existing, skip duplicates)
✅ Phase 2 only retries "site unreachable"
✅ Console progress (readable format, every 10 cards, with ETA)
✅ HTTP error handling (403/404/429/500/503)
✅ Keyboard interrupt handling (Ctrl+C)
✅ Final summary statistics
✅ Thread-safe file writes
✅ CloudScraper with realistic headers

***

This complete specification covers all gaps discussed and is ready for implementation.

