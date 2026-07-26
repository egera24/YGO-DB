from datetime import datetime, date
import re

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from ygo_app.collection_identity import (
    COLLECTION_CONDITIONS,
    COLLECTION_EDITIONS,
    COLLECTION_NOTES_MAX_LENGTH,
    normalize_collection_condition,
    normalize_collection_edition,
    normalize_collection_notes,
)


class PrintingOut(BaseModel):
    id: int
    set_name: str | None
    set_code: str
    set_rarity: str | None
    set_rarity_code: str
    set_price: str | None
    owned_quantity: int = 0
    trade_quantity: int = 0
    collection_item_id: int | None = None
    collection_variant_count: int = 0
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
    passcode: int | None = None
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
    trade_quantity: int = 0
    banlist_status: str | None = None
    genesys_points: int | None = None

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
    banlist_status: str | None = None
    genesys_points: int | None = None
    format_legal: bool | None = None


class FormatOut(BaseModel):
    code: str
    name: str
    description: str
    uses_banlist: bool
    uses_point_list: bool
    banlist_selectable: bool = False
    fixed_banlist_label: str | None = None
    zone_tooltips: dict[str, str] = Field(default_factory=dict)


class BanlistRevisionOut(BaseModel):
    id: int
    label: str
    effective_from: date | None = None
    source_list_id: str
    is_current: bool = False


class GenesysPointListOut(BaseModel):
    id: int
    label: str
    effective_from: date


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
    sell_price: float | None = None
    notes: str | None
    card_id: int | None = None
    image_url_small: str | None = None
    release_date: date | None = None

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


class CollectionDetailStatsOut(BaseModel):
    folder: str | None = None
    folder_label: str
    unique_printings: int
    total_quantity: int
    sum_low_price: float | None = None
    sum_avg_price: float | None = None
    sum_trend_price: float | None = None
    max_value_item: CollectionItemOut | None = None


class CollectionFilterRarityOut(BaseModel):
    rarity_code: str
    rarity_name: str | None = None


class RarityUiOut(BaseModel):
    sort_order: int
    name: str
    code: str
    normalized_code: str
    display: str
    tone: str


class CollectionFiltersOut(BaseModel):
    rarities: list[CollectionFilterRarityOut]
    editions: list[str]
    conditions: list[str]


class CollectionSuggestionsOut(BaseModel):
    values: list[str]


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

    @field_validator("folder_id")
    @classmethod
    def _require_folder_id(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("Folder is required")
        return value


class CollectionFolderDeleteResult(BaseModel):
    moved_allocations: int = 0
    moved_quantity: int = 0
    removed_allocations: int = 0
    removed_quantity: int = 0


class CollectionItemCreate(BaseModel):
    set_code: str
    rarity: str
    quantity: int = 1
    trade_quantity: int = Field(default=0, ge=0)
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
    sell_price: float | None = None
    notes: str | None = Field(default=None, max_length=COLLECTION_NOTES_MAX_LENGTH)

    @model_validator(mode="before")
    @classmethod
    def _normalize_variant_fields(cls, data):
        if not isinstance(data, dict):
            return data
        if "condition" in data:
            data["condition"] = normalize_collection_condition(data.get("condition"))
        if "printing" in data:
            data["printing"] = normalize_collection_edition(data.get("printing"))
        return data

    @model_validator(mode="after")
    def _require_folder(self):
        needs_folder = self.quantity >= 1 or self.trade_quantity >= 1
        if not needs_folder:
            return self
        if self.folder_allocations:
            return self
        if self.folder_id is None:
            raise ValueError("Folder is required")
        return self

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return normalize_collection_notes(value)


COLLECTION_LANGUAGES = (
    "English",
    "French",
    "Italian",
    "German",
    "Spanish",
    "Portuguese",
)


class CollectionItemUpdate(BaseModel):
    quantity: int | None = None
    trade_quantity: int | None = Field(default=None, ge=0)
    set_code: str | None = None
    rarity: str | None = None
    condition: str | None = None
    printing: str | None = None
    folder_allocations: list[FolderAllocation] | None = None
    sell_price: float | None = None
    notes: str | None = Field(default=None, max_length=COLLECTION_NOTES_MAX_LENGTH)

    @model_validator(mode="before")
    @classmethod
    def _normalize_variant_fields(cls, data):
        if not isinstance(data, dict):
            return data
        if "condition" in data:
            data["condition"] = normalize_collection_condition(data.get("condition"))
        if "printing" in data:
            data["printing"] = normalize_collection_edition(data.get("printing"))
        return data

    @field_validator("condition")
    @classmethod
    def _validate_condition(cls, value: str | None) -> str | None:
        if value is not None and value not in COLLECTION_CONDITIONS:
            allowed = ", ".join(COLLECTION_CONDITIONS)
            raise ValueError(f"Condition must be one of: {allowed}")
        return value

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return normalize_collection_notes(value)


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
    sort_order: int = 0
    banlist_status: str | None = None
    genesys_points: int | None = None

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
    format_code: str = "advanced"
    banlist_revision_id: int | None = None
    genesys_point_list_id: int | None = None

    model_config = {"from_attributes": True}


class ValidationIssueOut(BaseModel):
    severity: str
    code: str
    message: str
    card_id: int | None = None
    zone: str | None = None


class DeckValidationOut(BaseModel):
    errors: list[ValidationIssueOut] = Field(default_factory=list)
    warnings: list[ValidationIssueOut] = Field(default_factory=list)
    info: list[ValidationIssueOut] = Field(default_factory=list)
    main_count: int = 0
    extra_count: int = 0
    side_count: int = 0
    card_count: int = 0
    points_total: int | None = None
    points_cap: int | None = None


class DeckDetail(DeckOut):
    cards: list[DeckCardOut] = []
    validation: DeckValidationOut | None = None


class DeckCreate(BaseModel):
    name: str = Field(max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    format_code: str = "advanced"
    banlist_revision_id: int | None = None
    genesys_point_list_id: int | None = None


class DeckUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    preview_card_id: int | None = None
    format_code: str | None = None
    banlist_revision_id: int | None = None
    genesys_point_list_id: int | None = None


class DeckCardMutate(BaseModel):
    card_id: int
    zone: str = "main"
    quantity: int = 1


class DeckSave(BaseModel):
    name: str = Field(max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    format_code: str = "advanced"
    banlist_revision_id: int | None = None
    genesys_point_list_id: int | None = None
    preview_card_id: int | None = None
    cards: list[DeckCardMutate] = Field(default_factory=list)


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
        "for_trade_only",
        "tag",
        "format",
        "banlist_revision_id",
        "banlist_status",
        "genesys_point_list_id",
        "points_min",
        "points_max",
        "sort",
        "sort_dir",
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


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _HTML_TAG_RE.sub("", value).strip()
    return cleaned or None


class TradeSettingsOut(BaseModel):
    slug: str
    display_name: str | None = None
    trade_url: str


class TradeSettingsUpdateIn(BaseModel):
    slug: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        return name or None


class PublicTradeSellerOut(BaseModel):
    display_name: str | None = None


class PublicTradeCardOut(BaseModel):
    id: int
    passcode: int | None = None
    name: str
    type: str | None = None
    category: str | None = None
    types: list[str] = Field(default_factory=list)
    mechanic: str | None = None
    attribute: str | None = None
    level: int | None = None
    rank: int | None = None
    link_rating: int | None = None
    pendulum_scale: int | None = None
    link_markers: list[str] = Field(default_factory=list)
    archetype: str | None = None
    atk: int | None = None
    def_: int | None = Field(None, serialization_alias="def")
    desc: str | None = None
    image_url: str | None = None
    image_url_small: str | None = None

    model_config = {"populate_by_name": True}


class PublicTradeItemOut(BaseModel):
    item_id: int
    card_name: str | None
    set_code: str
    set_name: str | None
    rarity_code: str
    rarity_display: str | None = None
    rarity_name: str | None = None
    edition: str | None = None
    condition: str | None
    trade_quantity: int
    sell_price: float | None = None
    image_url_small: str | None = None
    card: PublicTradeCardOut | None = None


class PublicTradeListOut(BaseModel):
    seller: PublicTradeSellerOut
    items: list[PublicTradeItemOut]
    total: int
    limit: int
    offset: int


class PublicTradeRarityOptionOut(BaseModel):
    rarity_code: str
    rarity_name: str | None = None


class PublicTradeSetOptionOut(BaseModel):
    expansion_code: str
    set_name: str | None = None


class PublicTradeFiltersOut(BaseModel):
    sets: list[PublicTradeSetOptionOut] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    rarities: list[PublicTradeRarityOptionOut] = Field(default_factory=list)


class TradeOrderLineIn(BaseModel):
    item_id: int
    quantity: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)
    offer_price: float | None = Field(default=None, ge=0)

    @field_validator("comment")
    @classmethod
    def sanitize_comment(cls, value: str | None) -> str | None:
        return _strip_html(value)


class TradeOrderRequestIn(BaseModel):
    lines: list[TradeOrderLineIn] = Field(min_length=1)
    name: str | None = Field(default=None, max_length=128)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    gdpr_consent: bool
    send_copy_to_buyer: bool = False
    turnstile_token: str | None = None

    @field_validator("name", "phone", "address")
    @classmethod
    def sanitize_text(cls, value: str | None) -> str | None:
        return _strip_html(value)

    @model_validator(mode="after")
    def require_consent(self):
        if not self.gdpr_consent:
            raise ValueError("GDPR consent is required")
        if self.send_copy_to_buyer and not self.email:
            raise ValueError("Email is required when requesting a copy")
        return self


class TradeOrderRequestOut(BaseModel):
    message: str


class TradeLockLineOut(BaseModel):
    line_id: int
    collection_item_id: int | None = None
    card_name: str | None = None
    set_code: str
    set_name: str | None = None
    rarity_code: str
    rarity_display: str | None = None
    condition: str | None = None
    quantity: int
    comment: str | None = None
    offer_price: float | None = None
    list_price: float | None = None


class TradeLockOrderOut(BaseModel):
    order_id: int
    created_at: datetime
    buyer_name: str | None = None
    buyer_email: str | None = None
    buyer_phone: str | None = None
    buyer_address: str | None = None
    lines: list[TradeLockLineOut]


class TradeLocksOut(BaseModel):
    orders: list[TradeLockOrderOut]


class TradeLockLineActionIn(BaseModel):
    line_id: int
    quantity: int = Field(ge=1)


class TradeLockActionIn(BaseModel):
    lines: list[TradeLockLineActionIn] = Field(min_length=1)


class TradeLockActionOut(BaseModel):
    updated: int
    action: str


class PublicConfigOut(BaseModel):
    turnstile_site_key: str | None = None
    base_currency: str = "EUR"
    eur_huf_rate: float
    eur_huf_rate_source: str
    eur_huf_rate_as_of: str | None = None


class BulkGridBaselineOut(BaseModel):
    quantity: int = 0
    trade_quantity: int = 0
    folder_name: str | None = None
    collection_item_id: int | None = None


class BulkGridRowOut(BaseModel):
    row_id: str
    printing_id: int
    collection_item_id: int | None = None
    allocation_id: int | None = None
    folder_id: int | None = None
    folder_name: str | None = None
    quantity: int = 0
    trade_quantity: int = 0
    total_quantity: int = 0
    card_name: str | None = None
    expansion_code: str | None = None
    set_name: str | None = None
    set_code: str
    rarity_name: str | None = None
    rarity_code: str
    rarity_sort_order: int = 9999
    condition: str
    edition: str
    language: str
    price_bought: float | None = None
    date_bought: str | None = None
    owned: bool = False
    baseline: BulkGridBaselineOut


class BulkGridListOut(BaseModel):
    rows: list[BulkGridRowOut]
    total: int
    set_code: str


class BulkGridMetaOut(BaseModel):
    folders: list[CollectionFolderOut]
    conditions: list[str]
    editions: list[str]
    languages: list[str]


class BulkGridBaselineIn(BaseModel):
    quantity: int = 0
    trade_quantity: int = 0
    folder_name: str | None = None
    collection_item_id: int | None = None


class BulkGridChange(BaseModel):
    row_id: str
    printing_id: int
    collection_item_id: int | None = None
    allocation_id: int | None = None
    set_code: str
    rarity_code: str
    folder_name: str | None = None
    quantity: int = Field(default=0, ge=0)
    trade_quantity: int = Field(default=0, ge=0)
    condition: str = "NearMint"
    edition: str = "1st Edition"
    language: str = "English"
    price_bought: float | None = None
    date_bought: str | None = None
    baseline: BulkGridBaselineIn
    is_client_duplicate: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_variant_fields(cls, data):
        if not isinstance(data, dict):
            return data
        if "condition" in data:
            data["condition"] = normalize_collection_condition(data.get("condition"))
        if "edition" in data:
            data["edition"] = normalize_collection_edition(data.get("edition"))
        return data

    @field_validator("condition")
    @classmethod
    def _validate_condition(cls, value: str | None) -> str | None:
        if value is not None and value not in COLLECTION_CONDITIONS:
            allowed = ", ".join(COLLECTION_CONDITIONS)
            raise ValueError(f"Condition must be one of: {allowed}")
        return value

    @field_validator("edition")
    @classmethod
    def _validate_edition(cls, value: str | None) -> str | None:
        if value is not None and value not in COLLECTION_EDITIONS:
            allowed = ", ".join(COLLECTION_EDITIONS)
            raise ValueError(f"Edition must be one of: {allowed}")
        return value

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        if value is not None and value not in COLLECTION_LANGUAGES:
            allowed = ", ".join(COLLECTION_LANGUAGES)
            raise ValueError(f"Language must be one of: {allowed}")
        return value


class BulkGridSaveIn(BaseModel):
    set_code: str
    changes: list[BulkGridChange] = Field(default_factory=list, max_length=500)


class BulkGridSaveResult(BaseModel):
    printings_updated: int = 0
    quantities_added: int = 0
    trade_quantities_added: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_deleted: int = 0
