# Legacy Cardmarket scrapers (archived)

These standalone scripts were the original 3-step Cardmarket pipeline:

1. `cardmarket_expansion_list_scraper.py` — expansion IDs and names
2. `cardmarket_card_list_scraper.py` — product list pages per expansion
3. `cardmarket_card_details_scraper.py` — individual product pages for prices

They are **superseded** by the integrated jobs under `ygo_app/jobs/`:

```powershell
python -m ygo_app.jobs.scrape_cardmarket_expansions --cf-login   # one-time Cloudflare
python -m ygo_app.jobs.scrape_cardmarket_expansions
python -m ygo_app.jobs.scrape_cardmarket_card_list --resume
python -m ygo_app.jobs.scrape_cardmarket_card_details --resume
python -m ygo_app.jobs.export_cardmarket_prices
python -m ygo_app.jobs.upload_cardmarket_prices
```

See [`docs/LOCAL_DEV.md`](../docs/LOCAL_DEV.md), [`docs/cloudflare/README.md`](../docs/cloudflare/README.md), and [`agent_handoff.md`](../agent_handoff.md) for rate-limit guidance and artifact paths.

The legacy scripts remain here for reference only; do not extend them.
