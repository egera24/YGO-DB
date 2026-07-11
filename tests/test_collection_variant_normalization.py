"""Condition/edition alias normalization across import, API, and backfill."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.collection_variant_backfill import normalize_collection_variants_in_db
from ygo_app.import_data import import_collection_csv
from ygo_app.models import (
    Base,
    Card,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    User,
)
from ygo_app.schemas import CollectionItemUpdate
from ygo_app.services import _collection_item_row


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


class TestCollectionVariantNormalization(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="variant@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        session.add(
            Printing(
                card_id=89631139,
                set_code="LOB-001",
                set_rarity_code="(UR)",
                set_rarity="Ultra Rare",
            )
        )
        session.commit()
        session.close()

        self.session_factory_patcher = patch(
            "ygo_app.import_data.SessionLocal", self.Session
        )
        self.init_db_patcher = patch("ygo_app.import_data.init_db", lambda: None)
        self.session_factory_patcher.start()
        self.init_db_patcher.start()

    def tearDown(self):
        self.init_db_patcher.stop()
        self.session_factory_patcher.stop()
        self.engine.dispose()

    def test_import_merges_condition_aliases_in_same_file(self):
        csv_path = Path(self._tmp.name).with_suffix(".alias-merge.csv")
        fieldnames = ["Card Number", "Rarity", "Quantity", "Condition", "Printing"]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "1",
                    "Condition": "Light Played",
                    "Printing": "Unlimited",
                }
            )
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "2",
                    "Condition": "LightPlayed",
                    "Printing": "Unlimited",
                }
            )

        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.merged, 1)

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.condition, "LightPlayed")

    def test_collection_item_row_normalizes_aliases_for_api(self):
        session = self.Session()
        printing = session.execute(select(Printing)).scalar_one()
        item = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            quantity=1,
            condition="Light Played",
            edition="First Edition",
            printing_id=printing.id,
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        row = _collection_item_row(item)
        session.close()
        self.assertEqual(row["condition"], "LightPlayed")
        self.assertEqual(row["printing"], "1st Edition")

    def test_collection_item_update_accepts_condition_alias(self):
        update = CollectionItemUpdate(condition="Light Played")
        self.assertEqual(update.condition, "LightPlayed")

    def test_collection_item_update_rejects_unknown_condition(self):
        with self.assertRaises(ValidationError):
            CollectionItemUpdate(condition="Heavily Played")

    def test_backfill_merges_alias_duplicate_rows(self):
        session = self.Session()
        printing = session.execute(select(Printing)).scalar_one()
        item_a = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            quantity=1,
            condition="Light Played",
            edition="Unlimited",
            printing_id=printing.id,
        )
        item_b = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            quantity=2,
            condition="LightPlayed",
            edition="Unlimited",
            printing_id=printing.id,
        )
        session.add_all([item_a, item_b])
        session.flush()
        session.add_all(
            [
                CollectionItemFolder(collection_item_id=item_a.id, folder_id=None, quantity=1),
                CollectionItemFolder(collection_item_id=item_b.id, folder_id=None, quantity=2),
            ]
        )
        session.commit()
        session.close()

        session = self.Session()
        stats = normalize_collection_variants_in_db(session, user_id=self.user_id)
        items = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        session.close()

        self.assertEqual(stats["rows_merged"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].quantity, 3)
        self.assertEqual(items[0].condition, "LightPlayed")


if __name__ == "__main__":
    unittest.main()
