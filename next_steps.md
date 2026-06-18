# Next steps

Working list of upcoming topics. Companion to [`future_must_have_features.md`](future_must_have_features.md) (long-term roadmap) — items here are nearer-term and get checked off / moved to the changelog in [`agent_handoff.md`](agent_handoff.md) when done.

> **Last updated:** 2026-06-12

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

## 2. Login as landing page (no anonymous access)

**Current state:** the UI loads for everyone; auth only gates collection/decks/presets. `GET /api/filters` and card search are public.

**Plan:**

- [ ] Frontend: on load, call `/api/auth/me`; if not authenticated, render only a login/register view (hide tabs, search, everything). No data fetches until logged in.
- [ ] Backend: add the auth dependency to currently-public API routes (`/api/cards/search`, `/api/cards/{id}`, `/api/filters`, `/api/status`?) so data is not reachable without a token — frontend hiding alone is not access control.
- [ ] Decide whether `/api/health` stays public (Render health checks need it — yes).
- [ ] Update verification checklist in `agent_handoff.md` (§12 currently expects `GET /api/filters` without auth).

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
- [ ] **Auth:** JWT secret strength (`SECRET_KEY` per environment), token expiry, bcrypt cost factor; no tokens in URLs/logs.
- [ ] **Authorization (IDOR):** every collection/deck/preset endpoint must filter by `user_id` from the token — verify no endpoint trusts a client-supplied id to access another user's rows.
- [ ] **Rate limiting / brute force:** login endpoint has no throttling — consider `slowapi` or simple per-IP limit on `/api/auth/*`.
- [ ] **Input validation:** CSV import (size limits, malformed rows), preset `params` allowlist (exists — `SEARCH_PRESET_PARAM_KEYS`), folder/deck name lengths.
- [ ] **Headers:** add security headers (`X-Content-Type-Options`, `Content-Security-Policy`, `X-Frame-Options`) via middleware; HTTPS enforced by Render.
- [ ] **XSS:** `app.js` builds DOM from API data — confirm card names/descriptions/notes are inserted via `textContent` (not `innerHTML`) everywhere.
- [ ] **Secrets hygiene:** `.env` + `DO NOT DELETE/SECRETS/` are gitignored — periodically verify nothing leaked into git history.
- [ ] Optional: run `pip-audit` / `bandit` for dependency and static analysis checks.
