"""Tests for batch completion audit and retryable error classification."""

import json
import tempfile
import unittest
from pathlib import Path

from ygo_app.yugipedia.details import audit_slice_completion
from ygo_app.yugipedia.scrape_progress import BatchIncompleteError, is_retryable_error


class TestIsRetryableError(unittest.TestCase):
    def test_timeout_is_retryable(self) -> None:
        self.assertTrue(is_retryable_error("ReadTimeout: timed out"))

    def test_cloudflare_is_retryable(self) -> None:
        self.assertTrue(is_retryable_error("CloudflareError: challenge"))

    def test_parse_error_is_final(self) -> None:
        self.assertFalse(is_retryable_error("Parse error: missing effect text"))

    def test_password_mismatch_is_final(self) -> None:
        self.assertFalse(is_retryable_error("Password mismatch: expected 12345678"))


class TestAuditSliceCompletion(unittest.TestCase):
    def test_complete_batch_no_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "all_cards.json"
            out.write_text(
                json.dumps([{"id": "00000001"}, {"id": "00000002"}]),
                encoding="utf-8",
            )
            slice_cards = [
                {"password": "00000001", "name": "A"},
                {"password": "00000002", "name": "B"},
            ]
            missing = audit_slice_completion(
                slice_cards=slice_cards,
                output_path=out,
                rejected_cards=[],
                batch_index=0,
                batch_count=2,
            )
            self.assertEqual(missing, 0)

    def test_missing_raises_for_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "all_cards.json"
            out.write_text(json.dumps([{"id": "00000001"}]), encoding="utf-8")
            slice_cards = [
                {"password": "00000001", "name": "A"},
                {"password": "00000002", "name": "B"},
            ]
            with self.assertRaises(BatchIncompleteError):
                audit_slice_completion(
                    slice_cards=slice_cards,
                    output_path=out,
                    rejected_cards=[],
                    batch_index=0,
                    batch_count=2,
                )

    def test_missing_counted_as_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "all_cards.json"
            out.write_text(json.dumps([{"id": "00000001"}]), encoding="utf-8")
            slice_cards = [
                {"password": "00000001", "name": "A"},
                {"password": "00000002", "name": "B"},
            ]
            rejected = [{"password": "00000002", "name": "B", "rejection_reason": "x"}]
            missing = audit_slice_completion(
                slice_cards=slice_cards,
                output_path=out,
                rejected_cards=rejected,
                batch_index=0,
                batch_count=2,
            )
            self.assertEqual(missing, 0)


if __name__ == "__main__":
    unittest.main()
