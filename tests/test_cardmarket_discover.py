"""Tests for Cardmarket discovery seeding, probing, and HTTP backends."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket import http_client
from ygo_app.cardmarket.expansion_seed import apply_seed_to_cache, load_seed_codes
from ygo_app.cardmarket.expansions import resolve_expansion_ids
from ygo_app.cardmarket.browser_client import BrowserSession, format_fetch_error
from ygo_app.cardmarket.http_client import (
    AdaptiveRateLimiter,
    RateLimiter,
    _looks_like_429,
    create_scraper,
    curl_cffi_available,
    fetch_url,
    is_cloudflare_challenge,
    resolve_scrape_settings,
    user_agent_for_worker,
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

    def test_regenerate_expansion_seed(self):
        from ygo_app.cardmarket.expansion_seed import regenerate_expansion_seed

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "expansions.json"
            path.write_text(
                json.dumps(
                    [
                        {"expansion_id": 1, "expansion_name": "LOB", "expansion_code": "LOB"},
                        {"expansion_id": 2, "expansion_name": "No Code"},
                    ]
                ),
                encoding="utf-8",
            )
            seed_path = Path(tmp) / "seed.json"
            out = regenerate_expansion_seed(path, seed_path=seed_path)
            self.assertEqual(out, seed_path)
            data = json.loads(seed_path.read_text(encoding="utf-8"))
            self.assertEqual(data, [{"expansion_id": 1, "expansion_code": "LOB"}])


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
            mock.patch("ygo_app.cardmarket.http_client.log_line") as log_mock,
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
        logged = " ".join(str(c.args[0]) for c in log_mock.call_args_list)
        self.assertIn("Retry-After='2'", logged)

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
        self.assertIn("Retry-After='3'", logged)

    def test_429_without_retry_after_logs_not_set(self):
        scraper = create_scraper()
        responses = [
            mock.Mock(status_code=429, headers={}, text=""),
            mock.Mock(status_code=200, headers={}, text="<html>ok</html>"),
        ]

        with (
            mock.patch.object(scraper, "get", side_effect=responses),
            mock.patch("ygo_app.cardmarket.http_client.time.sleep"),
            mock.patch("ygo_app.cardmarket.http_client.log_line") as log_mock,
        ):
            html, error = fetch_url(
                scraper,
                "https://www.cardmarket.com/en/YuGiOh",
                rate_limiter=RateLimiter(1000),
                retries=3,
            )

        self.assertEqual(html, "<html>ok</html>")
        logged = " ".join(str(c.args[0]) for c in log_mock.call_args_list)
        self.assertIn("Retry-After=(not set)", logged)
        self.assertIn("no Retry-After header", logged)


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


class TestBrowserProfiles(unittest.TestCase):
    def test_parse_profile_pool(self):
        from ygo_app.cardmarket.browser_profiles import parse_profile_pool, resolve_profile_pool

        self.assertEqual(parse_profile_pool(None), ["default"])
        self.assertEqual(parse_profile_pool("default,alt1,alt2"), ["default", "alt1", "alt2"])
        self.assertEqual(parse_profile_pool("a,a,b"), ["a", "b"])
        self.assertEqual(
            resolve_profile_pool("alt1,alt2", "default,ignored"),
            ["alt1", "alt2"],
        )
        self.assertEqual(resolve_profile_pool(None, "x,y"), ["x", "y"])

    def test_burn_and_rotate(self):
        from ygo_app.cardmarket.browser_profiles import (
            ProfileState,
            burn_and_rotate,
            next_available_profile,
        )

        state = ProfileState(active="default", pool=["default", "alt1", "alt2"])
        rotated = burn_and_rotate(state, reason="429")
        self.assertIsNotNone(rotated)
        assert rotated is not None
        self.assertEqual(rotated.active, "alt1")
        self.assertIn("default", rotated.burned)
        self.assertIsNone(next_available_profile(ProfileState(active="alt2", pool=["a"], burned=["a"])))

    def test_profile_dir_legacy_default(self):
        from ygo_app.cardmarket import browser_profiles as bp

        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp)
            legacy = catalog / "cardmarket_chrome_profile"
            legacy.mkdir()
            with mock.patch.object(bp, "CATALOG_DIR", catalog), mock.patch.object(
                bp, "LEGACY_CDP_PROFILE_DIR", legacy
            ):
                self.assertEqual(bp.profile_dir("default"), legacy)
                self.assertEqual(bp.profile_dir("alt1"), catalog / "cardmarket_profiles" / "alt1")


class TestBrowserCookies(unittest.TestCase):
    def test_storage_has_cf_clearance(self):
        from ygo_app.cardmarket.browser_cookies import storage_has_cf_clearance

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"cookies": [{"name": "cf_clearance", "value": "x"}]}', encoding="utf-8")
            self.assertTrue(storage_has_cf_clearance(path))
            path.write_text('{"cookies": [{"name": "other", "value": "x"}]}', encoding="utf-8")
            self.assertFalse(storage_has_cf_clearance(path))


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
            backend="cloudscraper",
            use_browser=False,
            workers=4,
        )
        self.assertEqual(workers, 4)
        self.assertEqual(backend, "cloudscraper")

    def test_curl_cffi_mode_keeps_workers(self):
        workers, discovery_rps, price_rps, backend = resolve_scrape_settings(
            backend="curl_cffi",
            workers=6,
        )
        self.assertEqual(workers, 6)
        self.assertEqual(backend, "curl_cffi")
        self.assertGreater(discovery_rps, 0)
        self.assertGreater(price_rps, 0)


class TestCloudflareChallengeDetection(unittest.TestCase):
    def test_detects_challenge_markers(self):
        self.assertTrue(is_cloudflare_challenge("<html>Just a moment...</html>"))
        self.assertTrue(is_cloudflare_challenge('<script>_cf_chl_opt</script>'))
        self.assertFalse(is_cloudflare_challenge("<html>normal page</html>"))

    def test_cf_challenge_html_retries(self):
        http_client._consecutive_429_count = 0
        scraper = create_scraper(0)
        responses = [
            mock.Mock(status_code=200, headers={}, text="<html>Just a moment...</html>"),
            mock.Mock(status_code=200, headers={}, text="<html>ok</html>"),
        ]
        with (
            mock.patch.object(scraper, "get", side_effect=responses),
            mock.patch("ygo_app.cardmarket.http_client.time.sleep"),
        ):
            html, error = fetch_url(
                scraper,
                "https://www.cardmarket.com/en/YuGiOh",
                rate_limiter=RateLimiter(1000),
                retries=3,
            )
        self.assertEqual(html, "<html>ok</html>")
        self.assertIsNone(error)


class TestUserAgentRotation(unittest.TestCase):
    def test_workers_get_distinct_user_agents(self):
        agents = {user_agent_for_worker(i) for i in range(3)}
        self.assertGreaterEqual(len(agents), 2)

    def test_create_scraper_uses_worker_agent(self):
        scraper_a = create_scraper(0)
        scraper_b = create_scraper(1)
        self.assertNotEqual(
            scraper_a.headers["User-Agent"],
            scraper_b.headers["User-Agent"],
        )


class TestAdaptiveRateLimiter(unittest.TestCase):
    def test_slows_down_on_block(self):
        limiter = AdaptiveRateLimiter(4.0)
        baseline = limiter.min_interval
        limiter.note_block(reason="403")
        self.assertGreater(limiter.min_interval, baseline)

    def test_recovers_after_success_streak(self):
        limiter = AdaptiveRateLimiter(4.0)
        limiter.note_block(reason="403")
        slowed = limiter.min_interval
        for _ in range(20):
            limiter.note_success()
        self.assertLess(limiter.min_interval, slowed)


@unittest.skipUnless(curl_cffi_available(), "curl_cffi not installed")
class TestCurlCffiBackend(unittest.TestCase):
    def test_curl_cffi_backend_delegates_to_session(self):
        session = mock.Mock()
        response = mock.Mock(status_code=200, headers={}, text="<html>cffi</html>")
        session.get.return_value = response

        with mock.patch(
            "ygo_app.cardmarket.http_client.create_curl_cffi_session",
            return_value=session,
        ):
            html, error = fetch_url(
                None,
                "https://www.cardmarket.com/en/YuGiOh",
                backend="curl_cffi",
                rate_limiter=RateLimiter(1000),
            )

        self.assertEqual(html, "<html>cffi</html>")
        self.assertIsNone(error)
        session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
