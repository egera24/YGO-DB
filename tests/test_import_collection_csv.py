"""Collection CSV import, progress callback, and catalog matching."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.import_data import IMPORT_ERROR_COLUMN, import_collection_csv
from ygo_app.models import Base, Card, CollectionItem, Printing, User


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


class TestImportCollectionCsv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="csv@test.example", hashed_password="x")
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
        session.add(
            Printing(
                card_id=89631139,
                set_code="LOB-001",
                set_rarity_code="(SR)",
                set_rarity="Super Rare",
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

    def _write_csv(self, path: Path, rows: list[dict]) -> None:
        fieldnames = ["Card Number", "Rarity", "Card Name", "Quantity"]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_import_with_progress_callback(self):
        csv_path = Path(self._tmp.name).with_suffix(".csv")
        self._write_csv(
            csv_path,
            [
                {"Card Number": "LOB-001", "Rarity": "(UR)", "Card Name": "A", "Quantity": "1"},
                {"Card Number": "LOB-002", "Rarity": "(SR)", "Card Name": "B", "Quantity": "2"},
                {"Card Number": "", "Rarity": "", "Card Name": "Skip", "Quantity": "1"},
            ],
        )

        calls: list[tuple[int, int]] = []

        def on_progress(current: int, total: int) -> None:
            calls.append((current, total))

        result = import_collection_csv(
            csv_path,
            user_id=self.user_id,
            replace=True,
            progress_callback=on_progress,
        )

        self.assertEqual(result.imported, 1)
        self.assertEqual(len(result.rejected), 2)
        self.assertTrue(calls)
        self.assertEqual(calls[0], (0, 3))
        self.assertEqual(calls[-1], (3, 3))

        session = self.Session()
        count = (
            session.query(CollectionItem)
            .filter(CollectionItem.user_id == self.user_id)
            .count()
        )
        item = (
            session.query(CollectionItem)
            .filter(
                CollectionItem.user_id == self.user_id,
                CollectionItem.set_code == "LOB-001",
            )
            .one()
        )
        session.close()
        self.assertEqual(count, 1)
        self.assertIsNotNone(item.printing_id)

        errors = {r[IMPORT_ERROR_COLUMN] for r in result.rejected}
        self.assertIn("Missing card number", errors)
        self.assertTrue(
            any("LOB-002" in e and "not found" in e for e in errors),
            errors,
        )

    def test_rejects_unknown_set_code(self):
        csv_path = Path(self._tmp.name).with_suffix(".reject.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "FAKE-999", "Rarity": "(UR)", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertIn(
            "Set code 'FAKE-999' not found in catalog",
            result.rejected[0][IMPORT_ERROR_COLUMN],
        )

    def test_rejects_wrong_rarity_for_set_code(self):
        csv_path = Path(self._tmp.name).with_suffix(".rarity.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LOB-001", "Rarity": "(ScR)", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertIn(
            "Rarity 'ScR' not found for set code 'LOB-001'",
            result.rejected[0][IMPORT_ERROR_COLUMN],
        )

    def test_matched_row_has_printing_id(self):
        csv_path = Path(self._tmp.name).with_suffix(".match.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LOB-001", "Rarity": "(UR)", "Card Name": "A", "Quantity": "2"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        printing = session.get(Printing, item.printing_id)
        session.close()
        self.assertEqual(printing.set_code, "LOB-001")
        self.assertEqual(printing.set_rarity_code, "(UR)")


if __name__ == "__main__":
    unittest.main()
