"""Search preset CRUD, overwrite, and per-user isolation."""

from __future__ import annotations

import json
import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, SearchPreset, User
from ygo_app.schemas import normalize_search_preset_params
from ygo_app.services import (
    SearchPresetConflictError,
    create_search_preset,
    delete_search_preset,
    get_search_preset,
    get_search_preset_by_name,
    list_search_presets,
    update_search_preset,
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


class TestSearchPresets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user_a = User(email="a@test.example", hashed_password="x")
        user_b = User(email="b@test.example", hashed_password="x")
        session.add_all([user_a, user_b])
        session.commit()
        self.user_a_id = user_a.id
        self.user_b_id = user_b.id
        session.close()

        self.sample_params = {
            "q": "dragon",
            "category": "Monster",
            "level_min": "4",
            "owned_only": "true",
        }

    def tearDown(self):
        self.engine.dispose()
        import os

        os.unlink(self._tmp.name)

    def test_normalize_rejects_unknown_keys(self):
        with self.assertRaises(ValueError):
            normalize_search_preset_params({"q": "x", "limit": "500"})

    def test_normalize_strips_empty_values(self):
        cleaned = normalize_search_preset_params({"q": "  dragon  ", "set_code": ""})
        self.assertEqual(cleaned, {"q": "dragon"})

    def test_create_and_list_preset(self):
        session = self.Session()
        preset = create_search_preset(
            session, self.user_a_id, "Dragons", self.sample_params
        )
        self.assertEqual(preset.name, "Dragons")
        stored = json.loads(preset.params)
        self.assertEqual(stored["q"], "dragon")

        presets = list_search_presets(session, self.user_a_id)
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0].id, preset.id)
        session.close()

    def test_presets_isolated_per_user(self):
        session = self.Session()
        create_search_preset(session, self.user_a_id, "Shared name", {"q": "a"})
        create_search_preset(session, self.user_b_id, "Shared name", {"q": "b"})

        a_presets = list_search_presets(session, self.user_a_id)
        b_presets = list_search_presets(session, self.user_b_id)
        self.assertEqual(len(a_presets), 1)
        self.assertEqual(len(b_presets), 1)
        self.assertEqual(json.loads(a_presets[0].params)["q"], "a")
        self.assertEqual(json.loads(b_presets[0].params)["q"], "b")
        session.close()

    def test_duplicate_name_without_overwrite_raises(self):
        session = self.Session()
        create_search_preset(session, self.user_a_id, "My preset", {"q": "one"})
        with self.assertRaises(SearchPresetConflictError):
            create_search_preset(
                session, self.user_a_id, "My preset", {"q": "two"}, overwrite=False
            )
        session.close()

    def test_overwrite_replaces_params(self):
        session = self.Session()
        preset = create_search_preset(
            session, self.user_a_id, "My preset", {"q": "one"}
        )
        old_updated = preset.updated_at

        updated = create_search_preset(
            session,
            self.user_a_id,
            "My preset",
            {"q": "two", "set_code": "LOB-001"},
            overwrite=True,
        )
        self.assertEqual(updated.id, preset.id)
        stored = json.loads(updated.params)
        self.assertEqual(stored["q"], "two")
        self.assertEqual(stored["set_code"], "LOB-001")
        self.assertGreaterEqual(updated.updated_at, old_updated)
        session.close()

    def test_rename_success(self):
        session = self.Session()
        preset = create_search_preset(
            session, self.user_a_id, "Old name", self.sample_params
        )
        renamed = update_search_preset(
            session, preset.id, self.user_a_id, name="New name"
        )
        self.assertIsNotNone(renamed)
        assert renamed is not None
        self.assertEqual(renamed.name, "New name")
        session.close()

    def test_rename_conflict(self):
        session = self.Session()
        first = create_search_preset(session, self.user_a_id, "First", {"q": "1"})
        create_search_preset(session, self.user_a_id, "Second", {"q": "2"})
        with self.assertRaises(SearchPresetConflictError):
            update_search_preset(
                session, first.id, self.user_a_id, name="Second"
            )
        session.close()

    def test_patch_params_only(self):
        session = self.Session()
        preset = create_search_preset(
            session, self.user_a_id, "Editable", {"q": "before"}
        )
        updated = update_search_preset(
            session,
            preset.id,
            self.user_a_id,
            params={"q": "after", "favorites_only": "true"},
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.name, "Editable")
        stored = json.loads(updated.params)
        self.assertEqual(stored["q"], "after")
        self.assertEqual(stored["favorites_only"], "true")
        session.close()

    def test_delete_preset(self):
        session = self.Session()
        preset = create_search_preset(
            session, self.user_a_id, "Delete me", self.sample_params
        )
        self.assertTrue(delete_search_preset(session, preset.id, self.user_a_id))
        self.assertIsNone(get_search_preset(session, preset.id, self.user_a_id))
        session.close()

    def test_wrong_user_cannot_access_or_delete(self):
        session = self.Session()
        preset = create_search_preset(
            session, self.user_a_id, "Private", self.sample_params
        )
        self.assertIsNone(get_search_preset(session, preset.id, self.user_b_id))
        self.assertFalse(delete_search_preset(session, preset.id, self.user_b_id))
        self.assertIsNone(
            get_search_preset_by_name(session, self.user_b_id, "Private")
        )
        remaining = session.execute(select(SearchPreset)).scalars().all()
        self.assertEqual(len(remaining), 1)
        session.close()


if __name__ == "__main__":
    unittest.main()
