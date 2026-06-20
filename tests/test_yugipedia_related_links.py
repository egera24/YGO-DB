"""Tests for Yugipedia Errata/Tips link extraction."""

import unittest

from bs4 import BeautifulSoup

from ygo_app.yugipedia.related_links import (
    card_name_from_wiki_url,
    errata_url_for_card_name,
    extract_related_links,
    tips_url_for_card_name,
)


class TestRelatedLinks(unittest.TestCase):
    def test_extract_errata_and_tips_links(self):
        html = """
        <div class="hlist">
          <ul>
            <li><a href="/wiki/Card_Gallery:Abyss_Dweller">Gallery</a></li>
            <li><a href="/wiki/Card_Errata:Abyss_Dweller">Errata</a></li>
            <li><a href="/wiki/Card_Tips:Abyss_Dweller">Tips</a></li>
          </ul>
        </div>
        """
        links = extract_related_links(BeautifulSoup(html, "html.parser"))
        self.assertEqual(
            links["errata_url"],
            "https://yugipedia.com/wiki/Card_Errata:Abyss_Dweller",
        )
        self.assertEqual(
            links["tips_url"],
            "https://yugipedia.com/wiki/Card_Tips:Abyss_Dweller",
        )

    def test_redlink_errata_ignored(self):
        html = """
        <div class="hlist">
          <ul>
            <li><a href="/wiki/Card_Errata:Parallel_Teleport?redlink=1" class="new">Errata</a></li>
            <li><a href="/wiki/Card_Tips:Parallel_Teleport">Tips</a></li>
          </ul>
        </div>
        """
        links = extract_related_links(BeautifulSoup(html, "html.parser"))
        self.assertIsNone(links["errata_url"])
        self.assertEqual(
            links["tips_url"],
            "https://yugipedia.com/wiki/Card_Tips:Parallel_Teleport",
        )

    def test_canonical_urls_encode_special_chars(self):
        url = errata_url_for_card_name("Koa'ki Meiru Prototype")
        self.assertIn("Koa%27ki_Meiru_Prototype", url)
        self.assertIn("Card_Errata:", url)

    def test_card_name_from_wiki_url(self):
        self.assertEqual(
            card_name_from_wiki_url(tips_url_for_card_name("Parallel Teleport")),
            "Parallel Teleport",
        )


if __name__ == "__main__":
    unittest.main()
