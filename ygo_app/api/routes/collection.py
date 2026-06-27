import asyncio
import csv
import io
import json
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.auth import get_current_user
from ygo_app.cardmarket.market_prices import load_market_prices
from ygo_app.collection_export import export_collection_csv, list_export_formats
from ygo_app.config import COLLECTION_CSV_MAX_BYTES
from ygo_app.database import get_db
from ygo_app.import_data import CollectionImportResult, import_collection_csv
from ygo_app.import_progress import eta_seconds
from ygo_app.models import CollectionItem, CollectionItemFolder, Printing, User
from ygo_app.schemas import (
    CollectionFolderCreate,
    CollectionFolderDeleteResult,
    CollectionFolderOut,
    CollectionFolderUpdate,
    CollectionItemCreate,
    CollectionItemOut,
    CollectionItemUpdate,
    CollectionListOut,
    CollectionStatsOut,
)
from ygo_app.services import (
    FolderConflictError,
    _collection_item_row,
    add_collection_item,
    collection_stats,
    create_collection_folder,
    delete_collection_folder,
    list_collection,
    list_collection_folders,
    update_collection_folder,
    update_collection_item,
)

router = APIRouter(prefix="/collection", tags=["collection"])


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
    folder: str | None = None,
    set_code: str | None = None,
    sort: str = Query("set_code", pattern="^(set_code|card_name|folder_name|quantity|trade_quantity)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = list_collection(
        db,
        user_id=user.id,
        q=q,
        folder=folder,
        set_code=set_code,
        sort=sort,
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


def _progress_event(current: int, total: int, started: float) -> dict:
    eta = eta_seconds(current, total, started)
    percent = round(100 * current / total) if total else 0
    return {
        "type": "progress",
        "current": current,
        "total": total,
        "percent": percent,
        "eta_seconds": round(eta, 1) if eta is not None else None,
    }


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

    def on_progress(current: int, total: int) -> None:
        payload = _progress_event(current, total, started)
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
