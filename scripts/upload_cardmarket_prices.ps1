# Upload Cardmarket price export to R2 (run after local scrape).
# Requires S3_* env vars in .env (same as image mirror).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

python -m ygo_app.jobs.upload_cardmarket_prices @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
