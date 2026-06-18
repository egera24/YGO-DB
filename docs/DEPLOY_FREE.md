# Free permanent cloud deployment (Neon + Render + GitHub Actions)

Render’s free PostgreSQL **expires after 30 days**. This guide uses **Neon** for permanent free Postgres, **Render** for the free web app, and **GitHub Actions** to import the card catalog (no paid Render Job).

## Architecture

| Component | Service | Cost |
|-----------|---------|------|
| Database | [Neon](https://neon.com) Free Postgres | $0, permanent |
| Web app | [Render](https://render.com) Free Web Service | $0 (cold starts after idle) |
| Catalog import | GitHub Actions (Yugipedia scrape + import) | $0 on public repos |
| Card images | [Cloudflare R2](https://developers.cloudflare.com/r2/) mirror (WebP), Yugipedia CDN fallback | $0 within free tier (10 GB storage, zero egress) |

## Prerequisites

- GitHub repository with this project
- [Neon](https://neon.tech) account (no credit card on free tier)
- [Render](https://render.com) account (Hobby workspace)

---

## Step 1: Neon PostgreSQL

1. Sign in at [console.neon.tech](https://console.neon.tech).
2. **New project** → pick a region close to your users (e.g. EU or US).
3. On the project dashboard, open **Connection details**.
4. Copy the **pooled** connection string (host often contains `-pooler`).
   - It should look like:  
     `postgresql://user:password@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`
5. Save it somewhere safe — you will use it as `DATABASE_URL` (never commit it).

Optional: run migrations locally before deploy:

```powershell
$env:DATABASE_URL="postgresql://...your neon pooled url..."
alembic upgrade head
```

---

## Step 2: GitHub secrets and catalog import

1. Open your repo on GitHub → **Settings** → **Secrets and variables** → **Actions**.
2. **Repository secrets**:
   - `DATABASE_URL` — Neon **production** branch pooled URL
   - `DATABASE_URL_DEV` — Neon **dev** branch pooled URL (for staging / local parity)
3. Go to **Actions** → **Import Yugipedia catalog** → **Run workflow** → choose **production** or **dev**.
4. Wait until **all jobs** finish (`prepare` → `passcodes` → `scrape_batch_0` … `scrape_batch_5` → `import`). Total wall clock is often **~2–4 hours** (each batch job stays under its own timeout). Each batch log should end with **`[BATCH_RESULT] … missing=0`**. The **import** job log should end with:  
   `Catalog import complete: … cards, … printings.`

   Scrape exit codes: **0** success, **2** stalled (re-run workflow with `--resume`), **3** batch incomplete (fix errors, re-run). Look for **`[HEARTBEAT]`**, **`[FAIL]`**, **`[BATCH_RETRY]`** in batch job logs.

The workflow runs automatically on the **1st and 15th** of each month (production DB). Details scraping is split into **6 batches** (`BATCH_COUNT` in the workflow YAML); cumulative JSON is passed via the `catalog-state` artifact. Use **skip scrape** for import-only (requires `data/catalog/yugipedia_all_cards.json` in the workspace — normally you re-run the full workflow instead).

Emergency fallback: **Import YGO catalog (YGOProDeck API fallback)** — fast API import, no Yugipedia scrape.

### Local Yugipedia pipeline

```powershell
pip install -r requirements.txt
python -m ygo_app.jobs.scrape_yugipedia_catalog --full
# Resume interrupted scrape:
python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only --resume
# Same batching as GHA (example: batch 2 of 6):
python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only --resume --batch-index 2 --batch-count 6
python -m ygo_app.jobs.import_catalog_yugipedia
```

### Card image mirror (Cloudflare R2)

The `images` job in the Yugipedia workflow mirrors card art to an S3-compatible bucket (WebP full + 150px thumb, keys `cards/{passcode}.webp` / `cards/{passcode}-small.webp`) so the app stops hotlinking `ms.yugipedia.com`. The import then writes bucket URLs into `cards.image_url` / `image_url_small` for every mirrored passcode (Yugipedia URL fallback otherwise).

One-time setup:

1. Cloudflare Dashboard → **R2 Object Storage** → activate (needs a payment card; free tier is 10 GB storage / 1M writes / 10M reads per month — this project stays far below). Set a **billing notification** at $1 as a tripwire.
2. Create bucket `ygo-card-images` → Settings → **Public access** via the `r2.dev` subdomain (or a custom domain for full CDN caching).
3. **Manage R2 API Tokens** → create token with **Object Read & Write** scoped to the bucket.
4. Add **repository secrets** (also usable in `.env` for local runs):
   - `S3_ENDPOINT_URL` — `https://<account_id>.r2.cloudflarestorage.com`
   - `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` — from the R2 API token
   - `S3_BUCKET` — `ygo-card-images`
   - `IMAGE_BASE_URL` — public base URL (e.g. `https://pub-xxxx.r2.dev`)

If the secrets are absent the `images` job skips itself and the import keeps Yugipedia URLs. The job is **incremental** — re-runs only download images missing from the bucket. The first full backfill (~14k cards) takes a few hours; it can also be run locally:

```powershell
python -m ygo_app.jobs.sync_card_images            # needs data/catalog/yugipedia_all_cards.json
python -m ygo_app.jobs.sync_card_images --manifest-only   # rebuild manifest from bucket listing only
```

Vendor migration later: `rclone sync` the bucket to any S3-compatible provider, change `S3_*` + `IMAGE_BASE_URL` secrets, re-run the import (or one SQL `UPDATE ... replace(...)`).

### Optional: DB keep-alive workflow

The **Neon DB keep-alive** workflow pings **production** and **dev** databases every few days (requires both secrets).

See **[ENVIRONMENTS.md](ENVIRONMENTS.md)** for the full local → staging → production workflow.

---

## Step 3: Render web services (free)

[`render.yaml`](../render.yaml) defines **two** services: **ygo-app-dev** (`develop` branch) and **ygo-app** (`main`).

### Option A — Blueprint

1. Render Dashboard → **New** → **Blueprint**.
2. Connect the GitHub repo.
3. Use the default **`render.yaml`** (free web only). Do **not** use `render-paid.yaml` unless you want paid Render Postgres.
4. After the blueprint is created, open each web service → **Environment**:
   - **ygo-app-dev** → `DATABASE_URL` = Neon **dev** pooled URL
   - **ygo-app** → `DATABASE_URL` = Neon **production** pooled URL
5. Confirm **`SECRET_KEY`** was generated per service (or add your own).
6. Deploy / wait for **Live** on both.

### Option B — Manual web service

1. **New** → **Web Service** → connect repo.
2. **Instance type**: Free  
3. **Build command**: `pip install -r requirements.txt && alembic upgrade head`  
4. **Start command**: `uvicorn ygo_app.api.main:app --host 0.0.0.0 --port $PORT`  
5. **Health check path**: `/api/health`  
6. Environment variables:

   | Key | Value |
   |-----|--------|
   | `ENV` | `production` |
   | `DATABASE_URL` | Neon pooled URL |
   | `SECRET_KEY` | Long random string |
   | `PYTHON_VERSION` | `3.12.0` (optional) |
   | `EMAIL_BACKEND` | `brevo` |
   | `BREVO_API_KEY` | Brevo SMTP/API key |
   | `EMAIL_FROM` | Verified sender, e.g. `YGO App <you@example.com>` |

Optional (bot protection on registration):

| Key | Value |
|-----|--------|
| `TURNSTILE_SITE_KEY` | Cloudflare Turnstile site key |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile secret key |

For **local development**, use `EMAIL_BACKEND=console` in `.env` — verification codes print in the terminal instead of sending email.

---

## Step 4: Verify the live app

1. Open the Render URL (e.g. `https://ygo-app-xxxx.onrender.com`).
2. First request after idle may take **~1 minute** (free tier spin-up).
3. Status line should show thousands of **cards** (not “catalog empty”).
4. **Register** — create an account; check email for the 6-digit verification code (or spam folder).
5. **My Collection** → **Import CSV** to upload your DragonShield export (logged-in users only).

---

## Order of operations (checklist)

- [ ] Repo on GitHub  
- [ ] Neon project created; pooled `DATABASE_URL` copied  
- [ ] GitHub secret `DATABASE_URL` set  
- [ ] **Import Yugipedia catalog** workflow succeeded  
- [ ] Render free web deployed with same `DATABASE_URL` + `SECRET_KEY` + email env vars  
- [ ] Register on live site, verify email, and test search + CSV import  

---

## Tradeoffs

| Topic | What to expect |
|--------|----------------|
| **Data** | Neon free data does not expire at 30 days (unlike Render free Postgres). |
| **Cold starts** | Render web sleeps after ~15 min idle; Neon may take a few seconds to wake on first query. |
| **Neon limits** | 0.5 GB storage, 100 CU-hours/month — fine for hobby use; monitor in Neon dashboard. |
| **Backups** | Limited on free tier; export data occasionally if it matters. |
| **Do not** ping Render every few minutes to stay warm — you will burn the 750 free instance hours/month. |

---

## Catalog refresh without Render Job

GitHub → **Actions** → **Import Yugipedia catalog** → **Run workflow**.

Or from your PC:

```powershell
$env:DATABASE_URL="postgresql://...neon..."
$env:ENV="production"
python -m ygo_app.jobs.import_catalog
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Catalog empty in UI | Run GitHub import workflow; check job logs. |
| 401 on Collection / Decks | Log in first. |
| DB connection errors on Render | Use Neon **pooled** URL with `sslmode=require`; check IP allowlist (Neon default allows all). |
| Build fails on `alembic` | Ensure `DATABASE_URL` is set before deploy; run workflow import after first successful migrate. |
| SSL errors | Use pooled Neon URL; app enables SSL for Postgres when `sslmode` is missing (see `database.py`). |

---

## Paid alternative

For always-on web + managed Render Postgres + cron import, use [`render-paid.yaml`](../render-paid.yaml) (Starter plans, monthly cost).
