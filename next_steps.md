# Next steps

Working list of upcoming topics. Companion to [`future_must_have_features.md`](future_must_have_features.md) (long-term roadmap) — items here are nearer-term and get checked off / moved to the changelog in [`agent_handoff.md`](agent_handoff.md) when done.

> **Last updated:** 2026-07-16

---

## 1. Better-quality card images

**Current state:** scrape picks the largest card art `<img>` on the Yugipedia card page (`parsing.extract_card_image`), mirrors it to Cloudflare R2 as WebP (full = quality 82, small = 150px) via `jobs/sync_card_images.py`.

**To research:**

- [ ] Audit what resolution Yugipedia actually serves — the page `<img>` is often a *thumb*; the original file behind `ms.yugipedia.com//thumb/...` (strip the `/thumb/` + size suffix) is usually much larger. Check whether `images.py` URL normalization already grabs the full original or a downscaled variant.
- [ ] Compare alternative sources for full-res art:
  - **YGOProDeck CDN** (`images.ygoprodeck.com/images/cards/{passcode}.jpg`) — 421×614 typical, plus `cards_cropped` art-only variant; easy (passcode-keyed) but ToS asks not to hotlink (we mirror anyway, so fine).
  - **Yugipedia original uploads** — often highest quality scans, already our metadata source.
  - **Konami official card database** — authoritative but scraping is brittle and likely against ToS.
- [ ] Decide target sizes: keep `-small` at 150px for table thumbnails, consider bumping full image quality (WebP q85–90) and/or storing a medium size for the card modal.
- [ ] Any change in source/size = update `sync_card_images.py` + `--force` re-mirror + re-import (URLs live in `cards` rows).

## 2. URL routing — clean paths (deferred)

Hash routing (`#/search`, `#/collection`, `#/decks`, etc.) is shipped. Optional follow-up:

- [ ] Clean paths (`/collection` without `#`) — deferred; hash routing is sufficient for now.

## 3. Security review

**Likely fine already, but verify:**

- [ ] **SQL injection:** all queries go through SQLAlchemy ORM / bound parameters — audit `search_query.py` and `card_filters.py` to confirm no raw string interpolation into SQL (ILIKE patterns must be passed as bind params; escape `%`/`_` in user input used in LIKE).
- [ ] **Auth:** JWT secret strength (`SECRET_KEY` per environment), token expiry, bcrypt cost factor; no tokens in URLs/logs. Production already fail-fasts if `SECRET_KEY` missing/default or `EMAIL_BACKEND=console`; signup password complexity and OTP log redaction are in place — re-verify on deploy.
- [ ] **Authorization (IDOR):** every collection/deck/preset endpoint must filter by `user_id` from the token — verify no endpoint trusts a client-supplied id to access another user's rows.
- [ ] **Input validation:** CSV import (size limits, malformed rows), preset `params` allowlist (exists — `SEARCH_PRESET_PARAM_KEYS`), folder/deck name lengths. Partial: signup password rules; CSV import capped at 20 MB; deck/folder/preset `max_length=128` — finish remaining audit.
- [ ] **XSS:** `app.js` builds DOM from API data — confirm card names/descriptions/notes are inserted via `textContent` (not `innerHTML`) everywhere.
- [ ] **Secrets hygiene:** `.env` + `DO NOT DELETE/SECRETS/` are gitignored — periodically verify nothing leaked into git history.
- [ ] Optional: run `pip-audit` / `bandit` for dependency and static analysis checks.

## 4. Errata & tips — remaining ops / verify

Code for English-only errata, `<del>` lore text, Yugipedia-faithful `lore_html` display, empty tips, and modal supplement reset is shipped. Still needed on existing DBs:

### 4.1 Data backfill (user / GHA)

Required for `lore_html` and English-only errata on existing Neon rows:

```powershell
alembic upgrade head
python -m ygo_app.jobs.scrape_yugipedia_supplements
python -m ygo_app.jobs.import_catalog_yugipedia
```

Or GHA **Import Yugipedia catalog** on `develop` + `environment=dev` first.

- [ ] Re-scrape supplements + re-import catalog on dev/prod
- [ ] `alembic upgrade head` (migration 011+) if not already applied
- [ ] Manual side-by-side compare with Yugipedia for Castle of Dark Illusions (`33420043`), Abyss Dweller, Amazoness Paladin (after data backfill)

**Test command:**

```powershell
python -m unittest tests.test_yugipedia_errata tests.test_yugipedia_tips tests.test_yugipedia_supplements tests.test_card_detail_supplements -v
```

## 5. Bulk collection update

**Goal:** Change parameters on multiple existing collection rows at once (distinct from the set-code **Bulk Collection** spreadsheet).

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

## 6. GDPR & legal (main app + trade subsite)

**Goal:** Compliance artifacts on the authenticated app and public trade page: accurate legal HTML (operator placeholders until filled), footers, essential-storage notice, account deletion, and a full personal-data export (not only collection CSV).

**Current state:** Privacy, imprint, and terms at `/legal/*` (operator `{{PLACEHOLDER_*}}` tokens). Trade + main-app footers; dismissible storage notice; trade GDPR consent; `GET /api/auth/data-export`; `DELETE /api/auth/account`. Collection CSV export unchanged. No marketing cookies.

### 6.1 Static legal pages

| Page | Purpose |
|------|---------|
| **Privacy Policy** | Full data inventory, legal bases, retention, processors (Brevo, Turnstile, OAuth, host/DB), rights, CSV vs JSON export |
| **Imprint / Legal notice** | Operator name, address, contact (placeholders until filled) |
| **Terms of use** | Account rules, no Konami affiliation, trade list = request relay only, liability |

**Operator details still needed before final text (replace `{{PLACEHOLDER_*}}`):**

- Legal entity name, postal address, privacy contact email, country
- Optional: VAT ID, trade register number

### 6.2 UI integration

- [x] Footer on main app (auth landing + logged-in shell): Privacy · Imprint · Terms.
- [x] Terms link on trade + legal page footers.
- [x] Dismissible essential-storage notice (JWT / prefs / trade cart — no marketing cookies).

### 6.3 Account-holder rights (main app)

- [x] Privacy policy documents: collection CSV (format export) + `GET /api/auth/data-export` (full JSON).
- [x] `GET /api/auth/data-export` — profile, OAuth links, collection, folders, decks, favorites, tags, presets (no password hashes).
- [x] `DELETE /api/auth/account` — password confirm, or email confirm for OAuth-only; cascade FKs; cleanup pending OTP + email-keyed rate limits.

**Verify:** Footers on `/`, `/trade/{slug}`, `/legal/*`; export includes decks/presets; delete removes user + cascades; OAuth-only delete works; order submit blocked without consent checkbox.
