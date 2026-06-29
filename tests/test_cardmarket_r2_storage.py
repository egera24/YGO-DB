"""R2 upload helpers for Cardmarket catalog artifacts."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ygo_app.cardmarket.r2_storage import (
    upload_catalog_archive,
    upload_pipeline_report,
    upload_run_log,
)
from ygo_app.jobs.sync_cardmarket_catalog import _run_ts_suffix

_RUN_TS = "20260629_1200"
_CARDMARKET_BUCKET = "ygo-cardmarket"


class TestCardmarketR2Storage(unittest.TestCase):
    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_catalog_archive_key_format(self, mock_build_client):
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

        self.assertEqual(key, f"archives/sync_price_log_{_RUN_TS}.log")
        mock_s3.upload_file.assert_called_once()
        args = mock_s3.upload_file.call_args
        self.assertEqual(args[0][1], _CARDMARKET_BUCKET)
        self.assertEqual(args[0][2], key)

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

        self.assertEqual(key, f"archives/sync_price_report_{_RUN_TS}.json")
        mock_s3.upload_file.assert_called_once()
        args = mock_s3.upload_file.call_args
        self.assertEqual(args[0][1], _CARDMARKET_BUCKET)
        self.assertEqual(args[0][2], key)


class TestRunTsSuffix(unittest.TestCase):
    def test_run_ts_suffix_format(self):
        ts = _run_ts_suffix()
        self.assertRegex(ts, re.compile(r"^\d{8}_\d{4}$"))


if __name__ == "__main__":
    unittest.main()
