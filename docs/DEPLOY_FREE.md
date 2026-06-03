# Free permanent cloud deployment (Neon + Render + GitHub Actions)

Render’s free PostgreSQL **expires after 30 days**. This guide uses **Neon** for permanent free Postgres, **Render** for the free web app, and **GitHub Actions** to import the card catalog (no paid Render Job).

## Architecture

| Component | Service | Cost |
|-----------|---------|------|
| Database | [Neon](https://neon.com) Free Postgres | $0, permanent |
| Web app | [Render](https://render.com) Free Web Service | $0 (cold starts after idle) |
| Catalog import | GitHub Actions (Yugipedia scrape + import) | $0 on public repos |
| Card images | YGOPRODeck CDN | $0 (browser loads URLs) |

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
4. Wait until the job finishes (**~1–2 hours** for full scrape + import on first run). Logs should end with:  
   `Catalog import complete: … cards, … printings.`

The workflow runs automatically on the **1st and 15th** of each month (production DB). Use **skip scrape** to import-only from `data/catalog/` if you scraped locally.

Emergency fallback: **Import YGO catalog (YGOProDeck API fallback)** — fast API import, no Yugipedia scrape.

### Local Yugipedia pipeline

```powershell
pip install -r requirements.txt
python -m ygo_app.jobs.scrape_yugipedia_catalog --full
# Resume interrupted scrape:
python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only --resume
python -m ygo_app.jobs.import_catalog_yugipedia
```

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

---

## Step 4: Verify the live app

1. Open the Render URL (e.g. `https://ygo-app-xxxx.onrender.com`).
2. First request after idle may take **~1 minute** (free tier spin-up).
3. Status line should show thousands of **cards** (not “catalog empty”).
4. **Register** in the header.
5. **My Collection** → **Import CSV** to upload your DragonShield export (logged-in users only).

---

## Order of operations (checklist)

- [ ] Repo on GitHub  
- [ ] Neon project created; pooled `DATABASE_URL` copied  
- [ ] GitHub secret `DATABASE_URL` set  
- [ ] **Import Yugipedia catalog** workflow succeeded  
- [ ] Render free web deployed with same `DATABASE_URL` + `SECRET_KEY`  
- [ ] Register on live site and test search + CSV import  

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
