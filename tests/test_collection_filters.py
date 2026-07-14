"""Collection filter options and suggestions."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import (
    Base,
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    User,
)
from ygo_app.services import collection_filter_options, collection_suggestions, list_collection


def _sqlite_engine(path: str):
    eng = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def _add_item(
    session,
    *,
    user_id,
    set_code,
    rarity_code,
    card_name,
    set_name=None,
    edition="1st Edition",
    condition="NearMint",
    quantity=1,
    folder_id=None,
    printing_id=None,
):
    item = CollectionItem(
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        card_name=card_name,
        set_name=set_name,
        edition=edition,
        condition=condition,
        quantity=quantity,
        printing_id=printing_id,
    )
    session.add(item)
    session.flush()
    session.add(
        CollectionItemFolder(
            collection_item_id=item.id,
            folder_id=folder_id,
            quantity=quantity,
        )
    )
    return item


class TestCollectionFilters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="filters@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        printing = Printing(
            card_id=89631139,
            set_code="LOB-001",
            set_rarity_code="(UR)",
            set_rarity="Ultra Rare",
        )
        session.add(printing)
        session.flush()
        self.printing_id = printing.id

        _add_item(
            session,
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name="Blue-Eyes White Dragon",
            set_name="Legend of Blue Eyes",
            edition="1st Edition",
            condition="NearMint",
            printing_id=self.printing_id,
        )
        _add_item(
            session,
            user_id=self.user_id,
            set_code="MRD-001",
            rarity_code="(SR)",
            card_name="Dark Magician",
            set_name="Metal Raiders",
            edition="Unlimited",
            condition="Excellent",
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_list_filters_by_rarity_edition_condition(self):
        session = self.Session()
        items, total = list_collection(
            session,
            user_id=self.user_id,
            rarity="(UR)",
            edition="1st Edition",
            condition="NearMint",
        )
        session.close()

        self.assertEqual(total, 1)
        self.assertEqual(items[0]["card_name"], "Blue-Eyes White Dragon")

    def test_list_filters_by_card_name_and_set_name(self):
        session = self.Session()
        items, total = list_collection(
            session,
            user_id=self.user_id,
            card_name="Dark",
            set_name="Metal",
        )
        session.close()

        self.assertEqual(total, 1)
        self.assertEqual(items[0]["set_code"], "MRD-001")

    def test_filter_options_rarity_self_excludes_active_rarity(self):
        session = self.Session()
        all_opts = collection_filter_options(session, user_id=self.user_id)
        ur_opts = collection_filter_options(
            session, user_id=self.user_id, rarity="(UR)"
        )
        session.close()

        self.assertEqual(len(all_opts["rarities"]), 2)
        self.assertEqual(len(all_opts["editions"]), 2)
        self.assertEqual(len(ur_opts["rarities"]), 2)
        self.assertEqual(len(ur_opts["editions"]), 1)
        self.assertEqual(ur_opts["editions"][0], "1st Edition")

    def test_filter_options_rarities_scoped_to_folder(self):
        session = self.Session()
        folder = CollectionFolder(user_id=self.user_id, name="BIN1", name_key="bin1")
        session.add(folder)
        session.flush()

        _add_item(
            session,
            user_id=self.user_id,
            set_code="LOB-002",
            rarity_code="(ScR)",
            card_name="Exodia Head",
            folder_id=folder.id,
        )
        _add_item(
            session,
            user_id=self.user_id,
            set_code="MRD-002",
            rarity_code="(C)",
            card_name="Summoned Skull",
            folder_id=folder.id,
        )
        session.commit()

        opts = collection_filter_options(
            session,
            user_id=self.user_id,
            folder=str(folder.id),
            rarity="(ScR)",
        )
        session.close()

        rarity_codes = {row["rarity_code"] for row in opts["rarities"]}
        self.assertEqual(rarity_codes, {"(ScR)", "(C)"})

    def test_suggestions_for_card_name(self):
        session = self.Session()
        values = collection_suggestions(
            session,
            user_id=self.user_id,
            field="card_name",
            q="Blue",
        )
        session.close()

        self.assertEqual(values, ["Blue-Eyes White Dragon"])

    def test_suggestions_respect_active_filters(self):
        session = self.Session()
        values = collection_suggestions(
            session,
            user_id=self.user_id,
            field="set_name",
            rarity="(UR)",
        )
        session.close()

        self.assertEqual(values, ["Legend of Blue Eyes"])


if __name__ == "__main__":
    unittest.main()
