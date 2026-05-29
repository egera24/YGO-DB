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

Write-Host "Importing cards and collection (several minutes)..."
python -m ygo_app.import_data --reset

Write-Host ""
Write-Host "Done. Start the app with:  python run.py"
Write-Host "Or:  .\start.ps1"
