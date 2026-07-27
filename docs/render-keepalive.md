# Render prod keep-alive (cron-job.org + morning cold wake)

Keeps the **production** free Render web service warm by pinging `GET /api/health` every 10 minutes during **Europe/Budapest 08:00–22:00**. Staging is **not** pinged. Do **not** run 24/7 on free (shared 750-hour workspace quota; daytime keep-alive is ~420 h/mo).

## Why three pieces?

| Scheduler | Role |
|-----------|------|
| **cron-job.org** (morning POST) | **07:50** Budapest — triggers GHA via GitHub API (`workflow_dispatch`) |
| **GitHub Actions** [`render-prod-cold-wake.yml`](.github/workflows/render-prod-cold-wake.yml) | Runs `curl` with retries (up to ~90s) — only executor that can wait out cold start |
| **cron-job.org** (daytime GET) | Every 10 min **08:00–22:00** Budapest — keeps an already-warm service from spinning down |

Overnight the service spins down (~15 min after the last 21:50 ping). The **first** request of the day is a **cold start** (~50–60 seconds on this stack). cron-job.org has a **30 second** request timeout and does not retry; Render often responds with `x-render-routing: hibernate-wake-error` and an empty body. That failure does **not** complete the wake, so every subsequent cron ping also fails until something waits long enough.

GitHub Actions `schedule` is unreliable (delayed or dropped runs — including zero scheduled runs for the daily cold-wake workflow). **Do not rely on GHA cron.** Use cron-job.org to trigger `workflow_dispatch`; daytime pings stay on cron-job.org GET (timezone-aware, reliable every 10 minutes).

## cron-job.org setup — two jobs

Sign up at [cron-job.org](https://cron-job.org/en/) (free) if needed.

### Job 1: Daytime keep-alive (GET Render)

- **Title**: `YGO App prod keep-alive`
- **URL**: `https://ygo-app-jyek.onrender.com/api/health`
- **Method**: `GET`
- **Schedule timezone**: `Europe/Budapest`
- **Minutes**: `0, 10, 20, 30, 40, 50`
- **Hours**: `8–21` (inclusive; last run ~21:50, matches `8 <= hour < 22`)
- **Days / months / weekdays**: every day

Run a **Test run** while the service is warm. Expect HTTP **200** and body `{"ok":true}`.

### Job 2: Morning cold wake (POST GitHub API)

Triggers the GHA workflow so curl can retry long enough for Render cold start. **Do not** point this job at Render directly.

**GitHub PAT (one-time):**

1. GitHub → **Settings → Developer settings → Fine-grained personal access tokens**
2. Repository access: **Only `egera24/YGO-DB`**
3. Permissions: **Actions: Read and write**
4. Copy the token — store **only** in cron-job.org (never commit to the repo)

**cron-job.org job:**

- **Title**: `YGO App prod cold wake (trigger GHA)`
- **URL**: `https://api.github.com/repos/egera24/YGO-DB/actions/workflows/render-prod-cold-wake.yml/dispatches`
- **Method**: `POST`
- **Schedule timezone**: `Europe/Budapest`
- **Time**: **07:50** daily (10 min before the daytime window starts at 08:00)
- **Request body**: `{"ref":"main"}`
- **Headers** (cron-job.org Advanced):
  - `Accept`: `application/vnd.github+json`
  - `Authorization`: `Bearer github_pat_...` (your fine-grained PAT)
  - `Content-Type`: `application/json`

**Test run** — expect HTTP **204 No Content** from GitHub. Confirm a new run appears under Actions → **Render prod cold wake** with event **workflow_dispatch**.

Optionally enable **failure email notifications** on both jobs — expect a failure at **08:00** on the daytime GET job if the morning trigger did not run; otherwise failures are worth investigating.

## Morning cold wake (GitHub Actions)

Workflow: **Render prod cold wake** — triggered by cron-job.org POST at **07:50** Budapest, or manually:

- GitHub → **Actions** → **Render prod cold wake** → **Run workflow**
- Or: `gh workflow run render-prod-cold-wake.yml`

## Limits

cron-job.org allows up to **1 request/minute** per job. Daytime schedule is ~**84 pings/day** (14 hours × 6) plus **1** morning trigger = **~85/day**. The default account cap is roughly **100 HTTP executions/day**; if the dashboard warns about limits, use their free “request increase” option.

cron-job.org request timeout is **30 seconds** — **not** enough for a cold start on a direct GET to Render. The morning job must POST to GitHub API (fast response), not ping Render.

## Do not

- Keep-alive **staging** (`ygo-app-dev`)
- Run keep-alive **24/7** on the free Render tier
- Point the daytime job at a non-prod URL after a service rename without updating this doc
- Remove the morning cron-job.org → GHA trigger while using cron-job.org for daytime pings
- Add a second GET job at 07:50 pointing at Render — it cannot complete cold start
- Rely on GHA `schedule` for the morning wake

## Verification

- [ ] cron-job.org morning job **Test run** → GitHub **204**, Actions shows **workflow_dispatch** run
- [ ] GHA **Render prod cold wake** log shows curl success (`{"ok":true}`)
- [ ] cron-job.org daytime **Test run** returns 200 and `{"ok":true}` (service warm)
- [ ] cron-job.org execution history shows hits every ~10 minutes during 08:00–22:00 Budapest
- [ ] First daytime hit at **08:00** is 200, not `hibernate-wake-error`
