from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

SKIP_GZIP_PATHS = frozenset({"/api/collection/import-csv"})


class AppGZipMiddleware(GZipMiddleware):
    """GZip static/API payloads but not NDJSON import streams (small chunks buffer)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") in SKIP_GZIP_PATHS:
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

from ygo_app.api.routes import auth, cards, collection, decks, formats, meta, public_trade, search_presets
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
app.add_middleware(AppGZipMiddleware, minimum_size=1000)


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
app.include_router(formats.router, prefix="/api")
app.include_router(search_presets.router, prefix="/api")
app.include_router(public_trade.router, prefix="/api")


_LEGAL_PAGES = frozenset({"privacy", "imprint"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        STATIC_DIR / "img" / "favicon-32.png",
        media_type="image/png",
        headers=_CACHE_HEADERS or None,
    )


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers=_CACHE_HEADERS or None)
    return {"message": "Import the database, then open the UI.", "docs": "/docs"}


@app.get("/trade/{slug}", include_in_schema=False)
def trade_page(slug: str):
    trade_file = STATIC_DIR / "trade.html"
    if trade_file.exists():
        return FileResponse(trade_file, headers=_CACHE_HEADERS or None)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/legal/{page}", include_in_schema=False)
def legal_page(page: str):
    if page not in _LEGAL_PAGES:
        raise HTTPException(status_code=404, detail="Not found")
    legal_file = STATIC_DIR / "legal" / f"{page}.html"
    if legal_file.exists():
        return FileResponse(legal_file, headers=_CACHE_HEADERS or None)
    raise HTTPException(status_code=404, detail="Not found")
