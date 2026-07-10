"""Tests for Yugipedia HTTP client (parse API transport + fallback)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from ygo_app.yugipedia.http_client import (
    YUGIPEDIA_API_URL,
    create_session,
    fetch_current_revisions,
    fetch_page,
    fetch_pages_batch,
    normalize_wiki_title,
    wiki_title_from_url,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yugipedia"


class TestWikiTitleFromUrl(unittest.TestCase):
    def test_card_page(self):
        self.assertEqual(
            wiki_title_from_url("https://yugipedia.com/wiki/Dark_Magician"),
            "Dark_Magician",
        )

    def test_card_errata_with_colon(self):
        self.assertEqual(
            wiki_title_from_url(
                "https://yugipedia.com/wiki/Card_Errata:Amazoness_Paladin"
            ),
            "Card_Errata:Amazoness_Paladin",
        )

    def test_card_tips_strips_query(self):
        self.assertEqual(
            wiki_title_from_url(
                "https://yugipedia.com/wiki/Card_Tips:Parallel_Teleport?action=edit"
            ),
            "Card_Tips:Parallel_Teleport",
        )

    def test_percent_encoded_title(self):
        self.assertEqual(
            wiki_title_from_url(
                "https://yugipedia.com/wiki/Set_chronology#TCG"
            ),
            "Set_chronology",
        )

    def test_non_yugipedia_url(self):
        self.assertIsNone(wiki_title_from_url("https://example.com/wiki/Foo"))


class TestNormalizeWikiTitle(unittest.TestCase):
    def test_underscore_to_space(self):
        self.assertEqual(
            normalize_wiki_title("Dark_Magician"),
            "Dark Magician",
        )

    def test_preserves_case(self):
        self.assertEqual(
            normalize_wiki_title("Card_Errata:Amazoness_Paladin"),
            "Card Errata:Amazoness Paladin",
        )


class TestFetchPagesBatch(unittest.TestCase):
    def setUp(self):
        self.session = create_session()

    def test_batch_returns_multiple_pages(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Dark Magician",
                        "lastrevid": 10,
                        "touched": "2024-01-01T00:00:00Z",
                        "parse": {"text": {"*": "<html>dm</html>"}},
                    },
                    "2": {
                        "title": "Blue-Eyes White Dragon",
                        "lastrevid": 20,
                        "parse": {"text": {"*": "<html>be</html>"}},
                    },
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(self.session, "get", return_value=mock_response) as mock_get:
            results = fetch_pages_batch(
                self.session, ["Dark_Magician", "Blue-Eyes_White_Dragon"]
            )

        self.assertEqual(mock_get.call_count, 1)
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["action"], "query")
        self.assertEqual(params["maxlag"], 5)
        self.assertIn("Dark_Magician", params["titles"])
        self.assertIsNone(results["Dark Magician"].error)
        self.assertEqual(results["Dark Magician"].html, "<html>dm</html>")
        self.assertEqual(results["Dark Magician"].revid, 10)

    def test_batch_marks_missing_page(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": {
                "pages": {
                    "-1": {
                        "title": "Missing Card",
                        "missing": "",
                    }
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(self.session, "get", return_value=mock_response):
            results = fetch_pages_batch(self.session, ["Missing Card"])

        self.assertIsNone(results["Missing Card"].html)
        self.assertEqual(results["Missing Card"].error, "MissingPage")


class TestFetchCurrentRevisions(unittest.TestCase):
    def test_returns_revid_map(self):
        session = create_session()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Dark Magician",
                        "revisions": [{"revid": 42, "timestamp": "2024-01-01T00:00:00Z"}],
                    }
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(session, "get", return_value=mock_response):
            revs = fetch_current_revisions(session, ["Dark_Magician"])

        self.assertEqual(revs["Dark Magician"]["revid"], 42)


class TestBatchRetry429(unittest.TestCase):
    @patch("ygo_app.yugipedia.http_client.time.sleep")
    def test_retries_on_429_with_retry_after(self, mock_sleep):
        session = create_session()
        fail_response = MagicMock()
        fail_response.status_code = 429
        fail_response.headers = {"Retry-After": "2"}
        fail_response.content = b"rate limited"
        http_error = requests.HTTPError("429 Too Many Requests")
        http_error.response = fail_response
        fail_response.raise_for_status.side_effect = http_error

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Dark Magician",
                        "parse": {"text": {"*": "<html>ok</html>"}},
                    }
                }
            }
        }
        ok_response.raise_for_status = MagicMock()

        with patch.object(session, "get", side_effect=[fail_response, ok_response]):
            results = fetch_pages_batch(session, ["Dark_Magician"], retries=2)

        self.assertEqual(results["Dark Magician"].html, "<html>ok</html>")
        mock_sleep.assert_called()


class TestBatchMaxlag(unittest.TestCase):
    @patch("ygo_app.yugipedia.http_client.time.sleep")
    def test_retries_on_maxlag_json_error(self, mock_sleep):
        session = create_session()
        lag_response = MagicMock()
        lag_response.status_code = 200
        lag_response.json.return_value = {
            "error": {"code": "maxlag", "info": "Waiting", "lag": 7}
        }
        lag_response.raise_for_status = MagicMock()

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Dark Magician",
                        "parse": {"text": {"*": "<html>ok</html>"}},
                    }
                }
            }
        }
        ok_response.raise_for_status = MagicMock()

        with patch.object(session, "get", side_effect=[lag_response, ok_response]):
            results = fetch_pages_batch(session, ["Dark_Magician"], retries=2)

        self.assertEqual(results["Dark Magician"].html, "<html>ok</html>")
        mock_sleep.assert_called()


class TestFetchPageParsePath(unittest.TestCase):
    def setUp(self):
        self.fixture_html = (FIXTURES / "black_feather_counter.html").read_text(
            encoding="utf-8"
        )
        self.session = create_session()
        self.url = "https://yugipedia.com/wiki/Black_Feather_Counter"

    @patch("ygo_app.yugipedia.http_client.create_scraper")
    def test_uses_parse_api_without_wiki_fallback(self, mock_create_scraper):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"query":{"pages":{}}}'
        mock_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Black_Feather_Counter",
                        "parse": {"text": {"*": self.fixture_html}},
                    }
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(self.session, "get", return_value=mock_response) as mock_get:
            html, error = fetch_page(self.session, self.url)

        self.assertIsNone(error)
        self.assertEqual(html, self.fixture_html)
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["action"], "query")
        self.assertIn("Black_Feather_Counter", call_kwargs["params"]["titles"])
        self.assertEqual(mock_get.call_args.args[0], YUGIPEDIA_API_URL)
        mock_create_scraper.assert_not_called()

    @patch("ygo_app.yugipedia.http_client._fetch_via_wiki_url")
    @patch("ygo_app.yugipedia.http_client.create_scraper")
    def test_falls_back_to_wiki_url_when_parse_fails(
        self, mock_create_scraper, mock_wiki_fetch
    ):
        mock_scraper = MagicMock()
        mock_create_scraper.return_value = mock_scraper
        mock_wiki_fetch.return_value = ("<html>fallback</html>", None)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"error":{"info":"bad"}}'
        mock_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Black_Feather_Counter",
                        "missing": "",
                    }
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(self.session, "get", return_value=mock_response):
            html, error = fetch_page(
                self.session, self.url, retries=1, timeout=5
            )

        self.assertIsNone(error)
        self.assertEqual(html, "<html>fallback</html>")
        mock_create_scraper.assert_called_once()
        mock_wiki_fetch.assert_called_once_with(
            mock_scraper, self.url, retries=1, timeout=5
        )

    @patch("ygo_app.yugipedia.http_client._fetch_via_wiki_url")
    @patch("ygo_app.yugipedia.http_client.create_scraper")
    def test_retries_parse_on_503(self, mock_create_scraper, mock_wiki_fetch):
        mock_create_scraper.return_value = MagicMock()
        mock_wiki_fetch.return_value = (None, "fallback failed")

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.content = b"{}"
        ok_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "title": "Black_Feather_Counter",
                        "parse": {"text": {"*": "<html>ok</html>"}},
                    }
                }
            }
        }
        ok_response.raise_for_status = MagicMock()

        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.content = b"Service Unavailable"
        http_error = requests.HTTPError("503 Server Error")
        http_error.response = fail_response
        fail_response.raise_for_status.side_effect = http_error

        with patch.object(
            self.session,
            "get",
            side_effect=[fail_response, ok_response],
        ) as mock_get:
            html, error = fetch_page(
                self.session, self.url, retries=2, timeout=5
            )

        self.assertIsNone(error)
        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(mock_get.call_count, 2)
        mock_wiki_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
