from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from ygo_app.api.routes import cards, collection, decks, meta

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="YGO Collection & Deck Builder", version="1.0.0")

app.include_router(meta.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(collection.router, prefix="/api")
app.include_router(decks.router, prefix="/api")

class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response


if STATIC_DIR.exists():
    app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers=_NO_CACHE)
    return {"message": "Import the database, then open the UI.", "docs": "/docs"}
