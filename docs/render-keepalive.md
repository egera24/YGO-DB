# Render prod keep-alive (cron-job.org + morning cold wake)

Keeps the **production** free Render web service warm by pinging `GET /api/health` every 10 minutes during **Europe/Budapest 08:00–22:00**. Staging is **not** pinged. Do **not** run 24/7 on free (shared 750-hour workspace quota; daytime keep-alive is ~420 h/mo).

## Why two schedulers?

| Scheduler | Role |
|-----------|------|
| **GitHub Actions** [`render-prod-cold-wake.yml`](.github/workflows/render-prod-cold-wake.yml) | Once each morning ~**07:50** Budapest — wakes the service after overnight spin-down |
| **[cron-job.org](https://cron-job.org/en/)** | Every 10 min **08:00–22:00** Budapest — keeps an already-warm service from spinning down |

Overnight the service spins down (~15 min after the last 21:50 ping). The **first** request of the day is a **cold start** (~50–60 seconds on this stack). cron-job.org has a **30 second** request timeout and does not retry; Render often responds with `x-render-routing: hibernate-wake-error` and an empty body. That failure does **not** complete the wake, so every subsequent cron ping also fails until something waits long enough.

GitHub Actions `schedule` is unreliable for high-frequency `*/10` cron (runs may be delayed or dropped), but it is fine for **one daily** cold-wake with `curl --retry`. Daytime pings stay on cron-job.org (timezone-aware, reliable every 10 minutes).

## cron-job.org setup

1. Sign up at [cron-job.org](https://cron-job.org/en/) (free).
2. Create a cronjob with:
   - **Title**: `YGO App prod keep-alive`
   - **URL**: `https://ygo-app-jyek.onrender.com/api/health`
   - **Method**: `GET`
   - **Schedule timezone**: `Europe/Budapest`
   - **Minutes**: `0, 10, 20, 30, 40, 50`
   - **Hours**: `8–21` (inclusive; last run ~21:50, matches `8 <= hour < 22`)
   - **Days / months / weekdays**: every day
3. Optionally enable **failure email notifications** — expect a failure at **08:00** if the morning GHA cold-wake did not run; otherwise failures are worth investigating.
4. Run a **Test run** while the service is warm. Expect HTTP **200** and body `{"ok":true}`.
5. During daytime Budapest, check **execution history** for regular 10-minute hits.

## Morning cold wake (GitHub Actions)

Workflow: **Render prod cold wake** — runs on `main` at **05:50** and **06:50 UTC** (covers CET/CEST), pings only when Budapest local time is **07:45–08:14**.

Manual test: GitHub → **Actions** → **Render prod cold wake** → **Run workflow**.

## Limits

cron-job.org allows up to **1 request/minute** per job. This schedule is ~**84 pings/day** (14 hours × 6). The default account cap is roughly **100 HTTP executions/day**; if the dashboard warns about limits, use their free “request increase” option.

cron-job.org request timeout is **30 seconds** — **not** enough for a cold start. Do not rely on it for the first wake of the day.

## Do not

- Keep-alive **staging** (`ygo-app-dev`)
- Run keep-alive **24/7** on the free Render tier
- Point the job at a non-prod URL after a service rename without updating this doc
- Remove the morning GHA cold-wake while using cron-job.org for daytime pings

## Verification

- [ ] GHA **Render prod cold wake** succeeded today (check Actions tab)
- [ ] cron-job.org **Test run** returns 200 and `{"ok":true}` (service warm)
- [ ] cron-job.org execution history shows hits every ~10 minutes during 08:00–22:00 Budapest
- [ ] First hit at **08:00** is 200, not `hibernate-wake-error`
