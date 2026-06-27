from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ygo_app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    collection_items: Mapped[list["CollectionItem"]] = relationship(back_populates="user")
    collection_folders: Mapped[list["CollectionFolder"]] = relationship(
        back_populates="user"
    )
    decks: Mapped[list["Deck"]] = relationship(back_populates="user")
    favorites: Mapped[list["UserFavorite"]] = relationship(back_populates="user")
    card_tags: Mapped[list["UserCardTag"]] = relationship(back_populates="user")
    search_presets: Mapped[list["SearchPreset"]] = relationship(back_populates="user")


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    otp_hash: Mapped[str] = mapped_column(String(64))
    otp_expires_at: Mapped[datetime] = mapped_column(DateTime)
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime)


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    type: Mapped[str | None] = mapped_column(String(64), index=True)
    human_readable_type: Mapped[str | None] = mapped_column(String(128))
    frame_type: Mapped[str | None] = mapped_column(String(32), index=True)
    desc: Mapped[str | None] = mapped_column(Text)
    atk: Mapped[int | None] = mapped_column(Integer)
    def_: Mapped[int | None] = mapped_column("def", Integer)
    level: Mapped[int | None] = mapped_column(Integer)
    race: Mapped[str | None] = mapped_column(String(64), index=True)
    attribute: Mapped[str | None] = mapped_column(String(32), index=True)
    archetype: Mapped[str | None] = mapped_column(String(128), index=True)
    linkval: Mapped[int | None] = mapped_column(Integer)
    scale: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str | None] = mapped_column(String(16), index=True)
    types: Mapped[str | None] = mapped_column(Text)
    mechanic: Mapped[str | None] = mapped_column(String(64), index=True)
    rank: Mapped[int | None] = mapped_column(Integer, index=True)
    link_rating: Mapped[int | None] = mapped_column(Integer, index=True)
    pendulum_scale: Mapped[int | None] = mapped_column(Integer)
    link_markers: Mapped[str | None] = mapped_column(Text)
    summoning_condition: Mapped[str | None] = mapped_column(Text)
    ygoprodeck_url: Mapped[str | None] = mapped_column(String(512))
    image_url: Mapped[str | None] = mapped_column(String(512))
    image_url_small: Mapped[str | None] = mapped_column(String(512))
    has_errata: Mapped[bool] = mapped_column(Boolean, default=False)
    last_erratum_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tips: Mapped[str | None] = mapped_column(Text)

    printings: Mapped[list["Printing"]] = relationship(back_populates="card")
    errata_versions: Mapped[list["CardErrataVersion"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    deck_entries: Mapped[list["DeckCard"]] = relationship(back_populates="card")
    user_favorites: Mapped[list["UserFavorite"]] = relationship(back_populates="card")
    user_tags: Mapped[list["UserCardTag"]] = relationship(back_populates="card")


class TcgSet(Base):
    __tablename__ = "tcg_sets"

    abbr: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    set_type: Mapped[str | None] = mapped_column(String(128))
    series: Mapped[str | None] = mapped_column(String(256))
    region: Mapped[str] = mapped_column(String(8), default="TCG")
    release_date: Mapped[date | None] = mapped_column(Date)


class CardErrataVersion(Base):
    __tablename__ = "card_errata_versions"

    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String(32), primary_key=True)
    version_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_label: Mapped[str] = mapped_column(String(64))
    lore_text: Mapped[str | None] = mapped_column(Text)
    lore_html: Mapped[str | None] = mapped_column(Text)
    set_code: Mapped[str | None] = mapped_column(String(32))
    set_name: Mapped[str | None] = mapped_column(String(256))
    release_date: Mapped[date | None] = mapped_column(Date)

    card: Mapped["Card"] = relationship(back_populates="errata_versions")


class Printing(Base):
    __tablename__ = "printings"
    __table_args__ = (
        UniqueConstraint("card_id", "set_code", "set_rarity_code", name="uq_printing"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    set_name: Mapped[str | None] = mapped_column(String(256))
    set_code: Mapped[str] = mapped_column(String(32), index=True)
    set_rarity: Mapped[str | None] = mapped_column(String(64))
    set_rarity_code: Mapped[str] = mapped_column(String(64), index=True)
    set_price: Mapped[str | None] = mapped_column(String(32))

    card: Mapped["Card"] = relationship(back_populates="printings")
    collection_items: Mapped[list["CollectionItem"]] = relationship(
        back_populates="linked_printing"
    )


class CollectionItem(Base):
    """Physical ownership keyed by set code (card number) + rarity, per user."""

    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    set_code: Mapped[str] = mapped_column(String(32), index=True)
    rarity_code: Mapped[str] = mapped_column(String(64), index=True)
    card_name: Mapped[str | None] = mapped_column(String(256))
    expansion_code: Mapped[str | None] = mapped_column(String(32))
    set_name: Mapped[str | None] = mapped_column(String(256))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    trade_quantity: Mapped[int] = mapped_column(Integer, default=0)
    condition: Mapped[str | None] = mapped_column(String(32))
    edition: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(32))
    price_bought: Mapped[float | None] = mapped_column(Float)
    date_bought: Mapped[str | None] = mapped_column(String(32))
    avg_price: Mapped[float | None] = mapped_column(Float)
    low_price: Mapped[float | None] = mapped_column(Float)
    trend_price: Mapped[float | None] = mapped_column(Float)
    sell_price: Mapped[float | None] = mapped_column(Float)
    printing_id: Mapped[int | None] = mapped_column(ForeignKey("printings.id"), index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="collection_items")
    linked_printing: Mapped["Printing | None"] = relationship(
        back_populates="collection_items"
    )
    folder_allocations: Mapped[list["CollectionItemFolder"]] = relationship(
        back_populates="collection_item",
        cascade="all, delete-orphan",
    )


class CollectionFolder(Base):
    __tablename__ = "collection_folders"
    __table_args__ = (
        UniqueConstraint("user_id", "name_key", name="uq_collection_folder_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    name_key: Mapped[str] = mapped_column(String(128), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="collection_folders")
    item_allocations: Mapped[list["CollectionItemFolder"]] = relationship(
        back_populates="folder"
    )


class CollectionItemFolder(Base):
    __tablename__ = "collection_item_folders"
    __table_args__ = (
        UniqueConstraint(
            "collection_item_id",
            "folder_id",
            name="uq_collection_item_folder",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_item_id: Mapped[int] = mapped_column(
        ForeignKey("collection_items.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_folders.id", ondelete="SET NULL"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    collection_item: Mapped["CollectionItem"] = relationship(
        back_populates="folder_allocations"
    )
    folder: Mapped["CollectionFolder | None"] = relationship(
        back_populates="item_allocations"
    )


class UserFavorite(Base):
    __tablename__ = "user_favorites"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_user_favorite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)

    user: Mapped["User"] = relationship(back_populates="favorites")
    card: Mapped["Card"] = relationship(back_populates="user_favorites")


class UserCardTag(Base):
    __tablename__ = "user_card_tags"
    __table_args__ = (UniqueConstraint("user_id", "card_id", "tag", name="uq_user_card_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)

    user: Mapped["User"] = relationship(back_populates="card_tags")
    card: Mapped["Card"] = relationship(back_populates="user_tags")


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    preview_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="decks")
    cards: Mapped[list["DeckCard"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan"
    )


class DeckCard(Base):
    __tablename__ = "deck_cards"
    __table_args__ = (
        UniqueConstraint("deck_id", "card_id", "zone", name="uq_deck_card_zone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    zone: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    deck: Mapped["Deck"] = relationship(back_populates="cards")
    card: Mapped["Card"] = relationship(back_populates="deck_entries")


class PrintingMarketPrice(Base):
    """Cardmarket LOW/AVG/TREND keyed by set code + rarity (survives catalog re-import)."""

    __tablename__ = "printing_market_prices"

    set_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    rarity_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    cardmarket_product_id: Mapped[int | None] = mapped_column(Integer)
    cardmarket_url: Mapped[str | None] = mapped_column(String(512))
    low_price: Mapped[float | None] = mapped_column(Float)
    avg_price: Mapped[float | None] = mapped_column(Float)
    trend_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    discovery_status: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class CardmarketExpansion(Base):
    __tablename__ = "cardmarket_expansions"

    expansion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expansion_code: Mapped[str | None] = mapped_column(String(32), index=True)
    expansion_name: Mapped[str] = mapped_column(String(256))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class SearchPreset(Base):
    __tablename__ = "search_presets"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_search_preset_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    params: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship(back_populates="search_presets")
