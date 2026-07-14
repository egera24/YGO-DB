import asyncio
import csv
import io
import json
import logging
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.auth import get_current_user
from ygo_app.cardmarket.market_prices import load_market_prices
from ygo_app.collection_export import export_collection_csv, list_export_formats
from ygo_app.config import COLLECTION_CSV_MAX_BYTES
from ygo_app.database import SessionLocal, get_db
from ygo_app.import_data import CollectionImportResult, import_collection_csv
from ygo_app.import_progress import build_progress_event
from ygo_app.models import CollectionItem, CollectionItemFolder, Printing, User
from ygo_app.schemas import (
    BulkGridListOut,
    BulkGridMetaOut,
    BulkGridSaveIn,
    CollectionDetailStatsOut,
    CollectionFiltersOut,
    CollectionFolderCreate,
    CollectionFolderDeleteResult,
    CollectionFolderOut,
    CollectionFolderUpdate,
    CollectionItemCreate,
    CollectionItemOut,
    CollectionItemUpdate,
    CollectionListOut,
    CollectionStatsOut,
    CollectionSuggestionsOut,
    TradeSettingsOut,
    TradeSettingsUpdateIn,
)
from ygo_app.services import (
    FolderConflictError,
    _collection_item_row,
    add_collection_item,
    bulk_collection_grid_meta,
    collection_detail_stats,
    collection_filter_options,
    collection_stats,
    collection_suggestions,
    create_collection_folder,
    delete_collection_folder,
    get_trade_settings,
    list_bulk_collection_grid,
    list_collection,
    list_collection_folders,
    save_bulk_collection_grid,
    update_collection_folder,
    update_collection_item,
    update_trade_settings,
)

router = APIRouter(prefix="/collection", tags=["collection"])
logger = logging.getLogger(__name__)


def _item_out(
    db: Session,
    item: CollectionItem,
    *,
    folder_filter: str | None = None,
) -> CollectionItemOut:
    market_row = load_market_prices(db, [(item.set_code, item.rarity_code)]).get(
        (item.set_code, item.rarity_code)
    )
    return CollectionItemOut(
        **_collection_item_row(item, folder_filter=folder_filter, market_row=market_row)
    )


def _load_item_with_card(
    db: Session, item_id: int, user_id: int
) -> CollectionItem | None:
    return db.execute(
        select(CollectionItem)
        .options(
            joinedload(CollectionItem.linked_printing).joinedload(Printing.card),
            joinedload(CollectionItem.folder_allocations).joinedload(
                CollectionItemFolder.folder
            ),
        )
        .where(CollectionItem.id == item_id, CollectionItem.user_id == user_id)
    ).unique().scalar_one_or_none()


@router.get("/stats", response_model=CollectionStatsOut)
def get_collection_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return collection_stats(db, user_id=user.id)


@router.get("/stats/detail", response_model=CollectionDetailStatsOut)
def get_collection_detail_stats(
    folder: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = collection_detail_stats(db, user_id=user.id, folder=folder)
    max_item = payload.pop("max_value_item")
    return CollectionDetailStatsOut(
        **payload,
        max_value_item=CollectionItemOut(**max_item) if max_item else None,
    )


@router.get("/filters", response_model=CollectionFiltersOut)
def get_collection_filters(
    q: str | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return CollectionFiltersOut(
        **collection_filter_options(
            db,
            user_id=user.id,
            q=q,
            card_name=card_name,
            set_code=set_code,
            set_name=set_name,
            rarity=rarity,
            edition=edition,
            condition=condition,
            folder=folder,
        )
    )


@router.get("/suggestions", response_model=CollectionSuggestionsOut)
def get_collection_suggestions(
    field: str = Query(..., pattern="^(card_name|set_code|set_name)$"),
    q: str | None = None,
    limit: int = Query(20, le=50),
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    values = collection_suggestions(
        db,
        user_id=user.id,
        field=field,
        q=q,
        limit=limit,
        card_name=card_name,
        set_code=set_code,
        set_name=set_name,
        rarity=rarity,
        edition=edition,
        condition=condition,
        folder=folder,
    )
    return CollectionSuggestionsOut(values=values)


def _trade_settings_out(settings: dict) -> TradeSettingsOut:
    slug = settings["slug"]
    return TradeSettingsOut(
        slug=slug,
        display_name=settings.get("display_name"),
        trade_url=f"/trade/{slug}",
    )


@router.get("/trade-settings", response_model=TradeSettingsOut)
def read_trade_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        settings = get_trade_settings(db, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _trade_settings_out(settings)


@router.patch("/trade-settings", response_model=TradeSettingsOut)
def patch_trade_settings(
    body: TradeSettingsUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.slug is None and body.display_name is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    try:
        settings = update_trade_settings(
            db,
            user.id,
            slug=body.slug,
            display_name=body.display_name,
        )
    except ValueError as exc:
        message = str(exc)
        if "already taken" in message.lower() or "reserved" in message.lower():
            raise HTTPException(status.HTTP_409_CONFLICT, message) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message) from exc
    return _trade_settings_out(settings)


@router.get("/folders", response_model=list[CollectionFolderOut])
def get_folders(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return list_collection_folders(db, user_id=user.id)


@router.post("/folders", response_model=CollectionFolderOut, status_code=201)
def create_folder(
    body: CollectionFolderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        folder = create_collection_folder(db, user_id=user.id, name=body.name)
    except FolderConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    rows = list_collection_folders(db, user_id=user.id)
    match = next((row for row in rows if row["id"] == folder.id), None)
    return CollectionFolderOut(
        id=folder.id,
        name=folder.name,
        sort_order=folder.sort_order,
        item_count=match["item_count"] if match else 0,
        quantity=match["quantity"] if match else 0,
    )


@router.patch("/folders/{folder_id}", response_model=CollectionFolderOut)
def patch_folder(
    folder_id: int,
    body: CollectionFolderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        folder = update_collection_folder(
            db,
            user_id=user.id,
            folder_id=folder_id,
            name=body.name,
            sort_order=body.sort_order,
        )
    except FolderConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 400, str(exc)) from exc
    rows = list_collection_folders(db, user_id=user.id)
    match = next((row for row in rows if row["id"] == folder.id), None)
    return CollectionFolderOut(
        id=folder.id,
        name=folder.name,
        sort_order=folder.sort_order,
        item_count=match["item_count"] if match else 0,
        quantity=match["quantity"] if match else 0,
    )


@router.delete("/folders/{folder_id}", response_model=CollectionFolderDeleteResult)
def remove_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        moved_allocations, moved_quantity = delete_collection_folder(
            db, user_id=user.id, folder_id=folder_id
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return CollectionFolderDeleteResult(
        moved_allocations=moved_allocations,
        moved_quantity=moved_quantity,
    )


@router.get("", response_model=CollectionListOut)
def get_collection(
    q: str | None = None,
    card_name: str | None = None,
    folder: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    sort: str = Query(
        "set_code",
        pattern=(
            "^(set_code|card_name|folder_name|quantity|trade_quantity|passcode|release_date)$"
        ),
    ),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = list_collection(
        db,
        user_id=user.id,
        q=q,
        card_name=card_name,
        folder=folder,
        set_code=set_code,
        set_name=set_name,
        rarity=rarity,
        edition=edition,
        condition=condition,
        sort=sort,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    return CollectionListOut(
        items=[CollectionItemOut(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export-formats")
def get_export_formats(user: User = Depends(get_current_user)):
    return list_export_formats()


@router.get("/export-csv")
def export_csv(
    format: str = Query(..., description="Export format id (e.g. dragonshield)"),
    folders: list[str] | None = Query(
        None, description="Folder id or __no_folder__; omit for all"
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        csv_text, media_type, filename = export_collection_csv(
            db, user_id=user.id, format_id=format, folder_ids=folders
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    content = "\ufeff" + csv_text
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/bulk-grid/meta", response_model=BulkGridMetaOut)
def get_bulk_grid_meta(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = bulk_collection_grid_meta(db, user_id=user.id)
    return BulkGridMetaOut(
        folders=[CollectionFolderOut(**row) for row in payload["folders"]],
        conditions=payload["conditions"],
        editions=payload["editions"],
        languages=payload["languages"],
    )


@router.get("/bulk-grid", response_model=BulkGridListOut)
def get_bulk_grid(
    set_code: str = Query(..., min_length=1),
    q: str | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sort_specs: list[dict] | None = None
    if sort:
        try:
            parsed = json.loads(sort)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Invalid sort JSON"
            ) from exc
        if not isinstance(parsed, list):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sort must be a JSON array")
        sort_specs = parsed
    try:
        rows, total, abbr = list_bulk_collection_grid(
            db,
            user_id=user.id,
            set_code=set_code,
            q=q,
            sort=sort_specs,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return BulkGridListOut(rows=rows, total=total, set_code=abbr)


def _bulk_save_progress_event(update: dict, started: float) -> dict:
    return build_progress_event(started=started, **update)


def _log_bulk_save_progress(update: dict) -> None:
    phase = update.get("phase", "?")
    current = update.get("current", 0)
    total = update.get("total", 0)
    message = update.get("message")
    if message:
        logger.info("Bulk grid save [%s] %s (%s/%s)", phase, message, current, total)
    elif total:
        logger.info("Bulk grid save [%s] %s/%s", phase, current, total)
    else:
        logger.info("Bulk grid save [%s]", phase)


@router.post("/bulk-grid/save")
async def post_bulk_grid_save(
    request: Request,
    user: User = Depends(get_current_user),
):
    try:
        body = BulkGridSaveIn.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON body") from exc

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    started = time.monotonic()
    changes = [change.model_dump() for change in body.changes]

    def on_progress(update: dict) -> None:
        payload = _bulk_save_progress_event(update, started)
        _log_bulk_save_progress(update)
        loop.call_soon_threadsafe(queue.put_nowait, ("event", payload))

    def worker() -> None:
        session = SessionLocal()
        try:
            result = save_bulk_collection_grid(
                session,
                user_id=user.id,
                set_code=body.set_code,
                changes=changes,
                progress_callback=on_progress,
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("event", {"type": "done", **result}),
            )
        except ValueError as exc:
            session.rollback()
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("event", {"type": "error", "detail": str(exc)}),
            )
        except Exception as exc:
            session.rollback()
            logger.exception("Bulk grid save failed")
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("event", {"type": "error", "detail": str(exc)}),
            )
        finally:
            session.close()
            loop.call_soon_threadsafe(queue.put_nowait, ("close", None))

    threading.Thread(target=worker, daemon=True).start()

    async def event_stream():
        started_payload = build_progress_event(
            phase="started",
            message="Starting save…",
            started=started,
        )
        yield json.dumps(started_payload) + "\n"
        while True:
            kind, payload = await queue.get()
            if kind == "close":
                break
            yield json.dumps(payload) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=CollectionItemOut)
def create_item(
    body: CollectionItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        item = add_collection_item(db, user.id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    item = _load_item_with_card(db, item.id, user.id) or item
    return _item_out(db, item)


@router.get("/{item_id}", response_model=CollectionItemOut)
def get_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _load_item_with_card(db, item_id, user.id)
    if not item:
        raise HTTPException(404, "Collection item not found")
    return _item_out(db, item)


@router.patch("/{item_id}", response_model=CollectionItemOut)
def update_item(
    item_id: int,
    body: CollectionItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.get(CollectionItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Collection item not found")
    try:
        item = update_collection_item(
            db,
            user_id=user.id,
            item=item,
            data=body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    item = _load_item_with_card(db, item_id, user.id) or item
    return _item_out(db, item)


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = db.get(CollectionItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Collection item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


def _rejected_csv_text(result: CollectionImportResult) -> str | None:
    if not result.rejected:
        return None
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=result.fieldnames, extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(result.rejected)
    return buf.getvalue()


def _progress_event(update: dict, started: float) -> dict:
    return build_progress_event(started=started, **update)


def _log_progress(update: dict) -> None:
    phase = update.get("phase", "?")
    current = update.get("current", 0)
    total = update.get("total", 0)
    message = update.get("message")
    if message:
        logger.info("CSV import [%s] %s (%s/%s)", phase, message, current, total)
    elif total:
        logger.info("CSV import [%s] %s/%s", phase, current, total)
    else:
        logger.info("CSV import [%s]", phase)


@router.post("/import-csv")
async def import_csv(
    file: UploadFile | None = None,
    replace: bool = True,
    user: User = Depends(get_current_user),
):
    if not file or not file.filename:
        raise HTTPException(400, "Upload a CSV file (multipart form field: file)")
    content = await file.read(COLLECTION_CSV_MAX_BYTES + 1)
    if len(content) > COLLECTION_CSV_MAX_BYTES:
        max_mb = COLLECTION_CSV_MAX_BYTES // (1024 * 1024)
        raise HTTPException(413, f"CSV file too large (max {max_mb} MB)")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(content)
        path = tmp.name

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    started = time.monotonic()

    def on_progress(update: dict) -> None:
        payload = _progress_event(update, started)
        _log_progress(update)
        loop.call_soon_threadsafe(queue.put_nowait, ("event", payload))

    def worker() -> None:
        try:
            result = import_collection_csv(
                path,
                user_id=user.id,
                replace=replace,
                progress_callback=on_progress,
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                (
                    "event",
                    {
                        "type": "done",
                        "imported": result.imported,
                        "merged": result.merged,
                        "rejected_count": len(result.rejected),
                        "rejected_csv": _rejected_csv_text(result),
                    },
                ),
            )
        except Exception as exc:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("event", {"type": "error", "detail": str(exc)}),
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("close", None))
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    threading.Thread(target=worker, daemon=True).start()

    async def event_stream():
        started_payload = build_progress_event(
            phase="started",
            message="Starting import…",
            started=started,
        )
        yield json.dumps(started_payload) + "\n"
        while True:
            kind, payload = await queue.get()
            if kind == "close":
                break
            yield json.dumps(payload) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
