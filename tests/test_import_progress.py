"""Unit tests for import progress helpers."""

from __future__ import annotations

import time
import unittest

from ygo_app.import_progress import ProgressThrottle, build_progress_event, eta_seconds


class TestImportProgress(unittest.TestCase):
    def test_eta_none_until_min_rows(self):
        started = time.monotonic()
        self.assertIsNone(eta_seconds(5, 100, started))

    def test_eta_positive_after_enough_rows(self):
        started = time.monotonic() - 10.0
        eta = eta_seconds(50, 100, started)
        self.assertIsNotNone(eta)
        self.assertGreater(eta, 0)

    def test_throttle_emits_first_and_final(self):
        throttle = ProgressThrottle(every_rows=10, every_seconds=999)
        self.assertTrue(throttle.should_emit(1))
        for i in range(2, 10):
            self.assertFalse(throttle.should_emit(i))
        self.assertTrue(throttle.should_emit(11))

    def test_build_progress_event_includes_remaining(self):
        payload = build_progress_event(
            phase="importing",
            current=25,
            total=100,
            started=time.monotonic() - 5.0,
        )
        self.assertEqual(payload["type"], "progress")
        self.assertEqual(payload["phase"], "importing")
        self.assertEqual(payload["remaining"], 75)
        self.assertEqual(payload["percent"], 25)
