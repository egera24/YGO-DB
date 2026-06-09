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

from ygo_app.collection_export import export_collection_csv, list_export_formats

from ygo_app.database import get_db

from ygo_app.import_data import CollectionImportResult, import_collection_csv

from ygo_app.import_progress import eta_seconds

from ygo_app.models import CollectionItem, Printing, User

from ygo_app.schemas import (

    CollectionItemCreate,

    CollectionItemOut,

    CollectionItemUpdate,

    CollectionListOut,

    CollectionStatsOut,

    FolderRenameRequest,

    FolderRenameResult,

)

from ygo_app.services import (

    _collection_item_row,

    add_collection_item,

    collection_stats,

    list_collection,

    rename_collection_folder,

)



router = APIRouter(prefix="/collection", tags=["collection"])





def _item_out(item: CollectionItem) -> CollectionItemOut:

    return CollectionItemOut(**_collection_item_row(item))





def _load_item_with_card(db: Session, item_id: int, user_id: int) -> CollectionItem | None:

    item = db.execute(

        select(CollectionItem)

        .options(joinedload(CollectionItem.linked_printing).joinedload(Printing.card))

        .where(CollectionItem.id == item_id, CollectionItem.user_id == user_id)

    ).unique().scalar_one_or_none()

    return item





@router.get("/stats", response_model=CollectionStatsOut)

def get_collection_stats(

    db: Session = Depends(get_db),

    user: User = Depends(get_current_user),

):

    return collection_stats(db, user_id=user.id)





@router.patch("/folders/rename", response_model=FolderRenameResult)

def rename_folder(

    body: FolderRenameRequest,

    db: Session = Depends(get_db),

    user: User = Depends(get_current_user),

):

    try:

        updated = rename_collection_folder(

            db,

            user_id=user.id,

            from_name=body.from_name,

            to_name=body.to_name,

        )

    except ValueError as exc:

        raise HTTPException(400, str(exc)) from exc

    return FolderRenameResult(updated=updated)





@router.get("", response_model=CollectionListOut)

def get_collection(

    q: str | None = None,

    folder: str | None = None,

    set_code: str | None = None,

    sort: str = Query("set_code", pattern="^(set_code|card_name|folder_name|quantity)$"),

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

    db: Session = Depends(get_db),

    user: User = Depends(get_current_user),

):

    try:

        csv_text, media_type, filename = export_collection_csv(

            db, user_id=user.id, format_id=format

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

    item = add_collection_item(db, user.id, body.model_dump())

    item = _load_item_with_card(db, item.id, user.id) or item

    return _item_out(item)





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

    data = body.model_dump(exclude_unset=True)

    if "printing" in data:

        data["edition"] = data.pop("printing")

    for field, value in data.items():

        setattr(item, field, value)

    db.commit()

    item = _load_item_with_card(db, item_id, user.id) or item

    return _item_out(item)





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

