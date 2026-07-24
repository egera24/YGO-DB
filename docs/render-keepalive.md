# Render prod keep-alive (cron-job.org)

Keeps the **production** free Render web service warm by pinging `GET /api/health` every 10 minutes during **Europe/Budapest 08:00–22:00**. Staging is **not** pinged. Do **not** run 24/7 on free (shared 750-hour workspace quota; daytime keep-alive is ~420 h/mo).

GitHub Actions `schedule` is unreliable for high-frequency cron (runs may be delayed or dropped). Use [cron-job.org](https://cron-job.org/en/) instead — free, timezone-aware, and suitable for a 10-minute interval.

## Setup

1. Sign up at [cron-job.org](https://cron-job.org/en/) (free).
2. Create a cronjob with:
   - **Title**: `YGO App prod keep-alive`
   - **URL**: `https://ygo-app-jyek.onrender.com/api/health`
   - **Method**: `GET`
   - **Schedule timezone**: `Europe/Budapest`
   - **Minutes**: `0, 10, 20, 30, 40, 50`
   - **Hours**: `8–21` (inclusive; last run ~21:50, matches previous `8 <= hour < 22` window)
   - **Days / months / weekdays**: every day
3. Optionally enable **failure email notifications**.
4. Run a **Test run** once. Expect HTTP **200** and body `{"ok":true}`.
5. During daytime Budapest, check **execution history** for regular 10-minute hits.

## Limits

cron-job.org allows up to **1 request/minute** per job. This schedule is ~**84 pings/day** (14 hours × 6). The default account cap is roughly **100 HTTP executions/day**; if the dashboard warns about limits, use their free “request increase” option.

Request timeout on cron-job.org is **30 seconds** — enough for Render cold starts on `/api/health`.

## Do not

- Keep-alive **staging** (`ygo-app-dev`)
- Run keep-alive **24/7** on the free Render tier
- Point the job at a non-prod URL after a service rename without updating this doc

## Verification

- [ ] Test run returns 200 and `{"ok":true}`
- [ ] Execution history shows hits every ~10 minutes during 08:00–22:00 Budapest
- [ ] No GitHub Actions workflow named **Render prod keep-alive** (removed; Neon DB keep-alive remains on GHA)
