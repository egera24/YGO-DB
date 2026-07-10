"""Tests for mirrored card image keys, URLs, manifest, and import rewrite."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ygo_app import image_mirror
from ygo_app.image_mirror import (
    full_image_key,
    image_stem,
    load_images_manifest,
    load_passwordless_manifest,
    mirrored_image_urls,
    passwordless_image_stem,
    rewrite_image_urls,
    save_images_manifest,
    small_image_key,
)

YUGI_FULL = "https://ms.yugipedia.com//6/65/CardTrooper.png"
YUGI_SMALL = "https://ms.yugipedia.com//thumb/6/65/CardTrooper.png/150px-CardTrooper.png"


class TestImageKeys(unittest.TestCase):
    def test_keys_are_passcode_based(self):
        self.assertEqual(full_image_key(85087012), "cards/85087012.webp")
        self.assertEqual(small_image_key(85087012), "cards/85087012-small.webp")

    def test_mirrored_urls_strip_trailing_slash(self):
        urls = mirrored_image_urls(123, "https://img.example.com/")
        self.assertEqual(urls["image_url"], "https://img.example.com/cards/123.webp")
        self.assertEqual(urls["image_url_small"], "https://img.example.com/cards/123-small.webp")


class TestImageStem(unittest.TestCase):
    def test_passcode_wins(self):
        self.assertEqual(image_stem(85087012, "https://x/y"), "85087012")

    def test_source_url_when_no_passcode(self):
        url = "https://yugipedia.com/wiki/Obelisk_the_Tormentor"
        self.assertEqual(image_stem(None, url), passwordless_image_stem(url))

    def test_none_when_no_keys(self):
        self.assertIsNone(image_stem(None, None))

    def test_passwordless_stem_is_deterministic_and_prefixed(self):
        url = "https://yugipedia.com/wiki/Obelisk_the_Tormentor"
        stem = passwordless_image_stem(url)
        self.assertTrue(stem.startswith("pw-"))
        self.assertEqual(stem, passwordless_image_stem(url))
        self.assertNotEqual(stem, passwordless_image_stem(url + "_alt"))


class TestManifestRoundTrip(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            save_images_manifest({3, 1, 2}, path=path)
            self.assertEqual(load_images_manifest(path), {1, 2, 3})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["count"], 3)

    def test_save_and_load_passwordless(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            save_images_manifest({1, 2}, {"pw-aaa", "pw-bbb"}, path)
            self.assertEqual(load_images_manifest(path), {1, 2})
            self.assertEqual(load_passwordless_manifest(path), {"pw-aaa", "pw-bbb"})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["count"], 4)

    def test_passwordless_absent_is_empty(self):
        self.assertEqual(load_passwordless_manifest(Path("does/not/exist.json")), set())

    def test_missing_file_is_empty(self):
        self.assertEqual(load_images_manifest(Path("does/not/exist.json")), set())

    def test_invalid_json_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_images_manifest(path), set())

    def test_plain_list_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text('[1, "2", null]', encoding="utf-8")
            self.assertEqual(load_images_manifest(path), {1, 2})


class TestRewriteImageUrls(unittest.TestCase):
    def test_mirrored_passcode_rewritten(self):
        url, small = rewrite_image_urls(
            42, YUGI_FULL, YUGI_SMALL, base_url="https://img.example.com", manifest={42}
        )
        self.assertEqual(url, "https://img.example.com/cards/42.webp")
        self.assertEqual(small, "https://img.example.com/cards/42-small.webp")

    def test_unmirrored_passcode_kept(self):
        url, small = rewrite_image_urls(
            42, YUGI_FULL, YUGI_SMALL, base_url="https://img.example.com", manifest={7}
        )
        self.assertEqual(url, YUGI_FULL)
        self.assertEqual(small, YUGI_SMALL)

    def test_no_base_url_kept(self):
        url, small = rewrite_image_urls(42, YUGI_FULL, YUGI_SMALL, base_url="", manifest={42})
        self.assertEqual(url, YUGI_FULL)
        self.assertEqual(small, YUGI_SMALL)

    def test_mirrored_overrides_null_scrape_urls(self):
        url, small = rewrite_image_urls(
            42, None, None, base_url="https://img.example.com", manifest={42}
        )
        self.assertEqual(url, "https://img.example.com/cards/42.webp")
        self.assertEqual(small, "https://img.example.com/cards/42-small.webp")

    def test_passwordless_mirrored_by_source_url(self):
        source_url = "https://yugipedia.com/wiki/Obelisk_the_Tormentor"
        stem = passwordless_image_stem(source_url)
        url, small = rewrite_image_urls(
            None,
            YUGI_FULL,
            YUGI_SMALL,
            source_url=source_url,
            base_url="https://img.example.com",
            passwordless_manifest={stem},
        )
        self.assertEqual(url, f"https://img.example.com/cards/{stem}.webp")
        self.assertEqual(small, f"https://img.example.com/cards/{stem}-small.webp")

    def test_passwordless_unmirrored_kept(self):
        url, small = rewrite_image_urls(
            None,
            YUGI_FULL,
            YUGI_SMALL,
            source_url="https://yugipedia.com/wiki/Some_Token",
            base_url="https://img.example.com",
            passwordless_manifest=set(),
        )
        self.assertEqual(url, YUGI_FULL)
        self.assertEqual(small, YUGI_SMALL)

    def test_passcode_takes_precedence_over_source_url(self):
        # A card with both keys mirrors by passcode, ignoring source_url.
        url, small = rewrite_image_urls(
            42,
            YUGI_FULL,
            YUGI_SMALL,
            source_url="https://yugipedia.com/wiki/Card_Trooper",
            base_url="https://img.example.com",
            manifest={42},
            passwordless_manifest=set(),
        )
        self.assertEqual(url, "https://img.example.com/cards/42.webp")
        self.assertEqual(small, "https://img.example.com/cards/42-small.webp")

    def test_no_keys_kept(self):
        url, small = rewrite_image_urls(
            None, YUGI_FULL, YUGI_SMALL, base_url="https://img.example.com"
        )
        self.assertEqual(url, YUGI_FULL)
        self.assertEqual(small, YUGI_SMALL)


class TestAdapterRewrite(unittest.TestCase):
    def _entry(self, pid: str) -> dict:
        return {
            "id": pid,
            "name": "Test Card",
            "type": "Spell",
            "property": "Normal",
            "image_url": YUGI_FULL,
            "image_url_small": YUGI_SMALL,
            "card_sets": [{"set_code": "TST-EN001", "set_name": "T", "set_rarity": "C"}],
        }

    def test_import_row_uses_mirrored_urls(self):
        from ygo_app.yugipedia.card_import import yugipedia_entry_to_import

        with mock.patch.object(image_mirror.config, "IMAGE_BASE_URL", "https://img.example.com"), \
                mock.patch.object(image_mirror, "_cached_manifest", return_value={11111111}):
            row = yugipedia_entry_to_import(self._entry("11111111"))
        assert row is not None
        img = row["card_images"][0]
        self.assertEqual(img["image_url"], "https://img.example.com/cards/11111111.webp")
        self.assertEqual(img["image_url_small"], "https://img.example.com/cards/11111111-small.webp")

    def test_import_row_keeps_yugipedia_when_unmirrored(self):
        from ygo_app.yugipedia.card_import import yugipedia_entry_to_import

        with mock.patch.object(image_mirror.config, "IMAGE_BASE_URL", "https://img.example.com"), \
                mock.patch.object(image_mirror, "_cached_manifest", return_value=set()):
            row = yugipedia_entry_to_import(self._entry("22222222"))
        assert row is not None
        img = row["card_images"][0]
        self.assertEqual(img["image_url"], YUGI_FULL)
        self.assertEqual(img["image_url_small"], YUGI_SMALL)


if __name__ == "__main__":
    unittest.main()
