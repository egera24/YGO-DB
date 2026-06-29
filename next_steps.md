# Next steps

Working list of upcoming topics. Companion to [`future_must_have_features.md`](future_must_have_features.md) (long-term roadmap) — items here are nearer-term and get checked off / moved to the changelog in [`agent_handoff.md`](agent_handoff.md) when done.

> **Last updated:** 2026-06-30

---

## 1. Better-quality card images (DONE)

**Current state:** scrape picks the largest card art `<img>` on the Yugipedia card page (`parsing.extract_card_image`), mirrors it to Cloudflare R2 as WebP (full = quality 82, small = 150px) via `jobs/sync_card_images.py`.

**To research next session:**

- [ ] Audit what resolution Yugipedia actually serves — the page `<img>` is often a *thumb*; the original file behind `ms.yugipedia.com//thumb/...` (strip the `/thumb/` + size suffix) is usually much larger. Check whether `images.py` URL normalization already grabs the full original or a downscaled variant.
- [ ] Compare alternative sources for full-res art:
  - **YGOProDeck CDN** (`images.ygoprodeck.com/images/cards/{passcode}.jpg`) — 421×614 typical, plus `cards_cropped` art-only variant; easy (passcode-keyed) but ToS asks not to hotlink (we mirror anyway, so fine).
  - **Yugipedia original uploads** — often highest quality scans, already our metadata source.
  - **Konami official card database** — authoritative but scraping is brittle and likely against ToS.
- [ ] Decide target sizes: keep `-small` at 150px for table thumbnails, consider bumping full image quality (WebP q85–90) and/or storing a medium size for the card modal.
- [ ] Any change in source/size = update `sync_card_images.py` + `--force` re-mirror + re-import (URLs live in `cards` rows).

## 2. Login as landing page (no anonymous access) (DONE)

**Implemented 2026-06-18:**

- [x] Frontend: on load, call `/api/auth/me`; if not authenticated, render only login/register landing (hide tabs, search, everything). No data fetches until logged in.
- [x] Backend: auth dependency on formerly public routes (`/api/cards/search`, `/api/cards/{id}`, `/api/filters`, `/api/status`, summoning-suggestions, printings, by-set-code).
- [x] `/api/health` stays public for Render health checks.
- [x] Verification checklist in `agent_handoff.md` §12 updated.

## 3. URL reflects active page (routing) (DONE)

**Current state:** hash-based client routing in `app.js` — tabs, search filters, collection folder, deck detail, and card modal deep links.

**Implemented 2026-06-18:**

- [x] Hash routing (`#/search`, `#/collection`, `#/decks`) with back/forward and bookmarks.
- [x] Search params, collection `folder`, `#/decks/{id}`, `#/card/{passcode}` in the URL.
- [x] Tab a11y (`aria-selected`, `aria-controls`, `hidden` panels), `document.title` per view, URL param allowlist + length caps.
- [ ] Clean paths (`/collection` without `#`) — deferred; hash routing is sufficient for now.

## 4. Webapp speed improvements (DONE)

Implemented 2026-06-13 — see changelog in [`agent_handoff.md`](agent_handoff.md). Remaining ideas if still slow: Render keep-alive ping, virtualized lists, bundler/minifier.

## 5. Security review

**Likely fine already, but verify:**

- [ ] **SQL injection:** all queries go through SQLAlchemy ORM / bound parameters — audit `search_query.py` and `card_filters.py` to confirm no raw string interpolation into SQL (ILIKE patterns must be passed as bind params; escape `%`/`_` in user input used in LIKE).
- [ ] **Auth:** JWT secret strength (`SECRET_KEY` per environment), token expiry, bcrypt cost factor; no tokens in URLs/logs. **Done 2026-06-19:** production fail-fast if `SECRET_KEY` missing/default or `EMAIL_BACKEND=console`; signup password complexity (8+ chars, upper, number, special); OTP redacted from `logger.info` (terminal `print` unchanged for local dev).
- [ ] **Signup/login credentials in DevTools:** Is it normal that email and password are visible in the browser developer tools during register/login? **Yes — for the Network request Payload (or Request body), not the Response.** The browser must send credentials to the API; DevTools shows what *your* browser sends. This is standard for every web app and is **not** a server-side leak by itself. **Not a security issue when:** traffic uses **HTTPS** (Render enforces this in production); the password is **not** returned in API responses; the server stores **bcrypt** hashes only ([`ygo_app/auth.py`](ygo_app/auth.py)). **Real risks (same as any login form):** someone with access to your machine/DevTools, malware or browser extensions, exporting/sharing HAR files, typing password on an HTTP (non-TLS) site. **Verify:** register/login responses contain `needs_verification` or `access_token` only — never the password; local `run.py` uses HTTP on localhost (acceptable for dev only).
- [x] **Local signup smoke test:** Re-test registration on `python run.py` with default `EMAIL_BACKEND=console` — after **Create account** or **Resend code**, confirm the 6-digit verification code prints in the **uvicorn terminal** (`VERIFICATION CODE for …` from [`ygo_app/email.py`](ygo_app/email.py)); complete the verify-email step in the UI. Restart the server after pulling latest code if the line does not appear.
- [ ] **Authorization (IDOR):** every collection/deck/preset endpoint must filter by `user_id` from the token — verify no endpoint trusts a client-supplied id to access another user's rows.
- [x] **Rate limiting / brute force:** `/api/auth/*` has per-IP and per-email limits (register, login, verify, resend) in [`ygo_app/rate_limit.py`](ygo_app/rate_limit.py) — **extended 2026-06-19:** per-email login limit + per-IP resend limit.
- [ ] **Input validation:** CSV import (size limits, malformed rows), preset `params` allowlist (exists — `SEARCH_PRESET_PARAM_KEYS`), folder/deck name lengths. **Partial 2026-06-19:** signup password rules; CSV import capped at 20 MB; deck/folder/preset `max_length=128`.
- [x] **Headers:** add security headers (`X-Content-Type-Options`, `Content-Security-Policy`, `X-Frame-Options`) via middleware; HTTPS enforced by Render. **Done 2026-06-19** in [`ygo_app/api/main.py`](ygo_app/api/main.py); `/docs` disabled in production.
- [ ] **XSS:** `app.js` builds DOM from API data — confirm card names/descriptions/notes are inserted via `textContent` (not `innerHTML`) everywhere.
- [ ] **Secrets hygiene:** `.env` + `DO NOT DELETE/SECRETS/` are gitignored — periodically verify nothing leaked into git history.
- [ ] Optional: run `pip-audit` / `bandit` for dependency and static analysis checks.

## 6. Errata & tips — bugs to fix

**Current state:** Yugipedia supplements (migrations 010/011) power `has_errata`, `errata[]`, `tips[]` on card detail; card modal teasers + nested modals in [`app.js`](ygo_app/static/js/app.js). Parser in [`errata.py`](ygo_app/yugipedia/errata.py); API helpers in [`card_detail_extras.py`](ygo_app/yugipedia/card_detail_extras.py).

### 6.1 Stale Tips/Errata buttons on card navigation

**Symptom:** Opening another card from the search pane leaves the previous card's Tips button and errata teaser visible until the new card loads (or after an API error).

**Root cause:** `renderModalSupplements()` only runs after a successful `GET /api/cards/{id}`. `openCardModal()` resets name/skeleton but never hides `#modal-errata-teaser` / `#modal-tips-trigger` at navigation start.

- [x] Add `resetModalSupplements()`; call from `openCardModal()`, `renderModalSkeleton()`, and the error catch
- [x] Close errata/tips child modals when switching cards in `openCardModal()`
- [x] Dim supplement controls under `.modal-card.modal-loading`
- [x] Bump static `?v=` in `index.html`

**Verify:** Open card with errata + tips → click search result without either → buttons hidden immediately during skeleton. Open errata popup → switch card → popup closes.

### 6.2 English-only errata (no Japanese fallback)

**Symptom:** Cards with only Japanese errata on Yugipedia show Japanese text in the errata modal; set codes are EN TCG.

**Root cause:** `card_errata_for_api()` and `compute_errata_flags()` fall back to all languages when English is missing; scrape/import store every language.

- [x] Filter to `language == "English"` in scrape job before writing JSON
- [x] Skip non-English rows in `_errata_rows_for_entry()` on import
- [x] Remove API and `compute_errata_flags` fallbacks
- [x] Tests for no-English case
- [ ] Re-scrape supplements + re-import catalog on dev/prod (user/GHA — see §6.6)

### 6.3 Complete `<del>` errata text (Castle of Dark Illusions)

**Symptom:** First erratum columns with deletion-only `<del>` tags (no nested `<ins>`) show incomplete text when `lore_text` is used.

**Root cause:** `_lore_text_from_node` only kept text inside `<del><ins>…</ins></del>`, dropping bare `<del>` content.

- [x] Fix `_lore_text_from_node` to walk all `<del>` children
- [x] Extend Castle fixture test assertions on `lore_text`
- [ ] `alembic upgrade head` (migration 011) + supplements re-scrape + `import_catalog_yugipedia` to backfill `lore_html` on existing DB rows (see §6.6)

### 6.4 Yugipedia-faithful errata display (strikethrough, bold, italic)

**Goal:** Errata modal lore should match Yugipedia table cells — `<del>` strikethrough, `<ins>` underline, `<b>` bold, `<i>` italic, nested markup preserved.

**Pipeline:** Yugipedia HTML → `lore_html` in DB → API → `renderErrataModal()` `innerHTML` + `.errata-lore` CSS.

- [x] Treat `lore_html` as primary display path; show muted note when only `lore_text` available
- [x] Parser: normalize `strong`→`b`, `em`→`i` in `_serialize_lore_node`
- [x] Tests asserting `lore_html` for `del`/`ins`/`b`/`i` nesting (Castle, Abyss Dweller, Amazoness fixtures)
- [x] CSS: explicit `.errata-lore b` / `.errata-lore i`; nested `del ins` underline + strikethrough
- [ ] Manual side-by-side compare with Yugipedia for Castle of Dark Illusions (`33420043`), Abyss Dweller, Amazoness Paladin (after data backfill)

### 6.5 Empty Tips pages

**Expected:** When Yugipedia's Card_Tips page has no `<ul><li>` tips (404, timeout, or empty content), **no tips are stored in the DB** and the Tips button stays hidden.

| Stage | Result |
|-------|--------|
| Parse | `parse_tips_html()` → `[]` |
| Catalog JSON | `"tips": []` (marks card done on `--resume`) |
| Import | `_tips_json()` → `None` → `cards.tips` NULL |
| API / UI | `tips: []`, Tips button hidden |

The empty `tips: []` in catalog JSON is intentional — it distinguishes "scraped, none found" from "not yet scraped".

- [x] Document behavior (this section)
- [x] Fixture `tips_empty.html` + parser/scraper/import tests

### 6.6 Data backfill (user / GHA)

Required for `lore_html` and English-only errata on existing Neon rows:

```powershell
alembic upgrade head
python -m ygo_app.jobs.scrape_yugipedia_supplements
python -m ygo_app.jobs.import_catalog_yugipedia
```

Or GHA **Import Yugipedia catalog** on `develop` + `environment=dev` first.

**Test command:**

```powershell
python -m unittest tests.test_yugipedia_errata tests.test_yugipedia_tips tests.test_yugipedia_supplements tests.test_card_detail_supplements -v
```

## 7. "For trade" search filter

**Goal:** Add a third checkbox next to **Owned only** and **Favorites** on the Search tab — filters to cards where the logged-in user has `trade_quantity > 0`.

**Current state:** `trade_quantity` lives on `collection_items` ([`models.py`](ygo_app/models.py)); search already shows trade badges on tiles via `card_summaries_batch()`. No `for_trade_only` filter yet.

**Steps:**

- [ ] HTML: add `<input type="checkbox" id="for-trade-only" /> For trade` in [`index.html`](ygo_app/static/index.html) next to owned/favorites checkboxes.
- [ ] Frontend: wire `for_trade_only` in `ROUTE_SEARCH_KEYS`, `buildSearchParams()`, `resetSearchFilters()`, `applySearchParams()`, filter chips ([`app.js`](ygo_app/static/js/app.js)).
- [ ] Backend: add `for_trade_only: bool` query param on `GET /api/cards/search` ([`cards.py`](ygo_app/api/routes/cards.py)).
- [ ] Filter logic in `search_cards()` ([`services.py`](ygo_app/services.py)) — join `CollectionItem` like `owned_only`, add `CollectionItem.trade_quantity > 0`.
- [ ] Add `for_trade_only` to `SEARCH_PRESET_PARAM_KEYS` ([`schemas.py`](ygo_app/schemas.py)).
- [ ] Bump `?v=` on edited static assets in `index.html`.

**Verify:** Check **For trade** → only cards with trade qty appear; combine with Owned only; preset save/load preserves the flag.

---

## 8. Sell price column in folder view

**Goal:** Show the Sell Price column when viewing a specific folder in My Collection (currently hidden).

**Current state:** Data is rendered; CSS hides column 7 when `collection-table--in-folder` is set ([`style.css`](ygo_app/static/css/style.css) ~1335–1338; toggled in `renderCollectionTable()` in [`app.js`](ygo_app/static/js/app.js)).

**Steps:**

- [ ] Remove the `#collection-table.collection-table--in-folder … nth-child(7) { display: none }` rule from [`style.css`](ygo_app/static/css/style.css).
- [ ] Optionally remove the `collection-table--in-folder` class toggle if it is no longer needed for anything else.
- [ ] Bump `?v=` on `style.css` in `index.html`.

**Verify:** Open any folder → Sell Price column visible and matches **All** view values.

---

## 9. CSV import — Overwrite vs Append

**Goal:** Let the user choose import mode instead of always replacing the collection.

**Current state:** `import_collection_csv(..., replace=True)` in [`import_data.py`](ygo_app/import_data.py) supports `replace=False`, but the UI always calls `?replace=true` with a replace-only confirm ([`app.js`](ygo_app/static/js/app.js) ~5059).

**Append merge rule (decided):** When a CSV row matches an existing item (`user_id` + `set_code` + `rarity_code`):

| Field | Behavior |
|-------|----------|
| `quantity` | Add imported qty to existing |
| `trade_quantity` | Add imported trade qty to existing |
| `condition`, `edition`, `language`, `price_bought`, `date_bought`, `notes` | Update only if CSV cell is non-empty |
| `sell_price` | Do not overwrite from CSV (import already leaves it `None`) |
| Folder | Merge folder allocation qty if same folder name; else create allocation |

**Steps:**

- [ ] Import UI: modal or two-step confirm — **Overwrite** (current) vs **Append** (merge).
- [ ] Pass `replace=true|false` to `POST /api/collection/import-csv`.
- [ ] Implement merge lookup in `_process_row()` before `session.add(item)` ([`import_data.py`](ygo_app/import_data.py)).
- [ ] Extend import result: `{ imported, merged, rejected_count }` for clearer UI messaging.
- [ ] Tests: overwrite still wipes; append merges qty; append skips unmatched to rejected CSV.
- [ ] Bump `?v=` on edited static assets.

**Verify:** Append a CSV with 2 new rows + 3 duplicates → new rows added, duplicates merged, counts shown in alert.

---

## 10. Bulk collection update

**Goal:** Change parameters on multiple collection rows at once.

**Proposed UX:**

1. Checkbox column on collection table (per row + select-all on current page).
2. Sticky bar when ≥1 selected: *"N selected · Bulk edit · Clear"*.
3. Bulk edit modal — each field has **Leave unchanged** vs **Set value** (quantity/trade qty also support Add/Subtract).
4. Fields: quantity, trade quantity, condition, sell price (set / clear override), edition, language, notes (set/append), folder (move / add qty).

**Steps:**

- [ ] HTML: checkbox column header + bulk bar + modal markup in [`index.html`](ygo_app/static/index.html).
- [ ] Frontend: selection state, modal, `PATCH` call ([`app.js`](ygo_app/static/js/app.js)).
- [ ] Schema: `BulkCollectionUpdateIn` with optional per-field updates ([`schemas.py`](ygo_app/schemas.py)).
- [ ] API: `PATCH /api/collection/bulk` ([`collection.py`](ygo_app/api/routes/collection.py)).
- [ ] Service: `bulk_update_collection_items()` — verify all `item_ids` belong to user; max batch size (e.g. 500); reuse update logic ([`services.py`](ygo_app/services.py)).
- [ ] Tests: happy path, IDOR (foreign item_id rejected), partial field updates.
- [ ] Bump `?v=` on edited static assets.

**Verify:** Select 5 cards in a folder → set trade qty to 1 → all five updated; unchanged fields left alone.

---

## 11. Public trade subsite (share link + order requests)

**Goal:** Shareable public page at `/trade/{slug}` listing cards with `trade_quantity > 0`. Visitors can browse, filter, add to cart, and send an order request email to the collection owner via Brevo.

**Access model (decided):** Link always works at a fixed slug per user — no enable/disable toggle. Only items with trade qty > 0 are shown.

### 11.1 Data model & owner settings

- [ ] Alembic migration: add `trade_share_slug` (unique, indexed) to `users` ([`models.py`](ygo_app/models.py)).
- [ ] Auto-generate slug on registration (unguessable token); allow edit in collection UI with uniqueness check.
- [ ] Optional: `trade_display_name` for public page title (no email exposed).
- [ ] Owner UI: **Copy trade link** in collection toolbar; slug editor (`PATCH /api/collection/trade-settings` or similar).

### 11.2 Public routes (no JWT)

| Route | Purpose |
|-------|---------|
| `GET /trade/{slug}` | Serve [`trade.html`](ygo_app/static/trade.html) (separate from login-gated SPA) |
| `GET /api/public/trade/{slug}` | Trade items (sell price, condition, image, name, trade qty) |
| `GET /api/public/trade/{slug}/filters` | Facets for filter dropdowns |
| `POST /api/public/trade/{slug}/order-request` | Submit cart + contact info |

Register router in [`main.py`](ygo_app/api/main.py). Invalid slug → 404.

**Public item fields:** `item_id`, card name, set, rarity, condition, `trade_quantity`, resolved sell price, `image_url_small`. Seller: display name only — never `user.email`.

### 11.3 Trade page UI

New files: `trade.html`, `trade.js`, `trade.css` under [`ygo_app/static/`](ygo_app/static/).

- [ ] Toolbar: search, set-code filter, sort (mirror collection sort options where applicable).
- [ ] View toggle: **List** (table) / **Tiles** (reuse `.card-grid` + `.card-tile`).
- [ ] Card display: image, name, sell price, total trade qty, condition.
- [ ] Cart drawer: line qty (max = trade qty), per-line comment, optional offer price (discount).
- [ ] Contact fields (all optional): name, email, phone, delivery address.
- [ ] Info banner: visitor chooses which contact fields to share.
- [ ] GDPR consent checkbox (required) + link to privacy policy.
- [ ] Cart state in `sessionStorage`; clear on successful submit.

### 11.4 Order email (Brevo)

Extend [`email.py`](ygo_app/email.py) with `send_trade_order_request()`:

- **To:** collection owner's `User.email`
- **Reply-To:** buyer email if provided
- Plain-text body: cards, qty, list vs offer price, comments, contact block, timestamp

Reuse existing `BREVO_API_KEY` / `EMAIL_FROM` from [`config.py`](ygo_app/config.py).

### 11.5 Security

- [ ] Rate-limit `order-request` per IP (e.g. 5/hour) — [`rate_limit.py`](ygo_app/rate_limit.py).
- [ ] Cloudflare Turnstile on submit (reuse verify logic from auth).
- [ ] Server validates each `item_id` belongs to slug owner; `requested_qty <= trade_quantity`.
- [ ] Strip HTML from comments/contact; max field lengths; no PII in server logs.
- [ ] No server-side storage of buyer PII (email-only delivery reduces GDPR scope).

**Verify:** Copy link → open in incognito → filter/sort/tile view → add to cart → submit → owner receives Brevo email with correct lines and offer prices.

---

## 12. GDPR & legal (main app + trade subsite)

**Goal:** Basic compliance artifacts on both the authenticated app and the public trade page.

**Current state:** No privacy policy, imprint, footer links, or account deletion API.

### 12.1 Static legal pages

Serve at `/legal/*` (or `static/legal/`):

| Page | Purpose |
|------|---------|
| **Privacy Policy** | Data collected, legal basis, retention, Brevo as processor, user rights |
| **Imprint / Legal notice** | Operator name, address, contact (EU / DE Telemediengesetz) |
| **Terms of use** (optional) | Account rules, trade list disclaimer, liability |

**Details needed from you before final text:**

- Legal entity name, postal address, privacy contact email
- Country of operation (jurisdiction wording)
- Optional: VAT ID, trade register number
- Language: English, Hungarian, or bilingual

Ship with `{{PLACEHOLDER}}` tokens if details are not ready.

### 12.2 UI integration

- [ ] Footer on trade subsite: Privacy · Imprint · Contact (`mailto:`).
- [ ] Footer on main app (auth landing + logged-in shell).
- [ ] Lightweight storage notice (localStorage JWT on main app; sessionStorage cart on trade — essential only, no marketing cookies).
- [ ] Order form consent checkbox (trade subsite) — required before submit.

### 12.3 Account-holder rights (main app)

- [ ] Document in privacy policy: collection CSV export = data export.
- [ ] `DELETE /api/auth/account` (confirm password) — cascade delete per existing FK `ondelete=CASCADE`.

**Verify:** Footer links work on `/` and `/trade/{slug}`; account deletion removes user + collection; order submit blocked without consent checkbox.
