# Cloudflare rate limiting — project reference

> **Canonical upstream docs are authoritative.** These files are local snapshots for offline/agent use.  
> **Last synced:** 2026-06-23

| Snapshot | Canonical URL |
|----------|---------------|
| [error-429.md](error-429.md) | https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-429/ |
| [rate-limiting-rules.md](rate-limiting-rules.md) | https://developers.cloudflare.com/waf/rate-limiting-rules/ |
| [request-rate-calculation.md](request-rate-calculation.md) | https://developers.cloudflare.com/waf/rate-limiting-rules/request-rate/ |
| [best-practices.md](best-practices.md) | https://developers.cloudflare.com/waf/rate-limiting-rules/best-practices/ |
| [troubleshooting.md](troubleshooting.md) | https://developers.cloudflare.com/waf/rate-limiting-rules/troubleshooting/ |

## Cardmarket scraping (this project)

Cardmarket sits behind Cloudflare. Automated scraping triggers **HTTP 429** and **Error 1015** (“You are being rate limited”) when request volume looks non-human.

### How Cloudflare counts requests

Per [request rate calculation](request-rate-calculation.md), counters are keyed by **characteristics** configured in each rule — commonly **source IP**. Rotating Chrome user-data profiles on the **same IP** does not reset an IP-level ban.

Cloudflare’s [anti-scraping examples](best-practices.md#prevent-content-scraping-via-query-string) use thresholds such as **10 requests / 2 minutes** (~0.08 RPS) before challenge/block. Our scraper defaults target **~0.12 RPS** in browser mode (one request every ~8 seconds) plus random jitter and pauses between expansions.

### Error codes you will see

| Signal | Meaning |
|--------|---------|
| HTTP **429** + `Retry-After` | Rate limited; wait at least the header value before retrying |
| **Error 1015** (HTML) | IP temporarily banned; often `Retry-After: 3600` (1 hour) |
| HTTP **403** + challenge HTML | Cloudflare bot check; use `--cf-login` or `--browser --headed` |

### Recommended local commands

```powershell
# Polite browser scrape (recommended)
python -m ygo_app.jobs.scrape_cardmarket_card_list --browser --headed --polite --resume --limit 5

# After a long ban — wait, verify in normal Chrome, then resume slower:
python -m ygo_app.jobs.scrape_cardmarket_card_list --browser --headed --polite --resume --discovery-rps 0.08
```

### Recovery after IP ban

1. **Stop scraping** for at least the `Retry-After` duration (often 1 hour).
2. Open https://www.cardmarket.com in your **normal browser** (not the scrape Chrome profile). If you still see Error 1015, wait longer.
3. Reset burned profiles if needed: delete or edit `data/catalog/cardmarket_profile_state.json`.
4. Resume with `--resume` and `--polite` (or lower `--discovery-rps` / `--rps`).
5. Optional: `CARDMARKET_HTTP_PROXY` for a legitimate residential proxy only if you have one.

When the scraper detects `Retry-After >= 600` seconds, it **saves a checkpoint and exits** instead of sleeping for an hour. See [`docs/LOCAL_DEV.md`](../LOCAL_DEV.md).

### Environment overrides

```env
# CARDMARKET_DISCOVERY_RPS=0.12
# CARDMARKET_PRICE_RPS=0.2
# CARDMARKET_WORKERS=1
```

CLI flags (`--discovery-rps`, `--rps`, `--workers`) override env values.
