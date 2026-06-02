import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user
from ygo_app.database import get_db
from ygo_app.import_data import import_collection_csv
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


@router.post("/import-csv")
async def import_csv(
    file: UploadFile | None = None,
    replace: bool = True,
    user: User = Depends(get_current_user),
):
    if not file or not file.filename:
        raise HTTPException(400, "Upload a CSV file (multipart form field: file)")
    suffix = ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        path = tmp.name
    count = import_collection_csv(path, user_id=user.id, replace=replace)
    return {"imported": count}
