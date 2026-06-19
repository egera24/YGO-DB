from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from ygo_app.api.routes import auth, cards, collection, decks, meta, search_presets
from ygo_app.config import IMAGE_BASE_URL, IS_PRODUCTION
from ygo_app.import_data import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_docs_kwargs = (
    {"docs_url": None, "redoc_url": None, "openapi_url": None}
    if IS_PRODUCTION
    else {}
)

app = FastAPI(
    title="YGO Collection & Deck Builder",
    version="2.0.0",
    **_docs_kwargs,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _build_csp() -> str:
    img_sources = ["'self'", "data:", "https:"]
    if IMAGE_BASE_URL and IMAGE_BASE_URL.startswith("https://"):
        img_sources.append(IMAGE_BASE_URL)
    directives = [
        "default-src 'self'",
        f"img-src {' '.join(dict.fromkeys(img_sources))}",
        "script-src 'self' https://challenges.cloudflare.com",
        "style-src 'self'",
        "frame-src https://challenges.cloudflare.com",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    return "; ".join(directives)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = _build_csp()
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


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


class CachedStaticFiles(StaticFiles):
    """Long-lived cache for versioned static assets (?v= busting in HTML)."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if STATIC_DIR.exists():
    if IS_PRODUCTION:
        static_handler = CachedStaticFiles
    else:
        static_handler = DevStaticFiles
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
app.include_router(search_presets.router, prefix="/api")


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers=_CACHE_HEADERS or None)
    return {"message": "Import the database, then open the UI.", "docs": "/docs"}
