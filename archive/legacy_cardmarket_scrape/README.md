# Legacy Cardmarket web scraper (archived)

The 4-step Cardmarket **web scraper** (expansions → card list → card details → export) lived here before the **catalog pipeline** replaced it.

**Current workflow:** `python -m ygo_app.jobs.sync_cardmarket_catalog` — downloads official JSON from Cardmarket S3, matches Yugipedia printings, imports SCD Type 2 prices weekly via GHA.

See [`docs/cardmarket-catalog-pipeline.md`](../../docs/cardmarket-catalog-pipeline.md).

These files are kept for reference only; they are not imported by the active app.
