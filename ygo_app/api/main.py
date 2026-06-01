from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from ygo_app.api.routes import auth, cards, collection, decks, meta
from ygo_app.config import IS_PRODUCTION
from ygo_app.import_data import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="YGO Collection & Deck Builder", version="2.0.0")


@app.on_event("startup")
def on_startup():
    init_db()


class DevStaticFiles(StaticFiles):
    """Disable caching during local development."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response


if STATIC_DIR.exists():
    static_handler = StaticFiles if IS_PRODUCTION else DevStaticFiles
    app.mount("/static", static_handler(directory=STATIC_DIR), name="static")

_CACHE_HEADERS = (
    {}
    if IS_PRODUCTION
    else {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
)

app.include_router(meta.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(collection.router, prefix="/api")
app.include_router(decks.router, prefix="/api")


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers=_CACHE_HEADERS or None)
    return {"message": "Import the database, then open the UI.", "docs": "/docs"}
