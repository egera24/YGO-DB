import asyncio
import csv
import io
import json
import tempfile
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user
from ygo_app.database import get_db
from ygo_app.import_data import CollectionImportResult, import_collection_csv
from ygo_app.import_progress import eta_seconds
from ygo_app.models import CollectionItem, User
from ygo_app.schemas import CollectionItemCreate, CollectionItemOut, CollectionItemUpdate
from ygo_app.services import add_collection_item, find_card_by_set_code, list_collection

router = APIRouter(prefix="/collection", tags=["collection"])


def _item_out(db: Session, item: CollectionItem) -> CollectionItemOut:
    card = find_card_by_set_code(db, item.set_code)
    return CollectionItemOut(
        id=item.id,
        set_code=item.set_code,
        rarity_code=item.rarity_code,
        card_name=item.card_name,
        expansion_code=item.expansion_code,
        set_name=item.set_name,
        quantity=item.quantity,
        trade_quantity=item.trade_quantity,
        condition=item.condition,
        printing=item.edition,
        language=item.language,
        folder_name=item.folder_name,
        price_bought=item.price_bought,
        date_bought=item.date_bought,
        avg_price=item.avg_price,
        low_price=item.low_price,
        trend_price=item.trend_price,
        notes=item.notes,
        card_id=card.id if card else None,
        image_url_small=card.image_url_small if card else None,
    )


@router.get("", response_model=list[CollectionItemOut])
def get_collection(
    q: str | None = None,
    folder: str | None = None,
    set_code: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, _total = list_collection(
        db,
        user_id=user.id,
        q=q,
        folder=folder,
        set_code=set_code,
        limit=limit,
        offset=offset,
    )
    return [CollectionItemOut(**item) for item in items]


@router.post("", response_model=CollectionItemOut)
def create_item(
    body: CollectionItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = add_collection_item(db, user.id, body.model_dump())
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
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
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
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
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
