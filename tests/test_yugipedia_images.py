"""Tests for Yugipedia image URL extraction and normalization."""

import unittest

from bs4 import BeautifulSoup

from ygo_app.yugipedia.images import (
    normalize_yugipedia_image_url,
    resolve_display_image_url_small,
    yugipedia_image_urls_from_src,
    yugipedia_thumb_url,
)
from ygo_app.yugipedia.parsing import extract_card_image

MONSTER_PAGE_SNIPPET = """
<div class="cardtable">
  <a href="/wiki/File:CardTrooper-25YC-EN-SR-LE.png" class="image">
    <img alt="CardTrooper-25YC-EN-SR-LE.png"
         src="https://ms.yugipedia.com//thumb/6/65/CardTrooper-25YC-EN-SR-LE.png/300px-CardTrooper-25YC-EN-SR-LE.png"
         width="300" height="441" />
  </a>
  <a href="/wiki/File:DARK.svg" class="image">
    <img alt="" src="https://ms.yugipedia.com//d/de/DARK.svg" width="28" height="28" class="noviewer" />
  </a>
  <a href="/wiki/File:CardTrooper-MADU-EN-VG-artwork.png" class="image">
    <img alt="artwork"
         src="https://ms.yugipedia.com//thumb/a/a0/CardTrooper-MADU-EN-VG-artwork.png/50px-CardTrooper-MADU-EN-VG-artwork.png"
         width="50" height="73" />
  </a>
</div>
"""

SPELL_PAGE_SNIPPET = """
<a href="/wiki/File:ParallelTeleport-DUAD-EN-SR-1E.png" class="image">
  <img alt="ParallelTeleport-DUAD-EN-SR-1E.png"
       src="https://ms.yugipedia.com//thumb/a/a6/ParallelTeleport-DUAD-EN-SR-1E.png/300px-ParallelTeleport-DUAD-EN-SR-1E.png"
       width="300" height="441" />
</a>
<a href="/wiki/File:SPELL.svg" class="image">
  <img alt="" src="https://ms.yugipedia.com//0/09/SPELL.svg" width="28" height="28" class="noviewer" />
</a>
"""


class TestYugipediaImageUrls(unittest.TestCase):
    def test_normalize_thumb_to_direct(self):
        thumb = (
            "https://ms.yugipedia.com//thumb/6/65/CardTrooper-25YC-EN-SR-LE.png/"
            "300px-CardTrooper-25YC-EN-SR-LE.png"
        )
        self.assertEqual(
            normalize_yugipedia_image_url(thumb),
            "https://ms.yugipedia.com//6/65/CardTrooper-25YC-EN-SR-LE.png",
        )

    def test_build_thumb_from_direct(self):
        full = "https://ms.yugipedia.com//6/65/CardTrooper-25YC-EN-SR-LE.png"
        self.assertEqual(
            yugipedia_thumb_url(full, width=150),
            "https://ms.yugipedia.com//thumb/6/65/CardTrooper-25YC-EN-SR-LE.png/"
            "150px-CardTrooper-25YC-EN-SR-LE.png",
        )

    def test_urls_from_src(self):
        thumb = (
            "https://ms.yugipedia.com//thumb/a/a6/ParallelTeleport-DUAD-EN-SR-1E.png/"
            "300px-ParallelTeleport-DUAD-EN-SR-1E.png"
        )
        urls = yugipedia_image_urls_from_src(thumb)
        self.assertIn("ms.yugipedia.com//a/a6/ParallelTeleport-DUAD-EN-SR-1E.png", urls["image_url"])
        self.assertIn("300px-ParallelTeleport-DUAD-EN-SR-1E.png", urls["image_url_small"])

    def test_urls_from_src_preserves_scraped_thumb(self):
        thumb = (
            "https://ms.yugipedia.com//thumb/8/80/AbyssActorHyperDirector-DUOV-EN-UR-1E.png/"
            "300px-AbyssActorHyperDirector-DUOV-EN-UR-1E.png"
        )
        urls = yugipedia_image_urls_from_src(thumb)
        self.assertEqual(urls["image_url_small"], thumb)
        self.assertNotIn("150px-", urls["image_url_small"] or "")

    def test_resolve_display_upgrades_legacy_150px(self):
        full = "https://ms.yugipedia.com//8/80/AbyssActorHyperDirector-DUOV-EN-UR-1E.png"
        legacy_small = (
            "https://ms.yugipedia.com//thumb/8/80/AbyssActorHyperDirector-DUOV-EN-UR-1E.png/"
            "150px-AbyssActorHyperDirector-DUOV-EN-UR-1E.png"
        )
        resolved = resolve_display_image_url_small(legacy_small, full)
        self.assertIn("300px-AbyssActorHyperDirector-DUOV-EN-UR-1E.png", resolved or "")


class TestExtractCardImage(unittest.TestCase):
    def test_monster_page_picks_largest_card_art(self):
        soup = BeautifulSoup(MONSTER_PAGE_SNIPPET, "html.parser")
        result = extract_card_image(soup)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("CardTrooper-25YC-EN-SR-LE.png", result["image_url"])
        self.assertNotIn("MADU-EN-VG-artwork", result["image_url"])
        self.assertIn("300px-CardTrooper-25YC-EN-SR-LE.png", result["image_url_small"])

    def test_spell_page(self):
        soup = BeautifulSoup(SPELL_PAGE_SNIPPET, "html.parser")
        result = extract_card_image(soup)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("ParallelTeleport-DUAD-EN-SR-1E.png", result["image_url"])

    def test_icons_only_returns_none(self):
        html = """
        <img alt="" src="https://ms.yugipedia.com//d/de/DARK.svg" width="28" class="noviewer" />
        <img alt="" src="https://ms.yugipedia.com//e/e3/CG_Star.svg" width="18" class="noviewer" />
        """
        soup = BeautifulSoup(html, "html.parser")
        self.assertIsNone(extract_card_image(soup))


if __name__ == "__main__":
    unittest.main()
