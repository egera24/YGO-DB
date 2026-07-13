"""Bulk collection spreadsheet grid list + save."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token
from ygo_app.database import get_db
from ygo_app.models import (
    Base,
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    RarityPriceRank,
    User,
)
from ygo_app.services import list_bulk_collection_grid, save_bulk_collection_grid


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


class TestBulkCollectionGrid(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        owner = User(
            email="bulk@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
        )
        other = User(
            email="other-bulk@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
        )
        session.add_all([owner, other])
        session.flush()
        self.owner_id = owner.id
        self.other_id = other.id

        session.add(
            RarityPriceRank(sort_order=18, name="Ultra Rare", rarity_code="UR")
        )
        session.add(
            RarityPriceRank(sort_order=23, name="Secret Rare", rarity_code="ScR")
        )

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        session.add_all(
            [
                Printing(
                    card_id=card.id,
                    set_code="RA03-EN015",
                    set_name="Quarter Century Bonanza",
                    set_rarity_code="(UR)",
                    set_rarity="Ultra Rare",
                ),
                Printing(
                    card_id=card.id,
                    set_code="RA03-EN015",
                    set_name="Quarter Century Bonanza",
                    set_rarity_code="(ScR)",
                    set_rarity="Secret Rare",
                ),
                Printing(
                    card_id=card.id,
                    set_code="RA03-EN016",
                    set_name="Quarter Century Bonanza",
                    set_rarity_code="(UR)",
                    set_rarity="Ultra Rare",
                ),
            ]
        )
        session.flush()

        folder = CollectionFolder(
            user_id=self.owner_id, name="BOX2", name_key="box2"
        )
        session.add(folder)
        session.flush()
        self.folder_id = folder.id

        item = CollectionItem(
            user_id=self.owner_id,
            set_code="RA03-EN015",
            rarity_code="(UR)",
            card_name=card.name,
            expansion_code="RA03",
            set_name="Quarter Century Bonanza",
            quantity=1,
            trade_quantity=0,
            condition="NearMint",
            edition="1st Edition",
            language="English",
        )
        session.add(item)
        session.flush()
        self.item_id = item.id
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=self.folder_id,
                quantity=1,
            )
        )
        session.commit()
        session.close()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.owner_headers = {
            "Authorization": f"Bearer {create_access_token(self.owner_id)}"
        }
        self.other_headers = {
            "Authorization": f"Bearer {create_access_token(self.other_id)}"
        }

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_list_merges_catalog_and_owned_allocations(self):
        session = self.Session()
        rows, total, abbr = list_bulk_collection_grid(
            session, user_id=self.owner_id, set_code="RA03"
        )
        session.close()
        self.assertEqual(abbr, "RA03")
        self.assertEqual(total, 3)
        owned = [row for row in rows if row["owned"]]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["folder_name"], "BOX2")
        self.assertEqual(owned[0]["quantity"], 1)
        blank = [row for row in rows if row["row_id"].endswith("-default")]
        self.assertEqual(len(blank), 2)

    def test_list_sorts_by_rarity_rank(self):
        session = self.Session()
        rows, _, _ = list_bulk_collection_grid(
            session,
            user_id=self.owner_id,
            set_code="RA03",
            sort=[{"field": "set_code", "dir": "asc"}, {"field": "rarity_sort_order", "dir": "asc"}],
        )
        session.close()
        same_code = [row for row in rows if row["set_code"] == "RA03-EN015"]
        self.assertEqual(same_code[0]["rarity_code"], "(UR)")
        self.assertEqual(same_code[1]["rarity_code"], "(ScR)")

    def test_save_creates_new_item_with_folder(self):
        session = self.Session()
        result = save_bulk_collection_grid(
            session,
            user_id=self.owner_id,
            set_code="RA03",
            changes=[
                {
                    "row_id": "p-new",
                    "printing_id": session.execute(
                        select(Printing.id).where(Printing.set_code == "RA03-EN016")
                    ).scalar_one(),
                    "set_code": "RA03-EN016",
                    "rarity_code": "(UR)",
                    "folder_name": "BIN2",
                    "quantity": 2,
                    "trade_quantity": 0,
                    "condition": "NearMint",
                    "edition": "1st Edition",
                    "language": "English",
                    "baseline": {
                        "quantity": 0,
                        "trade_quantity": 0,
                        "folder_name": None,
                        "collection_item_id": None,
                    },
                }
            ],
        )
        item = session.execute(
            select(CollectionItem).where(
                CollectionItem.user_id == self.owner_id,
                CollectionItem.set_code == "RA03-EN016",
            )
        ).scalar_one()
        session.close()
        self.assertEqual(result["items_created"], 1)
        self.assertEqual(result["quantities_added"], 2)
        self.assertEqual(item.quantity, 2)

    def test_save_adds_second_folder_via_duplicate_row(self):
        session = self.Session()
        printing_id = session.execute(
            select(Printing.id).where(
                Printing.set_code == "RA03-EN015",
                Printing.set_rarity_code == "(UR)",
            )
        ).scalar_one()
        result = save_bulk_collection_grid(
            session,
            user_id=self.owner_id,
            set_code="RA03",
            changes=[
                {
                    "row_id": "r-existing",
                    "printing_id": printing_id,
                    "collection_item_id": self.item_id,
                    "set_code": "RA03-EN015",
                    "rarity_code": "(UR)",
                    "folder_name": "BOX2",
                    "quantity": 1,
                    "trade_quantity": 0,
                    "condition": "NearMint",
                    "edition": "1st Edition",
                    "language": "English",
                    "baseline": {
                        "quantity": 1,
                        "trade_quantity": 0,
                        "folder_name": "BOX2",
                        "collection_item_id": self.item_id,
                    },
                },
                {
                    "row_id": "dup-bin2",
                    "printing_id": printing_id,
                    "collection_item_id": self.item_id,
                    "set_code": "RA03-EN015",
                    "rarity_code": "(UR)",
                    "folder_name": "BIN2",
                    "quantity": 1,
                    "trade_quantity": 0,
                    "condition": "NearMint",
                    "edition": "1st Edition",
                    "language": "English",
                    "is_client_duplicate": True,
                    "baseline": {
                        "quantity": 0,
                        "trade_quantity": 0,
                        "folder_name": None,
                        "collection_item_id": self.item_id,
                    },
                },
            ],
        )
        item = session.get(CollectionItem, self.item_id)
        folders = sorted(
            (alloc.folder.name if alloc.folder else None, alloc.quantity)
            for alloc in item.folder_allocations
        )
        session.close()
        self.assertEqual(result["items_updated"], 1)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(folders, [("BIN2", 1), ("BOX2", 1)])

    def test_save_ignores_folder_only_edit_on_zero_row(self):
        session = self.Session()
        printing_id = session.execute(
            select(Printing.id).where(
                Printing.set_code == "RA03-EN016",
                Printing.set_rarity_code == "(UR)",
            )
        ).scalar_one()
        before = session.execute(select(CollectionItem)).scalars().all()
        result = save_bulk_collection_grid(
            session,
            user_id=self.owner_id,
            set_code="RA03",
            changes=[
                {
                    "row_id": "p-default",
                    "printing_id": printing_id,
                    "set_code": "RA03-EN016",
                    "rarity_code": "(UR)",
                    "folder_name": "BOX2",
                    "quantity": 0,
                    "trade_quantity": 0,
                    "condition": "NearMint",
                    "edition": "1st Edition",
                    "language": "English",
                    "baseline": {
                        "quantity": 0,
                        "trade_quantity": 0,
                        "folder_name": None,
                        "collection_item_id": None,
                    },
                }
            ],
        )
        after = session.execute(select(CollectionItem)).scalars().all()
        session.close()
        self.assertEqual(result["items_created"], 0)
        self.assertEqual(len(before), len(after))

    def test_save_trade_only_without_quantity(self):
        session = self.Session()
        printing_id = session.execute(
            select(Printing.id).where(Printing.set_code == "RA03-EN016")
        ).scalar_one()
        result = save_bulk_collection_grid(
            session,
            user_id=self.owner_id,
            set_code="RA03",
            changes=[
                {
                    "row_id": "p-trade-only",
                    "printing_id": printing_id,
                    "set_code": "RA03-EN016",
                    "rarity_code": "(UR)",
                    "folder_name": None,
                    "quantity": 0,
                    "trade_quantity": 2,
                    "condition": "NearMint",
                    "edition": "1st Edition",
                    "language": "English",
                    "baseline": {
                        "quantity": 0,
                        "trade_quantity": 0,
                        "folder_name": None,
                        "collection_item_id": None,
                    },
                }
            ],
        )
        item = session.execute(
            select(CollectionItem).where(
                CollectionItem.user_id == self.owner_id,
                CollectionItem.set_code == "RA03-EN016",
            )
        ).scalar_one()
        session.close()
        self.assertEqual(result["items_created"], 1)
        self.assertEqual(result["trade_quantities_added"], 2)
        self.assertEqual(item.quantity, 0)
        self.assertEqual(item.trade_quantity, 2)

    def test_api_save_rejects_foreign_item_id(self):
        session = self.Session()
        printing_id = session.execute(
            select(Printing.id).where(
                Printing.set_code == "RA03-EN015",
                Printing.set_rarity_code == "(UR)",
            )
        ).scalar_one()
        session.close()
        res = self.client.post(
            "/api/collection/bulk-grid/save",
            headers=self.other_headers,
            json={
                "set_code": "RA03",
                "changes": [
                    {
                        "row_id": "bad",
                        "printing_id": printing_id,
                        "collection_item_id": self.item_id,
                        "set_code": "RA03-EN015",
                        "rarity_code": "(UR)",
                        "folder_name": "BOX2",
                        "quantity": 1,
                        "trade_quantity": 0,
                        "condition": "NearMint",
                        "edition": "1st Edition",
                        "language": "English",
                        "baseline": {
                            "quantity": 0,
                            "trade_quantity": 0,
                            "folder_name": None,
                            "collection_item_id": None,
                        },
                    }
                ],
            },
        )
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
