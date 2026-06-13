"""Tests for Cardmarket discovery seeding, probing, and HTTP backends."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket import http_client
from ygo_app.cardmarket.expansion_seed import apply_seed_to_cache, load_seed_codes
from ygo_app.cardmarket.expansions import resolve_expansion_ids
from ygo_app.cardmarket.browser_client import BrowserSession, format_fetch_error
from ygo_app.cardmarket.http_client import (
    RateLimiter,
    _looks_like_429,
    create_scraper,
    fetch_url,
    resolve_scrape_settings,
)
from ygo_app.models import Base, CardmarketExpansion


def _memory_session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    return sessionmaker(autocommit=False, autoflush=False, bind=eng)()


class TestExpansionSeed(unittest.TestCase):
    def test_load_seed_codes_from_bundled_file(self):
        codes = load_seed_codes()
        self.assertGreater(len(codes), 900)
        self.assertEqual(codes[1651], "YS15")

    def test_apply_seed_to_cache_updates_null_codes(self):
        session = _memory_session()
        session.add(
            CardmarketExpansion(
                expansion_id=1651,
                expansion_code=None,
                expansion_name="2-Player Starter Deck Yuya & Declan",
                fetched_at=datetime.utcnow(),
            )
        )
        session.add(
            CardmarketExpansion(
                expansion_id=9999,
                expansion_code=None,
                expansion_name="Unknown",
                fetched_at=datetime.utcnow(),
            )
        )
        session.commit()

        updated = apply_seed_to_cache(session, {1651: "YS15"})
        self.assertEqual(updated, 1)
        row = session.get(CardmarketExpansion, 1651)
        assert row is not None
        self.assertEqual(row.expansion_code, "YS15")

    def test_load_seed_from_custom_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.json"
            path.write_text(
                '[{"expansion_id": 1, "expansion_code": "LOB"}]',
                encoding="utf-8",
            )
            self.assertEqual(load_seed_codes(path), {1: "LOB"})


class TestResolveExpansionIds(unittest.TestCase):
    def test_stops_probing_when_missing_codes_resolved(self):
        session = _memory_session()
        now = datetime.utcnow()
        session.add(
            CardmarketExpansion(
                expansion_id=100,
                expansion_code="LOB",
                expansion_name="Legend of Blue Eyes",
                fetched_at=now,
            )
        )
        session.add(
            CardmarketExpansion(
                expansion_id=200,
                expansion_code=None,
                expansion_name="Unused Set",
                fetched_at=now,
            )
        )
        session.commit()

        probe_calls: list[int] = []

        def fake_probe(scraper, expansion_id, expansion_name, *, rate_limiter, backend="cloudscraper"):
            probe_calls.append(expansion_id)
            return None

        with (
            mock.patch(
                "ygo_app.cardmarket.expansions.refresh_expansion_cache",
                return_value=2,
            ),
            mock.patch(
                "ygo_app.cardmarket.expansions.apply_seed_to_cache",
                return_value=0,
            ),
            mock.patch(
                "ygo_app.cardmarket.product_list.probe_expansion_code",
                side_effect=fake_probe,
            ),
        ):
            result = resolve_expansion_ids(session, {"LOB"}, force_refresh=False)

        self.assertEqual(result, {"LOB": 100})
        self.assertEqual(probe_calls, [])

    def test_probes_only_until_missing_cleared(self):
        session = _memory_session()
        now = datetime.utcnow()
        session.add(
            CardmarketExpansion(
                expansion_id=100,
                expansion_code=None,
                expansion_name="Legend of Blue Eyes",
                fetched_at=now,
            )
        )
        session.add(
            CardmarketExpansion(
                expansion_id=200,
                expansion_code=None,
                expansion_name="Later Set",
                fetched_at=now,
            )
        )
        session.commit()

        probe_calls: list[int] = []

        def fake_probe(scraper, expansion_id, expansion_name, *, rate_limiter, backend="cloudscraper"):
            probe_calls.append(expansion_id)
            if expansion_id == 100:
                return "LOB"
            return "SKIP"

        with (
            mock.patch(
                "ygo_app.cardmarket.expansions.refresh_expansion_cache",
                return_value=2,
            ),
            mock.patch(
                "ygo_app.cardmarket.expansions.apply_seed_to_cache",
                return_value=0,
            ),
            mock.patch(
                "ygo_app.cardmarket.product_list.probe_expansion_code",
                side_effect=fake_probe,
            ),
        ):
            result = resolve_expansion_ids(session, {"LOB"}, force_refresh=False)

        self.assertEqual(result, {"LOB": 100})
        self.assertEqual(probe_calls, [100])


class TestFormatFetchError(unittest.TestCase):
    def test_playwright_error_includes_message(self):
        class Error(Exception):
            pass

        exc = Error("It looks like you are using Playwright Sync API inside the asyncio loop.")
        self.assertIn("PlaywrightError:", format_fetch_error(exc))
        self.assertIn("asyncio loop", format_fetch_error(exc))

    def test_missing_executable_includes_install_hint(self):
        class Error(Exception):
            pass

        exc = Error(
            "BrowserType.launch: Executable doesn't exist at "
            "C:\\ms-playwright\\chromium_headless_shell-1223\\chrome-headless-shell.exe"
        )
        formatted = format_fetch_error(exc)
        self.assertIn("python -m playwright install chromium", formatted)

    def test_generic_exception_includes_type_and_message(self):
        exc = ValueError("bad status")
        self.assertEqual(format_fetch_error(exc), "ValueError: bad status")


class TestLooksLike429(unittest.TestCase):
    def test_status_429(self):
        self.assertTrue(_looks_like_429(status=429, error=None))

    def test_error_message_429(self):
        self.assertTrue(_looks_like_429(status=None, error="HTTP 429"))


class TestFetchUrl429(unittest.TestCase):
    def setUp(self):
        http_client._consecutive_429_count = 0

    def test_honors_retry_after_header(self):
        scraper = create_scraper()
        responses = [
            mock.Mock(status_code=429, headers={"Retry-After": "2"}, text=""),
            mock.Mock(status_code=200, headers={}, text="<html>ok</html>"),
        ]

        with (
            mock.patch.object(scraper, "get", side_effect=responses),
            mock.patch("ygo_app.cardmarket.http_client.time.sleep") as sleep_mock,
        ):
            html, error = fetch_url(
                scraper,
                "https://www.cardmarket.com/en/YuGiOh",
                rate_limiter=RateLimiter(1000),
                retries=3,
            )

        self.assertEqual(html, "<html>ok</html>")
        self.assertIsNone(error)
        sleep_mock.assert_called()
        self.assertEqual(sleep_mock.call_args_list[0].args[0], 2.0)

    def test_playwright_backend_delegates_to_browser_session(self):
        browser_html = "<html>browser</html>"

        with mock.patch(
            "ygo_app.cardmarket.browser_client.BrowserSession.get"
        ) as get_mock:
            session = mock.Mock()
            session.fetch.return_value = (browser_html, 200, {}, None)
            get_mock.return_value = session

            html, error = fetch_url(
                None,
                "https://www.cardmarket.com/en/YuGiOh",
                backend="playwright",
                rate_limiter=RateLimiter(1000),
            )

        self.assertEqual(html, browser_html)
        self.assertIsNone(error)
        session.fetch.assert_called_once()

    def test_playwright_429_logs_status_and_retries(self):
        with (
            mock.patch(
                "ygo_app.cardmarket.http_client._fetch_playwright",
                side_effect=[
                    (None, 429, {"Retry-After": "3"}, "HTTP 429"),
                    ("<html>ok</html>", 200, {}, None),
                ],
            ),
            mock.patch("ygo_app.cardmarket.http_client.time.sleep") as sleep_mock,
            mock.patch("ygo_app.cardmarket.http_client.log_line") as log_mock,
        ):
            html, error = fetch_url(
                None,
                "https://www.cardmarket.com/en/YuGiOh",
                backend="playwright",
                rate_limiter=RateLimiter(1000),
                retries=3,
            )

        self.assertEqual(html, "<html>ok</html>")
        self.assertIsNone(error)
        sleep_mock.assert_called()
        logged = " ".join(str(c.args[0]) for c in log_mock.call_args_list)
        self.assertIn("HTTP 429", logged)


class TestBrowserSessionThreading(unittest.TestCase):
    def test_fetch_returns_result_from_worker_queue(self):
        from ygo_app.cardmarket.browser_client import _FetchResult, _STOP

        session = BrowserSession()
        session._ready = True

        def fake_put(item: object) -> None:
            if item is _STOP:
                return
            _url, result_queue = item
            result_queue.put(_FetchResult("<html>ok</html>", 200, {}, None))

        with (
            mock.patch.object(session, "_ensure_worker"),
            mock.patch.object(session._command_queue, "put", side_effect=fake_put),
        ):
            html, status, headers, err = session.fetch("https://example.com/test")

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(status, 200)
        self.assertEqual(headers, {})
        self.assertIsNone(err)


class TestResolveScrapeSettings(unittest.TestCase):
    def test_browser_mode_clamps_workers(self):
        workers, discovery_rps, price_rps, backend = resolve_scrape_settings(
            use_browser=True,
            workers=8,
        )
        self.assertEqual(workers, 1)
        self.assertEqual(backend, "playwright")
        self.assertLess(discovery_rps, 2.0)
        self.assertLessEqual(price_rps, 1.0)

    def test_cloudscraper_mode_keeps_workers(self):
        workers, _discovery_rps, _price_rps, backend = resolve_scrape_settings(
            use_browser=False,
            workers=4,
        )
        self.assertEqual(workers, 4)
        self.assertEqual(backend, "cloudscraper")


if __name__ == "__main__":
    unittest.main()
