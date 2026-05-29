from datetime import datetime

from sqlalchemy import (
    Boolean,
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
    ygoprodeck_url: Mapped[str | None] = mapped_column(String(512))
    image_url: Mapped[str | None] = mapped_column(String(512))
    image_url_small: Mapped[str | None] = mapped_column(String(512))
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    printings: Mapped[list["Printing"]] = relationship(back_populates="card")
    tags: Mapped[list["CardTag"]] = relationship(back_populates="card", cascade="all, delete-orphan")
    deck_entries: Mapped[list["DeckCard"]] = relationship(back_populates="card")


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
    set_rarity_code: Mapped[str] = mapped_column(String(16), index=True)
    set_price: Mapped[str | None] = mapped_column(String(32))

    card: Mapped["Card"] = relationship(back_populates="printings")
    collection_items: Mapped[list["CollectionItem"]] = relationship(back_populates="linked_printing")


class CollectionItem(Base):
    """Physical ownership keyed by set code (card number) + rarity."""

    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_code: Mapped[str] = mapped_column(String(32), index=True)
    rarity_code: Mapped[str] = mapped_column(String(16), index=True)
    card_name: Mapped[str | None] = mapped_column(String(256))
    expansion_code: Mapped[str | None] = mapped_column(String(32))
    set_name: Mapped[str | None] = mapped_column(String(256))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    trade_quantity: Mapped[int] = mapped_column(Integer, default=0)
    condition: Mapped[str | None] = mapped_column(String(32))
    edition: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(32))
    folder_name: Mapped[str | None] = mapped_column(String(128), index=True)
    price_bought: Mapped[float | None] = mapped_column(Float)
    date_bought: Mapped[str | None] = mapped_column(String(32))
    avg_price: Mapped[float | None] = mapped_column(Float)
    low_price: Mapped[float | None] = mapped_column(Float)
    trend_price: Mapped[float | None] = mapped_column(Float)
    printing_id: Mapped[int | None] = mapped_column(ForeignKey("printings.id"), index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    linked_printing: Mapped["Printing | None"] = relationship(back_populates="collection_items")


class CardTag(Base):
    __tablename__ = "card_tags"
    __table_args__ = (UniqueConstraint("card_id", "tag", name="uq_card_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)

    card: Mapped["Card"] = relationship(back_populates="tags")


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

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
