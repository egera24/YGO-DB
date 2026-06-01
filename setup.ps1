# One-time setup for YGO Collection & Deck Builder
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

if (-not (Test-Path "all_cards.json")) {
    Write-Host "Downloading card database..."
    Push-Location ygopro
    python get_ygopro_database.py
    Pop-Location
}

Write-Host "Importing card catalog from API (several minutes)..."
python -m ygo_app.import_data --from-api --reset --skip-collection

Write-Host ""
Write-Host "Register at http://127.0.0.1:8000 then import collection CSV from the UI."
Write-Host "Or: python -m ygo_app.import_data --skip-cards --user-id 1 (after first user exists)"

Write-Host ""
Write-Host "Done. Start the app with:  python run.py"
Write-Host "Or:  .\start.ps1"
