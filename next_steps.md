# Next steps

Working list of upcoming topics. Companion to [`future_must_have_features.md`](future_must_have_features.md) (long-term roadmap) — items here are nearer-term and get checked off / moved to the changelog in [`agent_handoff.md`](agent_handoff.md) when done.

> **Last updated:** 2026-06-20

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
- [ ] Re-scrape supplements + re-import catalog on dev/prod (user/GHA — see §6.3)

### 6.3 Complete `<del>` errata text (Castle of Dark Illusions)

**Symptom:** First erratum columns with deletion-only `<del>` tags (no nested `<ins>`) show incomplete text when `lore_text` is used.

**Root cause:** `_lore_text_from_node` only kept text inside `<del><ins>…</ins></del>`, dropping bare `<del>` content.

- [x] Fix `_lore_text_from_node` to walk all `<del>` children
- [x] Extend Castle fixture test assertions on `lore_text`
- [ ] `alembic upgrade head` (migration 011) + supplements re-scrape + `import_catalog_yugipedia` to backfill `lore_html` on existing DB rows

### 6.4 Yugipedia-faithful errata display (strikethrough, bold, italic)

**Goal:** Errata modal lore should match Yugipedia table cells — `<del>` strikethrough, `<ins>` underline, `<b>` bold, `<i>` italic, nested markup preserved.

**Pipeline:** Yugipedia HTML → `lore_html` in DB → API → `renderErrataModal()` `innerHTML` + `.errata-lore` CSS.

- [x] Treat `lore_html` as primary display path; show muted note when only `lore_text` available
- [x] Parser: normalize `strong`→`b`, `em`→`i` in `_serialize_lore_node`
- [x] Tests asserting `lore_html` for `del`/`ins`/`b`/`i` nesting (Castle, Abyss Dweller, Amazoness fixtures)
- [x] CSS: explicit `.errata-lore b` / `.errata-lore i`; nested `del ins` underline + strikethrough
- [ ] Manual side-by-side compare with Yugipedia for Castle of Dark Illusions (`33420043`), Abyss Dweller, Amazoness Paladin (after data backfill)

**Test command:**

```powershell
python -m unittest tests.test_yugipedia_errata tests.test_card_detail_supplements -v
```

**Data backfill (required for formatted display in production):**

```powershell
alembic upgrade head
python -m ygo_app.jobs.scrape_yugipedia_supplements
python -m ygo_app.jobs.import_catalog_yugipedia
```
