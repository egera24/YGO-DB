# Yugipedia scrape baseline (GHA)

Measured from workflow run `29084640684` (develop, success, **3h 53m** total).

| Job | Duration |
|-----|----------|
| prepare | 0.4m |
| passcodes | 2.1m |
| scrape_batch_0 | 16.8m |
| scrape_batch_1 | 14.1m |
| scrape_batch_2 | 13.9m |
| scrape_batch_3 | 14.0m |
| scrape_batch_4 | 14.0m |
| scrape_batch_5 | 32.5m |
| set_chronology | 0.4m |
| supplements_batch_0 | 19.6m |
| supplements_batch_1 | 19.3m |
| supplements_batch_2 | 19.6m |
| supplements_batch_3 | 19.6m |
| supplements_batch_4 | 19.3m |
| supplements_batch_5 | 17.8m |
| images | 1.7m |
| import | 7.1m |

**Scrape subtotal:** passcodes + details + supplements + set_chronology ≈ **3.4h**

Re-measure after speedup changes:

```powershell
gh run list --workflow="Import Yugipedia catalog" --limit 1
gh run view <run_id> --json jobs | python scripts/gha_run_job_durations.py
```
