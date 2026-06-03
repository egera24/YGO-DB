"""Tests for scrape heartbeat / stall detection."""

import unittest
from pathlib import Path

from ygo_app.yugipedia.scrape_progress import ScrapeProgressMonitor, ScrapeStalledError


class TestScrapeProgressMonitor(unittest.TestCase):
    def test_check_abort_raises_when_stall_set(self) -> None:
        out = Path("data/catalog/test_heartbeat.json")
        monitor = ScrapeProgressMonitor(total_pending=10, output_path=out)
        monitor._abort = ScrapeStalledError("simulated stall")
        with self.assertRaises(ScrapeStalledError):
            monitor.check_abort()

    def test_record_updates_progress_time(self) -> None:
        out = Path("data/catalog/test_heartbeat.json")
        monitor = ScrapeProgressMonitor(total_pending=10, output_path=out)
        before = monitor.seconds_since_progress()
        monitor.record(card_name="Test", success=True)
        after = monitor.seconds_since_progress()
        self.assertLess(after, before)


if __name__ == "__main__":
    unittest.main()
