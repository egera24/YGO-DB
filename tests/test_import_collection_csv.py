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
from ygo_app.models import (
    Base,
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    User,
)


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
        user = User(
            email="csv@test.example",
            hashed_password="x",
            trade_share_slug="csv-test-trade",
        )
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

    def _write_csv(self, path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
        if fieldnames is None:
            fieldnames = ["Card Number", "Rarity", "Card Name", "Quantity"]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _seed_collection_item(
        self,
        *,
        set_code: str = "LOB-001",
        rarity_code: str = "(UR)",
        quantity: int = 1,
        trade_quantity: int = 0,
        condition: str | None = "NM",
        edition: str = "Unlimited",
        language: str | None = "English",
        price_bought: float | None = 1.0,
        date_bought: str | None = "2020-01-01",
        notes: str | None = "existing note",
        sell_price: float | None = 5.0,
        folder_name: str | None = None,
        folder_qty: int | None = None,
        card_name: str = "Blue-Eyes White Dragon",
    ) -> CollectionItem:
        session = self.Session()
        printing = session.execute(
            select(Printing)
            .where(Printing.set_code == set_code)
            .where(Printing.set_rarity_code == rarity_code)
        ).scalar_one()
        folder = None
        if folder_name is not None:
            folder = CollectionFolder(
                user_id=self.user_id,
                name=folder_name,
                name_key=folder_name.casefold(),
            )
            session.add(folder)
            session.flush()
        item = CollectionItem(
            user_id=self.user_id,
            set_code=set_code,
            rarity_code=rarity_code,
            card_name=card_name,
            quantity=quantity,
            trade_quantity=trade_quantity,
            condition=condition,
            edition=edition,
            language=language,
            price_bought=price_bought,
            date_bought=date_bought,
            notes=notes,
            sell_price=sell_price,
            printing_id=printing.id,
        )
        session.add(item)
        session.flush()
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=folder.id if folder else None,
                quantity=folder_qty if folder_qty is not None else quantity,
            )
        )
        session.commit()
        session.close()
        return item

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

        calls: list[dict] = []

        def on_progress(update: dict) -> None:
            calls.append(update)

        result = import_collection_csv(
            csv_path,
            user_id=self.user_id,
            replace=True,
            progress_callback=on_progress,
        )

        self.assertEqual(result.imported, 1)
        self.assertEqual(len(result.rejected), 2)
        self.assertTrue(calls)
        phases = [call["phase"] for call in calls]
        self.assertIn("replacing", phases)
        self.assertIn("parsing", phases)
        self.assertIn("preloading", phases)
        self.assertIn("importing", phases)
        self.assertIn("finalizing", phases)
        preload_messages = [
            call.get("message")
            for call in calls
            if call.get("phase") == "preloading"
        ]
        self.assertIn("Loading catalog matches…", preload_messages)
        self.assertIn("Loading catalog index…", preload_messages)
        self.assertIn("Scanning catalog for alternate-art codes…", preload_messages)
        parsing = [call for call in calls if call["phase"] == "parsing"]
        self.assertEqual(parsing[0]["message"], "Reading CSV…")
        self.assertEqual(parsing[1]["message"], "Read 3 rows…")
        self.assertEqual(parsing[1]["current"], 1)
        self.assertEqual(parsing[1]["total"], 1)
        catalog_loads = [
            call
            for call in calls
            if call.get("phase") == "preloading"
            and call.get("message") == "Loading catalog matches…"
        ]
        self.assertEqual(len(catalog_loads), 1)
        self.assertEqual(catalog_loads[0]["current"], 1)
        self.assertEqual(catalog_loads[0]["total"], 1)
        scan_calls = [
            call
            for call in calls
            if call.get("phase") == "preloading"
            and call.get("message") == "Scanning catalog for alternate-art codes…"
            and call.get("total")
        ]
        self.assertTrue(scan_calls)
        self.assertEqual(scan_calls[-1]["current"], 2)
        self.assertEqual(scan_calls[-1]["total"], 2)
        self.assertEqual(calls[-1]["phase"], "finalizing")
        importing = [call for call in calls if call["phase"] == "importing"]
        self.assertEqual(importing[0], {"phase": "importing", "current": 0, "total": 3, "message": "Importing 3 rows…"})
        self.assertEqual(importing[0]["total"], 3)
        self.assertGreaterEqual(max(call["current"] for call in importing), 1)

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

    def test_preload_scan_emits_throttled_progress(self):
        csv_path = Path(self._tmp.name).with_suffix(".scan.csv")
        rows = [
            {
                "Card Number": f"FAKE-{index:04d}",
                "Rarity": "(UR)",
                "Card Name": f"Card {index}",
                "Quantity": "1",
            }
            for index in range(120)
        ]
        self._write_csv(csv_path, rows)

        calls: list[dict] = []

        def on_progress(update: dict) -> None:
            calls.append(update)

        result = import_collection_csv(
            csv_path,
            user_id=self.user_id,
            replace=True,
            progress_callback=on_progress,
        )

        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 120)
        scan_calls = [
            call
            for call in calls
            if call.get("phase") == "preloading"
            and call.get("message") == "Scanning catalog for alternate-art codes…"
            and call.get("total") == 120
        ]
        self.assertGreater(len(scan_calls), 1)
        self.assertEqual(scan_calls[-1]["current"], 120)

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

    def test_imports_semicolon_delimited_dragonshield_csv(self):
        csv_path = Path(self._tmp.name).with_suffix(".semi.csv")
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            f.write(
                "Folder;Quantity;Trade Quantity;Total Quantity;"
                "Card Number;Rarity;Condition;Printing;Language\n"
            )
            f.write(
                "BOX1;2;0;2;LOB-001;Ultra Rare;Near Mint;"
                "Limited Edition;English\n"
            )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(len(result.rejected), 0)

        session = self.Session()
        item = (
            session.query(CollectionItem)
            .filter(
                CollectionItem.user_id == self.user_id,
                CollectionItem.set_code == "LOB-001",
            )
            .one()
        )
        folder = (
            session.query(CollectionFolder)
            .filter(CollectionFolder.user_id == self.user_id)
            .one()
        )
        session.close()
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.card_name, "Blue-Eyes White Dragon")
        self.assertEqual(folder.name, "BOX1")

    def test_ignores_csv_card_name_when_catalog_match_exists(self):
        csv_path = Path(self._tmp.name).with_suffix(".wrong-name.csv")
        self._write_csv(
            csv_path,
            [
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "Wrong Name",
                    "Quantity": "1",
                }
            ],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.card_name, "Blue-Eyes White Dragon")

    def test_append_merge_refreshes_card_name_from_catalog(self):
        self._seed_collection_item(card_name="Wrong Name", condition=None)
        csv_path = Path(self._tmp.name).with_suffix(".append-name.csv")
        self._write_csv(
            csv_path,
            [
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "Still Wrong",
                    "Quantity": "1",
                }
            ],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=False)
        self.assertEqual(result.imported, 0)
        self.assertEqual(result.merged, 1)

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.card_name, "Blue-Eyes White Dragon")

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
            "ScR",
            result.rejected[0][IMPORT_ERROR_COLUMN],
        )
        self.assertIn(
            "not found for set code 'LOB-001'",
            result.rejected[0][IMPORT_ERROR_COLUMN],
        )

    def test_rejects_overlong_notes(self):
        csv_path = Path(self._tmp.name).with_suffix(".notes.csv")
        self._write_csv(
            csv_path,
            [
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "Blue-Eyes White Dragon",
                    "Quantity": "1",
                    "Notes": "x" * 501,
                }
            ],
            fieldnames=["Card Number", "Rarity", "Card Name", "Quantity", "Notes"],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertIn("500 characters", result.rejected[0][IMPORT_ERROR_COLUMN])

    def test_import_resolves_short_print_alias(self):
        session = self.Session()
        session.add(
            Printing(
                card_id=89631139,
                set_code="CROS-EN063",
                set_rarity_code="(Short Print)",
                set_rarity="Short Print",
            )
        )
        session.commit()
        session.close()

        csv_path = Path(self._tmp.name).with_suffix(".sp.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "CROS-EN063", "Rarity": "SP", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.rarity_code, "(SP)")

    def test_import_resolves_cross_portal_quarter_century_alias(self):
        session = self.Session()
        session.add(
            Printing(
                card_id=89631139,
                set_code="RA01-EN001",
                set_rarity_code="(QCSR)",
                set_rarity="Quarter Century Secret Rare",
            )
        )
        session.commit()
        session.close()

        csv_path = Path(self._tmp.name).with_suffix(".qcsr.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "RA01-EN001", "Rarity": "QCScR", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.rarity_code, "(QCSR)")

    def _add_printing(
        self,
        *,
        set_code: str,
        rarity_code: str,
        set_rarity: str | None = None,
    ) -> None:
        session = self.Session()
        session.add(
            Printing(
                card_id=89631139,
                set_code=set_code,
                set_rarity_code=rarity_code,
                set_rarity=set_rarity or rarity_code.strip("()"),
            )
        )
        session.commit()
        session.close()

    def test_import_resolves_alt_art_letter_suffix(self):
        self._add_printing(set_code="LCKC-EN001", rarity_code="(UR)", set_rarity="Ultra Rare")
        csv_path = Path(self._tmp.name).with_suffix(".alt-letter.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LCKC-EN001b", "Rarity": "UR", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.set_code, "LCKC-EN001")
        self.assertIsNotNone(item.printing_id)

    def test_import_resolves_alt_art_version_suffix(self):
        self._add_printing(set_code="RA05-EN110", rarity_code="(UR)", set_rarity="Ultra Rare")
        csv_path = Path(self._tmp.name).with_suffix(".alt-version.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "RA05-EN110_v1", "Rarity": "UR", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.set_code, "RA05-EN110")

    def test_import_resolves_alt_art_passcode_suffix(self):
        self._add_printing(
            set_code="RA04-EN108",
            rarity_code="(PlScR)",
            set_rarity="Platinum Secret Rare",
        )
        csv_path = Path(self._tmp.name).with_suffix(".alt-passcode.csv")
        self._write_csv(
            csv_path,
            [
                {
                    "Card Number": "RA04-EN108-8",
                    "Rarity": "PlScR",
                    "Card Name": "X",
                    "Quantity": "1",
                }
            ],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1, result.rejected)
        self.assertEqual(result.rejected, [])

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.set_code, "RA04-EN108")

    def test_rejects_wrong_rarity_for_alt_art_parent(self):
        self._add_printing(set_code="LCKC-EN001", rarity_code="(UR)", set_rarity="Ultra Rare")
        csv_path = Path(self._tmp.name).with_suffix(".alt-rarity.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LCKC-EN001b", "Rarity": "ScR", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertIn("ScR", result.rejected[0][IMPORT_ERROR_COLUMN])
        self.assertIn(
            "not found for set code 'LCKC-EN001b'",
            result.rejected[0][IMPORT_ERROR_COLUMN],
        )

    def test_rejects_substring_false_positive_without_valid_suffix(self):
        self._add_printing(set_code="OP21-EN02", rarity_code="(C)", set_rarity="Common")
        csv_path = Path(self._tmp.name).with_suffix(".alt-false-positive.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "OP21-EN027", "Rarity": "C", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertIn(
            "Set code 'OP21-EN027' not found in catalog",
            result.rejected[0][IMPORT_ERROR_COLUMN],
        )

    def test_rejects_unknown_rarity_code(self):
        csv_path = Path(self._tmp.name).with_suffix(".unknown.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LOB-001", "Rarity": "ZZZ", "Card Name": "X", "Quantity": "1"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertIn(
            "Unknown rarity 'ZZZ'",
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

    def test_import_ignores_market_price_columns(self):
        csv_path = Path(self._tmp.name).with_suffix(".prices.csv")
        fieldnames = [
            "Card Number",
            "Rarity",
            "Card Name",
            "Quantity",
            "Price Bought",
            "AVG",
            "LOW",
            "TREND",
            "Sell Price",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "A",
                    "Quantity": "1",
                    "Price Bought": "1.25",
                    "AVG": "9.99",
                    "LOW": "8.88",
                    "TREND": "7.77",
                    "Sell Price": "6.66",
                }
            )

        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1)

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertAlmostEqual(item.price_bought, 1.25)
        self.assertIsNone(item.sell_price)

    def test_import_creates_folder_once(self):
        csv_path = Path(self._tmp.name).with_suffix(".folders.csv")
        fieldnames = ["Card Number", "Rarity", "Card Name", "Quantity", "Folder Name"]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "A",
                    "Quantity": "1",
                    "Folder Name": "Binder A",
                }
            )
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(SR)",
                    "Card Name": "B",
                    "Quantity": "2",
                    "Folder Name": "binder a",
                }
            )

        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 2)

        session = self.Session()
        folders = session.execute(
            select(CollectionFolder).where(CollectionFolder.user_id == self.user_id)
        ).scalars().all()
        allocations = session.execute(
            select(CollectionItemFolder).join(
                CollectionItem, CollectionItem.id == CollectionItemFolder.collection_item_id
            ).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        session.close()

        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0].name, "Binder A")
        self.assertEqual(len(allocations), 2)

    def test_overwrite_wipes_existing(self):
        self._seed_collection_item(quantity=3)
        csv_path = Path(self._tmp.name).with_suffix(".overwrite.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LOB-001", "Rarity": "(SR)", "Card Name": "B", "Quantity": "2"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.merged, 0)

        session = self.Session()
        items = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        session.close()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].set_code, "LOB-001")
        self.assertEqual(items[0].rarity_code, "(SR)")
        self.assertEqual(items[0].quantity, 2)

    def test_append_merges_quantity(self):
        self._seed_collection_item(
            quantity=2,
            trade_quantity=1,
            sell_price=5.0,
            condition="LP",
            edition="1st Edition",
        )
        csv_path = Path(self._tmp.name).with_suffix(".append-merge.csv")
        self._write_csv(
            csv_path,
            [
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "Blue-Eyes White Dragon",
                    "Quantity": "3",
                    "Trade Quantity": "2",
                    "Condition": "LP",
                    "Printing": "1st Edition",
                    "Language": "German",
                    "Price Bought": "2.5",
                    "Date Bought": "2024-06-01",
                    "Notes": "updated note",
                }
            ],
            fieldnames=[
                "Card Number",
                "Rarity",
                "Card Name",
                "Quantity",
                "Trade Quantity",
                "Condition",
                "Printing",
                "Language",
                "Price Bought",
                "Date Bought",
                "Notes",
            ],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=False)
        self.assertEqual(result.imported, 0)
        self.assertEqual(result.merged, 1)

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.quantity, 5)
        self.assertEqual(item.trade_quantity, 3)
        self.assertEqual(item.condition, "LightPlayed")
        self.assertEqual(item.edition, "1st Edition")
        self.assertEqual(item.language, "German")
        self.assertAlmostEqual(item.price_bought, 2.5)
        self.assertEqual(item.date_bought, "2024-06-01")
        self.assertEqual(item.notes, "updated note")
        self.assertAlmostEqual(item.sell_price, 5.0)

    def test_append_preserves_fields_when_csv_cells_empty(self):
        self._seed_collection_item(
            quantity=2,
            condition=None,
            edition="Unlimited",
            language="English",
            price_bought=1.0,
            date_bought="2020-01-01",
            notes="keep me",
        )
        csv_path = Path(self._tmp.name).with_suffix(".append-preserve.csv")
        self._write_csv(
            csv_path,
            [
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "Blue-Eyes White Dragon",
                    "Quantity": "1",
                    "Trade Quantity": "0",
                    "Condition": "",
                    "Printing": "",
                    "Language": "",
                    "Price Bought": "",
                    "Date Bought": "",
                    "Notes": "",
                }
            ],
            fieldnames=[
                "Card Number",
                "Rarity",
                "Card Name",
                "Quantity",
                "Trade Quantity",
                "Condition",
                "Printing",
                "Language",
                "Price Bought",
                "Date Bought",
                "Notes",
            ],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=False)
        self.assertEqual(result.merged, 1)

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        session.close()
        self.assertEqual(item.quantity, 3)
        self.assertIsNone(item.condition)
        self.assertEqual(item.edition, "Unlimited")
        self.assertEqual(item.language, "English")
        self.assertAlmostEqual(item.price_bought, 1.0)
        self.assertEqual(item.date_bought, "2020-01-01")
        self.assertEqual(item.notes, "keep me")

    def test_append_adds_unmatched(self):
        self._seed_collection_item(quantity=1)
        csv_path = Path(self._tmp.name).with_suffix(".append-new.csv")
        self._write_csv(
            csv_path,
            [{"Card Number": "LOB-001", "Rarity": "(SR)", "Card Name": "B", "Quantity": "2"}],
        )
        result = import_collection_csv(csv_path, user_id=self.user_id, replace=False)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.merged, 0)

        session = self.Session()
        items = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        session.close()
        self.assertEqual(len(items), 2)

    def test_append_merges_folder_allocation(self):
        self._seed_collection_item(
            quantity=2,
            folder_name="Binder A",
            folder_qty=2,
            condition=None,
            edition="Unlimited",
        )
        csv_path = Path(self._tmp.name).with_suffix(".append-folder.csv")
        fieldnames = ["Card Number", "Rarity", "Card Name", "Quantity", "Folder Name"]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "A",
                    "Quantity": "3",
                    "Folder Name": "binder a",
                }
            )
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Card Name": "A",
                    "Quantity": "1",
                    "Folder Name": "Binder B",
                }
            )

        result = import_collection_csv(csv_path, user_id=self.user_id, replace=False)
        self.assertEqual(result.merged, 2)

        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        folders = session.execute(
            select(CollectionFolder).where(CollectionFolder.user_id == self.user_id)
        ).scalars().all()
        allocations = session.execute(
            select(CollectionItemFolder).where(
                CollectionItemFolder.collection_item_id == item.id
            )
        ).scalars().all()
        session.close()

        self.assertEqual(item.quantity, 6)
        self.assertEqual(len(folders), 2)
        self.assertEqual(len(allocations), 2)
        by_folder = {alloc.folder_id: alloc.quantity for alloc in allocations}
        binder_a = next(folder for folder in folders if folder.name == "Binder A")
        binder_b = next(folder for folder in folders if folder.name == "Binder B")
        self.assertEqual(by_folder[binder_a.id], 5)
        self.assertEqual(by_folder[binder_b.id], 1)

    def test_import_splits_different_editions(self):
        csv_path = Path(self._tmp.name).with_suffix(".split-edition.csv")
        fieldnames = [
            "Card Number",
            "Rarity",
            "Quantity",
            "Condition",
            "Printing",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "1",
                    "Condition": "NearMint",
                    "Printing": "1st Edition",
                }
            )
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "1",
                    "Condition": "NearMint",
                    "Printing": "Unlimited",
                }
            )

        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 2)
        self.assertEqual(result.merged, 0)

        session = self.Session()
        items = session.execute(
            select(CollectionItem)
            .where(CollectionItem.user_id == self.user_id)
            .order_by(CollectionItem.edition)
        ).scalars().all()
        session.close()
        self.assertEqual(len(items), 2)
        editions = {item.edition for item in items}
        self.assertEqual(editions, {"1st Edition", "Unlimited"})

    def test_import_splits_different_conditions(self):
        csv_path = Path(self._tmp.name).with_suffix(".split-condition.csv")
        fieldnames = [
            "Card Number",
            "Rarity",
            "Quantity",
            "Condition",
            "Printing",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "1",
                    "Condition": "NearMint",
                    "Printing": "Unlimited",
                }
            )
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "1",
                    "Condition": "LightPlayed",
                    "Printing": "Unlimited",
                }
            )

        result = import_collection_csv(csv_path, user_id=self.user_id, replace=True)
        self.assertEqual(result.imported, 2)
        self.assertEqual(result.merged, 0)

        session = self.Session()
        items = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        session.close()
        self.assertEqual(len(items), 2)
        conditions = {item.condition for item in items}
        self.assertEqual(conditions, {"NearMint", "LightPlayed"})

    def test_import_merges_same_edition_and_condition(self):
        csv_path = Path(self._tmp.name).with_suffix(".merge-variant.csv")
        fieldnames = [
            "Card Number",
            "Rarity",
            "Quantity",
            "Condition",
            "Printing",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "2",
                    "Condition": "NearMint",
                    "Printing": "1st Edition",
                }
            )
            writer.writerow(
                {
                    "Card Number": "LOB-001",
                    "Rarity": "(UR)",
                    "Quantity": "3",
                    "Condition": "NearMint",
                    "Printing": "1st Edition",
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
        self.assertEqual(item.quantity, 5)
        self.assertEqual(item.condition, "NearMint")
        self.assertEqual(item.edition, "1st Edition")


if __name__ == "__main__":
    unittest.main()
