"""R2 upload helpers for Cardmarket catalog artifacts."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import brotli

from ygo_app.cardmarket.archive_compression import (
    PRICES_EXPORT_MEMBER,
    brotli_decompress_to_path,
    extract_prices_zip,
    write_lzma_zip,
)
from ygo_app.cardmarket.export_schema import load_export
from ygo_app.cardmarket.paths import LEGACY_R2_CARDMARKET_PRICES_KEY, prices_archive_key
from ygo_app.cardmarket.r2_storage import (
    download_latest_prices_archive,
    upload_catalog_archive,
    upload_pipeline_report,
    upload_prices_archive,
    upload_run_log,
)
from ygo_app.jobs.sync_cardmarket_catalog import _run_ts_suffix

_RUN_TS = "20260629_1200"
_CARDMARKET_BUCKET = "ygo-cardmarket"
_SAMPLE_EXPORT = {
    "schema_version": 1,
    "exported_at": "2026-06-29T12:00:00+00:00",
    "source": "cardmarket-catalog",
    "currency": "EUR",
    "stats": {"total": 1},
    "prices": [
        {
            "set_code": "LOB",
            "rarity_code": "LOB-EN001",
            "discovery_status": "matched",
            "low_price": 1.0,
            "avg_price": 2.0,
            "trend_price": 1.5,
        }
    ],
}


class TestArchiveCompression(unittest.TestCase):
    def test_lzma_zip_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "cardmarket_prices.json"
            src.write_text(json.dumps(_SAMPLE_EXPORT), encoding="utf-8")
            zip_path = tmp_path / "prices.zip"
            write_lzma_zip(zip_path, [(src, PRICES_EXPORT_MEMBER)])

            with zipfile.ZipFile(zip_path, "r") as archive:
                info = archive.getinfo(PRICES_EXPORT_MEMBER)
                self.assertEqual(info.compress_type, zipfile.ZIP_LZMA)

            dest = tmp_path / "out.json"
            extract_prices_zip(zip_path, dest)
            payload = load_export(dest)
            self.assertEqual(payload["stats"]["total"], 1)

    def test_brotli_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "report.json"
            src.write_text('{"ok": true}', encoding="utf-8")
            br_path = tmp_path / "report.json.br"
            br_path.write_bytes(brotli.compress(src.read_bytes(), quality=11))
            dest = tmp_path / "out.json"
            brotli_decompress_to_path(br_path, dest)
            self.assertEqual(json.loads(dest.read_text(encoding="utf-8")), {"ok": True})


class TestCardmarketR2Storage(unittest.TestCase):
    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_catalog_archive_key_format_and_lzma(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in ("products_singles.json", "products_nonsingles.json", "price_guide.json"):
                (tmp_path / name).write_text("[]", encoding="utf-8")
            with patch(
                "ygo_app.cardmarket.r2_storage.config.S3_CARDMARKET_BUCKET",
                _CARDMARKET_BUCKET,
            ):
                key = upload_catalog_archive(
                    singles_path=tmp_path / "products_singles.json",
                    nonsingles_path=tmp_path / "products_nonsingles.json",
                    price_guide_path=tmp_path / "price_guide.json",
                    manifest={"run_id": "test"},
                    run_ts=_RUN_TS,
                )

        self.assertEqual(key, f"archives/catalog_archive_{_RUN_TS}.zip")
        mock_s3.upload_file.assert_called_once()
        args = mock_s3.upload_file.call_args
        self.assertEqual(args[0][1], _CARDMARKET_BUCKET)
        self.assertEqual(args[0][2], key)

    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_prices_archive_key_format(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3

        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "cardmarket_prices.json"
            export_path.write_text(json.dumps(_SAMPLE_EXPORT), encoding="utf-8")
            with patch(
                "ygo_app.cardmarket.r2_storage.config.S3_CARDMARKET_BUCKET",
                _CARDMARKET_BUCKET,
            ):
                key = upload_prices_archive(export_path, run_ts=_RUN_TS)

        expected_key = prices_archive_key(_RUN_TS)
        self.assertEqual(key, expected_key)
        mock_s3.upload_file.assert_called_once()
        args = mock_s3.upload_file.call_args
        self.assertEqual(args[0][1], _CARDMARKET_BUCKET)
        self.assertEqual(args[0][2], expected_key)

    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_run_log_key_format(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.log"
            log_path.write_text("[JOB_START]\n", encoding="utf-8")
            with patch(
                "ygo_app.cardmarket.r2_storage.config.S3_CARDMARKET_BUCKET",
                _CARDMARKET_BUCKET,
            ):
                key = upload_run_log(log_path, run_ts=_RUN_TS)

        self.assertEqual(key, f"archives/sync_price_log_{_RUN_TS}.log.br")
        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args.kwargs
        self.assertEqual(kwargs["Bucket"], _CARDMARKET_BUCKET)
        self.assertEqual(kwargs["Key"], key)
        self.assertIn("[JOB_START]", brotli.decompress(kwargs["Body"]).decode("utf-8"))

    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_pipeline_report_key_format(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text("{}", encoding="utf-8")
            with patch(
                "ygo_app.cardmarket.r2_storage.config.S3_CARDMARKET_BUCKET",
                _CARDMARKET_BUCKET,
            ):
                key = upload_pipeline_report(report_path, run_ts=_RUN_TS)

        self.assertEqual(key, f"archives/sync_price_report_{_RUN_TS}.json.br")
        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args.kwargs
        self.assertEqual(kwargs["Bucket"], _CARDMARKET_BUCKET)
        self.assertEqual(kwargs["Key"], key)

    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_download_latest_prices_archive_picks_newest(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3
        older = prices_archive_key("20260628_1200")
        newer = prices_archive_key("20260629_1200")
        mock_s3.list_objects_v2.return_value = {
            "Contents": [{"Key": older}, {"Key": newer}],
            "IsTruncated": False,
        }

        def _fake_download(bucket, key, dest):
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    PRICES_EXPORT_MEMBER,
                    json.dumps(_SAMPLE_EXPORT),
                )

        mock_s3.download_file.side_effect = _fake_download

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cardmarket_prices.json"
            with patch(
                "ygo_app.cardmarket.r2_storage.config.S3_CARDMARKET_BUCKET",
                _CARDMARKET_BUCKET,
            ):
                result = download_latest_prices_archive(dest)

            self.assertEqual(result, dest)
            self.assertTrue(dest.is_file())
            payload = load_export(dest)
            self.assertEqual(payload["stats"]["total"], 1)

        mock_s3.download_file.assert_called_once()
        self.assertEqual(mock_s3.download_file.call_args[0][1], newer)

    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_download_latest_prices_archive_legacy_fallback(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {"Contents": [], "IsTruncated": False}

        def _fake_download(bucket, key, dest):
            Path(dest).write_text(json.dumps(_SAMPLE_EXPORT), encoding="utf-8")

        mock_s3.download_file.side_effect = _fake_download

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cardmarket_prices.json"
            with patch(
                "ygo_app.cardmarket.r2_storage.config.S3_CARDMARKET_BUCKET",
                _CARDMARKET_BUCKET,
            ):
                download_latest_prices_archive(dest)

        mock_s3.download_file.assert_called_once()
        self.assertEqual(
            mock_s3.download_file.call_args[0][1],
            LEGACY_R2_CARDMARKET_PRICES_KEY,
        )


class TestRunTsSuffix(unittest.TestCase):
    def test_run_ts_suffix_format(self):
        ts = _run_ts_suffix()
        self.assertRegex(ts, re.compile(r"^\d{8}_\d{4}$"))


if __name__ == "__main__":
    unittest.main()
