# YGO Collection & Deck Builder

Local web app for searching Yu-Gi-Oh! cards, tracking physical copies by **set code** (card number, e.g. `25LP-EN001`), building decks, favorites, and tags.

Built on your existing data:

- `all_cards.json` — YGOProDeck API export (`ygopro/get_ygopro_database.py`)
- `my_collection.csv` — DragonShield export (`ygopro/get_my_cards.py`)

## Quick start

```powershell
cd "c:\Python Projects\YGO App Cursor"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# One-time import (several minutes for full card DB)
python -m ygo_app.import_data

# Start the app (opens browser)
python run.py
```

API docs: http://127.0.0.1:8000/docs

## Features

| Area | What you can do |
|------|-----------------|
| **Search** | Name, description, archetype, passcode, set code, attribute, race, frame type |
| **Set code** | Every printing lists `set_code`; search/filter collection by card number |
| **Collection** | Import DragonShield CSV; view by folder; add owned copies from card detail |
| **Decks** | Main / Extra / Side zones, local SQLite storage |
| **Extras** | Favorites, custom tags (searchable via `tag` query param on API) |

## Import options

```powershell
# Full card database + collection
python -m ygo_app.import_data

# Only refresh collection from CSV
python -m ygo_app.import_data --skip-cards

# Test with first 1000 cards
python -m ygo_app.import_data --limit 1000
```

Refresh YGOProDeck data:

```powershell
cd ygopro
python get_ygopro_database.py
cd ..
python -m ygo_app.import_data --skip-collection
```

Re-import collection from the UI (**My Collection → Re-import CSV**) or:

```powershell
python -m ygo_app.import_data --skip-cards
```

## Project layout

```
ygo_app/           # Application
  import_data.py   # JSON + CSV → SQLite (data/ygo.db)
  api/             # FastAPI routes
  static/          # Web UI
ygopro/            # Your existing download/merge scripts
yugipedia/         # Optional extended scrapers
cardmarket/        # Optional price scrapers
all_cards.json
my_collection.csv
data/ygo.db        # Created on import
run.py
```

## Set code & rarity matching

DragonShield **Card Number** = YGOProDeck **set_code** (e.g. `25LP-EN001`).

DragonShield rarity `UR` is stored as `(UR)` to match `set_rarity_code` in `all_cards.json` — same logic as your `extend_cards.py` / `get_full_database.py`.

## API examples

```http
GET /api/cards/search?q=diabellstar&owned_only=true
GET /api/cards/by-set-code/25LP-EN001
GET /api/collection?set_code=25LP
POST /api/collection  { "set_code": "25LP-EN001", "rarity": "UR", "quantity": 1 }
```

## Local data (not in Git)

Large files stay on your machine (see `.gitignore`): `all_cards.json`, `my_collection.csv`, `data/ygo.db`, scraper JSON outputs, and `yugipedia/image_*` folders. After cloning, run the `ygopro` scripts and `python -m ygo_app.import_data` as in Quick start.

## Notes

- Deck builder stores cards by **passcode** (card identity), not a specific printing — use Collection for printings you own.
- Optional scrapers (`yugipedia`, `cardmarket`) are not wired in yet; the schema can be extended later for extra prices or images.
- Your original `prompt.txt` mentioned wxPython; this stack uses a browser UI for easier search on large databases. The scrapers in this folder stay unchanged.
