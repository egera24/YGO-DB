from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user
from ygo_app.database import get_db
from ygo_app.models import User
from ygo_app.schemas import SearchPresetCreate, SearchPresetOut, SearchPresetUpdate
from ygo_app.services import (
    SearchPresetConflictError,
    _search_preset_out,
    create_search_preset,
    delete_search_preset,
    list_search_presets,
    update_search_preset,
)

router = APIRouter(prefix="/search-presets", tags=["search-presets"])


def _to_out(preset) -> SearchPresetOut:
    return SearchPresetOut(**_search_preset_out(preset))


@router.get("", response_model=list[SearchPresetOut])
def list_presets(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    presets = list_search_presets(db, user.id)
    return [_to_out(p) for p in presets]


@router.post("", response_model=SearchPresetOut)
def create_preset(
    body: SearchPresetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        preset = create_search_preset(
            db,
            user.id,
            body.name,
            body.params,
            overwrite=body.overwrite,
        )
    except SearchPresetConflictError:
        raise HTTPException(
            409,
            f"A preset named '{body.name}' already exists",
        ) from None
    return _to_out(preset)


@router.patch("/{preset_id}", response_model=SearchPresetOut)
def patch_preset(
    preset_id: int,
    body: SearchPresetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        preset = update_search_preset(
            db,
            preset_id,
            user.id,
            name=body.name,
            params=body.params,
        )
    except SearchPresetConflictError:
        raise HTTPException(
            409,
            f"A preset named '{body.name}' already exists",
        ) from None
    if not preset:
        raise HTTPException(404, "Preset not found")
    return _to_out(preset)


@router.delete("/{preset_id}")
def remove_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not delete_search_preset(db, preset_id, user.id):
        raise HTTPException(404, "Preset not found")
    return {"ok": True}
