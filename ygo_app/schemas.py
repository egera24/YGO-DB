from datetime import datetime, date

from pydantic import BaseModel, Field, field_validator, model_validator


class PrintingOut(BaseModel):
    id: int
    set_name: str | None
    set_code: str
    set_rarity: str | None
    set_rarity_code: str
    set_price: str | None
    owned_quantity: int = 0
    low_price: float | None = None
    avg_price: float | None = None
    trend_price: float | None = None
    price_currency: str | None = None
    prices_updated_at: datetime | None = None

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


class CardErrataVersionOut(BaseModel):
    version_label: str
    lore_text: str | None = None
    lore_html: str | None = None
    set_code: str | None = None
    set_name: str | None = None
    release_date: date | None = None
    source_url: str | None = None

    model_config = {"from_attributes": True}


class CardTipsSectionOut(BaseModel):
    format: str
    tips: list[str] = Field(default_factory=list)


class CardDetail(CardSummary):
    human_readable_type: str | None
    desc: str | None
    linkval: int | None
    scale: int | None
    ygoprodeck_url: str | None
    image_url: str | None
    printings: list[PrintingOut] = []
    tags: list[str] = []
    has_errata: bool = False
    last_erratum_date: date | None = None
    errata: list[CardErrataVersionOut] = Field(default_factory=list)
    tips: list[CardTipsSectionOut] = Field(default_factory=list)


class FolderAllocationOut(BaseModel):
    folder_id: int | None
    name: str | None
    quantity: int


class CollectionItemOut(BaseModel):
    id: int
    set_code: str
    rarity_code: str
    rarity_display: str | None = None
    rarity_name: str | None = None
    card_name: str | None
    expansion_code: str | None
    set_name: str | None
    quantity: int
    trade_quantity: int
    condition: str | None
    printing: str | None
    language: str | None
    folders: list[FolderAllocationOut] = Field(default_factory=list)
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
    id: int
    name: str
    item_count: int
    quantity: int


class CollectionStatsOut(BaseModel):
    total_items: int
    total_quantity: int
    unique_printings: int
    no_folder_count: int
    no_folder_quantity: int
    folders: list[CollectionFolderStats]


class CollectionFolderOut(BaseModel):
    id: int
    name: str
    sort_order: int
    item_count: int = 0
    quantity: int = 0

    model_config = {"from_attributes": True}


class CollectionFolderCreate(BaseModel):
    name: str = Field(max_length=128)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Folder name is required")
        return name


class CollectionFolderUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    sort_order: int | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("Folder name is required")
        return name

    @model_validator(mode="after")
    def require_field(self):
        if self.name is None and self.sort_order is None:
            raise ValueError("At least one of name or sort_order is required")
        return self


class FolderAllocation(BaseModel):
    folder_id: int | None
    quantity: int = Field(ge=1)


class CollectionFolderDeleteResult(BaseModel):
    moved_allocations: int
    moved_quantity: int


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
    folder_id: int | None = None
    folder_allocations: list[FolderAllocation] | None = None
    price_bought: float | None = None
    date_bought: str | None = None
    notes: str | None = None


COLLECTION_CONDITIONS = (
    "Mint",
    "NearMint",
    "Excellent",
    "Good",
    "LightPlayed",
    "Played",
    "Poor",
)


class CollectionItemUpdate(BaseModel):
    quantity: int | None = None
    trade_quantity: int | None = None
    set_code: str | None = None
    rarity: str | None = None
    condition: str | None = None
    printing: str | None = None
    folder_allocations: list[FolderAllocation] | None = None
    notes: str | None = None

    @field_validator("condition")
    @classmethod
    def _validate_condition(cls, value: str | None) -> str | None:
        if value is not None and value not in COLLECTION_CONDITIONS:
            allowed = ", ".join(COLLECTION_CONDITIONS)
            raise ValueError(f"Condition must be one of: {allowed}")
        return value


class DeckPreviewCard(BaseModel):
    card_id: int
    image_url: str | None


class DeckCardOut(BaseModel):
    card_id: int
    name: str
    type: str | None
    image_url_small: str | None
    image_url: str | None = None
    zone: str
    quantity: int

    model_config = {"from_attributes": True}


class DeckOut(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    preview_card_id: int | None = None
    preview_cards: list[DeckPreviewCard] = []
    main_count: int = 0
    extra_count: int = 0
    side_count: int = 0
    card_count: int = 0

    model_config = {"from_attributes": True}


class DeckDetail(DeckOut):
    cards: list[DeckCardOut] = []


class DeckCreate(BaseModel):
    name: str = Field(max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class DeckUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    preview_card_id: int | None = None


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
        "tag",
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
    name: str = Field(max_length=128)
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
    name: str | None = Field(default=None, max_length=128)
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
