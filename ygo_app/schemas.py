from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


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
    category: str | None = None
    types: list[str] = Field(default_factory=list)
    mechanic: str | None = None
    rank: int | None = None
    link_rating: int | None = None
    pendulum_scale: int | None = None
    link_markers: list[str] = Field(default_factory=list)
    summoning_condition: str | None = None
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
    rarity_display: str | None = None
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


class CollectionListOut(BaseModel):
    items: list[CollectionItemOut]
    total: int
    limit: int
    offset: int


class CollectionFolderStats(BaseModel):
    name: str
    item_count: int
    quantity: int


class CollectionStatsOut(BaseModel):
    total_items: int
    total_quantity: int
    unique_printings: int
    unassigned_count: int
    unassigned_quantity: int
    folders: list[CollectionFolderStats]


class FolderRenameRequest(BaseModel):
    from_name: str
    to_name: str


class FolderRenameResult(BaseModel):
    updated: int


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


SEARCH_PRESET_PARAM_KEYS = frozenset(
    {
        "q",
        "set_code",
        "category",
        "types",
        "mechanic",
        "attribute",
        "archetype",
        "summoning_condition",
        "link_markers",
        "level_min",
        "level_max",
        "rank_min",
        "rank_max",
        "link_rating_min",
        "link_rating_max",
        "pendulum_scale_min",
        "pendulum_scale_max",
        "atk_min",
        "atk_max",
        "def_min",
        "def_max",
        "owned_only",
        "favorites_only",
    }
)


def normalize_search_preset_params(params: dict[str, str]) -> dict[str, str]:
    unknown = set(params) - SEARCH_PRESET_PARAM_KEYS
    if unknown:
        raise ValueError(f"Unknown preset params: {', '.join(sorted(unknown))}")
    cleaned: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    return cleaned


class SearchPresetOut(BaseModel):
    id: int
    name: str
    params: dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SearchPresetCreate(BaseModel):
    name: str
    params: dict[str, str] = Field(default_factory=dict)
    overwrite: bool = False

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Preset name is required")
        return name

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, str]) -> dict[str, str]:
        return normalize_search_preset_params(value)


class SearchPresetUpdate(BaseModel):
    name: str | None = None
    params: dict[str, str] | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("Preset name is required")
        return name

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return normalize_search_preset_params(value)

    @model_validator(mode="after")
    def require_field(self):
        if self.name is None and self.params is None:
            raise ValueError("At least one of name or params is required")
        return self
