"""R2 upload helpers for Cardmarket catalog artifacts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ygo_app.cardmarket.r2_storage import upload_pipeline_report, upload_run_log


class TestCardmarketR2Storage(unittest.TestCase):
    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_run_log_key_format(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.log"
            log_path.write_text("[JOB_START]\n", encoding="utf-8")
            with patch("ygo_app.cardmarket.r2_storage.config.S3_BUCKET", "test-bucket"):
                key = upload_run_log(log_path, timestamp="20260629T120000Z")

        self.assertEqual(key, "ygo-cardmarket/archives/20260629T120000Z.log")
        mock_s3.upload_file.assert_called_once()
        args = mock_s3.upload_file.call_args
        self.assertEqual(args[0][2], key)

    @patch("ygo_app.cardmarket.r2_storage.build_s3_client")
    def test_upload_pipeline_report_key_format(self, mock_build_client):
        mock_s3 = MagicMock()
        mock_build_client.return_value = mock_s3

        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text("{}", encoding="utf-8")
            with patch("ygo_app.cardmarket.r2_storage.config.S3_BUCKET", "test-bucket"):
                key = upload_pipeline_report(report_path, timestamp="20260629T120000Z")

        self.assertEqual(key, "ygo-cardmarket/archives/20260629T120000Z_report.json")


if __name__ == "__main__":
    unittest.main()
