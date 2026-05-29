from datetime import datetime

from pydantic import BaseModel, Field


class PrintingOut(BaseModel):
    id: int
    set_name: str | None
    set_code: str
    set_rarity: str | None
    set_rarity_code: str
    set_price: str | None
    owned_quantity: int = 0

    model_config = {"from_attributes": True}


class CardSearchPage(BaseModel):
    items: list["CardSummary"]
    total: int
    limit: int
    offset: int


class CardSummary(BaseModel):
    id: int
    name: str
    type: str | None
    frame_type: str | None
    atk: int | None
    def_: int | None = Field(None, serialization_alias="def")
    level: int | None
    race: str | None
    attribute: str | None
    archetype: str | None
    image_url_small: str | None
    is_favorite: bool
    owned: bool = False
    owned_quantity: int = 0

    model_config = {"from_attributes": True, "populate_by_name": True}


class CardDetail(CardSummary):
    human_readable_type: str | None
    desc: str | None
    linkval: int | None
    scale: int | None
    ygoprodeck_url: str | None
    image_url: str | None
    printings: list[PrintingOut] = []
    tags: list[str] = []


class CollectionItemOut(BaseModel):
    id: int
    set_code: str
    rarity_code: str
    card_name: str | None
    expansion_code: str | None
    set_name: str | None
    quantity: int
    trade_quantity: int
    condition: str | None
    printing: str | None
    language: str | None
    folder_name: str | None
    price_bought: float | None
    date_bought: str | None
    avg_price: float | None
    low_price: float | None
    trend_price: float | None
    notes: str | None
    card_id: int | None = None
    image_url_small: str | None = None

    model_config = {"from_attributes": True}


class CollectionItemCreate(BaseModel):
    set_code: str
    rarity: str
    quantity: int = 1
    trade_quantity: int = 0
    card_name: str | None = None
    expansion_code: str | None = None
    set_name: str | None = None
    condition: str | None = "NearMint"
    printing: str | None = "Unlimited"
    language: str | None = "English"
    folder_name: str | None = None
    price_bought: float | None = None
    date_bought: str | None = None
    notes: str | None = None


class CollectionItemUpdate(BaseModel):
    quantity: int | None = None
    trade_quantity: int | None = None
    condition: str | None = None
    printing: str | None = None
    folder_name: str | None = None
    notes: str | None = None


class DeckCardOut(BaseModel):
    card_id: int
    name: str
    type: str | None
    image_url_small: str | None
    zone: str
    quantity: int

    model_config = {"from_attributes": True}


class DeckOut(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    main_count: int = 0
    extra_count: int = 0
    side_count: int = 0

    model_config = {"from_attributes": True}


class DeckDetail(DeckOut):
    cards: list[DeckCardOut] = []


class DeckCreate(BaseModel):
    name: str
    description: str | None = None


class DeckCardMutate(BaseModel):
    card_id: int
    zone: str = "main"
    quantity: int = 1


class TagMutate(BaseModel):
    tag: str
