"""Tests for the card image mirror sync job (fake S3, no network)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ygo_app.image_mirror import load_images_manifest
from ygo_app.jobs import sync_card_images
from ygo_app.jobs.sync_card_images import FAILURES_FILENAME, manifest_from_bucket, sync_images


class FakeS3:
    """Minimal in-memory stand-in for the boto3 S3 client surface used."""

    def __init__(self, keys: set[str] | None = None):
        self.objects: dict[str, bytes] = {key: b"" for key in (keys or set())}
        self.put_calls: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix=""):
                contents = [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)]
                yield {"Contents": contents}

        return Paginator()

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
        self.objects[Key] = Body
        self.put_calls.append(Key)


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (300, 440), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


class FakeScraper:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.requested: list[str] = []

    def get(self, url, timeout=60):
        self.requested.append(url)
        payload = self.payload

        class Response:
            content = payload

            def raise_for_status(self):
                pass

        return Response()


class TestSyncImages(unittest.TestCase):
    def _run(self, entries, s3, *, force=False):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            scraper = FakeScraper(_png_bytes())
            with mock.patch.object(sync_card_images, "create_scraper", return_value=scraper), \
                    mock.patch.object(sync_card_images._rate_limiter, "min_interval", 0):
                counters = sync_images(
                    entries, s3, "bucket", force=force, manifest_path=manifest_path
                )
            return counters, scraper, load_images_manifest(manifest_path)

    def test_uploads_missing_and_skips_existing(self):
        entries = [
            {"id": "11111111", "image_url": "https://ms.yugipedia.com//a/b/One.png"},
            {"id": "22222222", "image_url": "https://ms.yugipedia.com//c/d/Two.png"},
        ]
        s3 = FakeS3({"cards/11111111.webp", "cards/11111111-small.webp"})
        counters, scraper, manifest = self._run(entries, s3)

        self.assertEqual(counters["skipped_existing"], 1)
        self.assertEqual(counters["uploaded"], 1)
        # Only the missing card was downloaded.
        self.assertEqual(scraper.requested, ["https://ms.yugipedia.com//c/d/Two.png"])
        self.assertIn("cards/22222222.webp", s3.objects)
        self.assertIn("cards/22222222-small.webp", s3.objects)
        self.assertEqual(manifest, {11111111, 22222222})

    def test_entry_without_image_not_mirrored(self):
        entries = [{"id": "33333333", "image_url": None}]
        counters, scraper, manifest = self._run(entries, FakeS3())
        self.assertEqual(counters["no_image"], 1)
        self.assertEqual(scraper.requested, [])
        self.assertEqual(manifest, set())

    def test_uploaded_objects_are_webp(self):
        from PIL import Image

        entries = [{"id": "44444444", "image_url": "https://ms.yugipedia.com//e/f/Four.png"}]
        s3 = FakeS3()
        self._run(entries, s3)
        full = Image.open(io.BytesIO(s3.objects["cards/44444444.webp"]))
        small = Image.open(io.BytesIO(s3.objects["cards/44444444-small.webp"]))
        self.assertEqual(full.format, "WEBP")
        self.assertEqual(small.format, "WEBP")
        self.assertEqual(full.width, 300)
        self.assertLessEqual(small.width, sync_card_images.SMALL_WIDTH)
        self.assertEqual(small.width, 300)

    def test_small_thumb_downscales_large_source(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (600, 880), (10, 120, 200)).save(buf, "PNG")
        entries = [{"id": "55555555", "image_url": "https://ms.yugipedia.com//g/h/Five.png"}]
        s3 = FakeS3()
        scraper = FakeScraper(buf.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            with mock.patch.object(sync_card_images, "create_scraper", return_value=scraper), \
                    mock.patch.object(sync_card_images._rate_limiter, "min_interval", 0):
                sync_images(entries, s3, "bucket", manifest_path=manifest_path)
        small = Image.open(io.BytesIO(s3.objects["cards/55555555-small.webp"]))
        self.assertEqual(small.width, sync_card_images.SMALL_WIDTH)

    def test_progress_emits_multiple_times(self):
        entries = [
            {"id": f"{index:08d}", "image_url": f"https://ms.yugipedia.com//x/{index}.png"}
            for index in range(120)
        ]
        s3 = FakeS3()
        log_messages: list[str] = []

        def capture_log(message: str) -> None:
            log_messages.append(message)

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            scraper = FakeScraper(_png_bytes())
            with mock.patch.object(sync_card_images, "log_line", side_effect=capture_log), \
                    mock.patch.object(sync_card_images, "create_scraper", return_value=scraper), \
                    mock.patch.object(sync_card_images._rate_limiter, "min_interval", 0):
                sync_images(entries, s3, "bucket", manifest_path=manifest_path)

        progress_msgs = [message for message in log_messages if message.startswith("[PROGRESS]")]
        self.assertGreaterEqual(len(progress_msgs), 3)
        self.assertTrue(any("/120" in message for message in progress_msgs))
        self.assertTrue(any(message.startswith("[RESULT]") for message in log_messages))

    def test_download_failure_writes_failures_json(self):
        entries = [{"id": "66666666", "image_url": "https://ms.yugipedia.com//fail.png"}]
        s3 = FakeS3()

        def fail_fetch(_scraper, _url, **kwargs):
            return None, "HTTPError: 404 Not Found"

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            with mock.patch.object(sync_card_images, "fetch_image_bytes", side_effect=fail_fetch), \
                    mock.patch.object(sync_card_images, "create_scraper"), \
                    mock.patch.object(sync_card_images._rate_limiter, "min_interval", 0):
                counters = sync_images(entries, s3, "bucket", manifest_path=manifest_path)
            failures_path = manifest_path.parent / FAILURES_FILENAME
            self.assertEqual(counters["failed"], 1)
            self.assertTrue(failures_path.exists())
            failures = json.loads(failures_path.read_text(encoding="utf-8"))
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["passcode"], 66666666)
            self.assertEqual(failures[0]["stage"], "download")

    def test_main_returns_1_when_sync_has_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "cards.json"
            json_path.write_text('[{"id": "12345678", "image_url": "https://example.com/x.png"}]', encoding="utf-8")
            manifest_path = Path(tmp) / "manifest.json"
            with mock.patch.object(sync_card_images, "build_s3_client", return_value=FakeS3()), \
                    mock.patch(
                        "ygo_app.jobs.import_catalog_yugipedia.load_yugipedia_cards",
                        return_value=[{"id": "12345678", "image_url": "https://example.com/x.png"}],
                    ), \
                    mock.patch.object(
                        sync_card_images,
                        "sync_images",
                        return_value={
                            "skipped_existing": 0,
                            "uploaded": 0,
                            "no_image": 0,
                            "failed": 1,
                        },
                    ):
                rc = sync_card_images.main(["--json", str(json_path), "--manifest", str(manifest_path)])
            self.assertEqual(rc, 1)


class TestManifestFromBucket(unittest.TestCase):
    def test_requires_both_objects(self):
        s3 = FakeS3(
            {
                "cards/11111111.webp",
                "cards/11111111-small.webp",
                "cards/22222222.webp",  # missing small -> excluded
                "cards/not-a-card.webp",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            mirrored = manifest_from_bucket(s3, "bucket", path)
            self.assertEqual(mirrored, {11111111})
            self.assertEqual(load_images_manifest(path), {11111111})


if __name__ == "__main__":
    unittest.main()
