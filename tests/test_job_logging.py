"""Tests for Cardmarket job file logging."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ygo_app.job_logging as job_logging
from ygo_app.yugipedia.scrape_progress import log_line


class TestJobLogging(unittest.TestCase):
    def setUp(self) -> None:
        job_logging.close_job_log()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmpdir.name)
        self._patch_log_dir = mock.patch.object(job_logging, "LOG_DIR", self.log_dir)
        self._patch_log_dir.start()

    def tearDown(self) -> None:
        job_logging.close_job_log()
        self._patch_log_dir.stop()
        self._tmpdir.cleanup()

    def test_log_line_tees_timestamped_line_to_console_and_file(self) -> None:
        path = job_logging.configure_job_log("test_job")
        try:
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                log_line("[FETCH] OK example")
            console = stdout.getvalue()
            self.assertRegex(
                console, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[FETCH\] OK example\n"
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("[JOB_START] job=test_job", text)
            self.assertRegex(text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[FETCH\] OK example")
        finally:
            job_logging.close_job_log(exit_code=0)

    def test_close_job_log_prints_job_end_to_console(self) -> None:
        job_logging.configure_job_log("test_job")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            job_logging.close_job_log(exit_code=0)
        self.assertIn("[JOB_END] elapsed=", stdout.getvalue())
        self.assertIn(" exit=0", stdout.getvalue())

    def test_close_job_log_writes_elapsed_and_exit_code(self) -> None:
        path = job_logging.configure_job_log("test_job")
        job_logging.close_job_log(exit_code=0)
        text = path.read_text(encoding="utf-8")
        self.assertIn("[JOB_END] elapsed=", text)
        self.assertIn(" exit=0", text)

    def test_collision_suffix_when_log_exists(self) -> None:
        started = job_logging.datetime.now().replace(microsecond=0)
        stamp = started.strftime("%Y%m%d_%H%M%S")
        existing = self.log_dir / f"dup_job_{stamp}.log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        existing.write_text("existing\n", encoding="utf-8")

        path = job_logging._resolve_log_path("dup_job", started)

        self.assertEqual(path.name, f"dup_job_{stamp}_001.log")

    def test_job_log_session_records_nonzero_exit_code(self) -> None:
        path_holder: list[Path] = []

        def failing_job() -> int:
            log_line("before failure")
            return 2

        with job_logging.job_log_session("session_job") as handle:
            path_holder.append(handle.path)
            handle.exit_code = failing_job()

        text = path_holder[0].read_text(encoding="utf-8")
        self.assertIn("before failure", text)
        self.assertIn(" exit=2", text)

    def test_job_log_session_sets_exit_one_on_exception(self) -> None:
        path_holder: list[Path] = []

        with self.assertRaises(ValueError):
            with job_logging.job_log_session("error_job") as handle:
                path_holder.append(handle.path)
                log_line("about to fail")
                raise ValueError("boom")

        text = path_holder[0].read_text(encoding="utf-8")
        self.assertIn("about to fail", text)
        self.assertIn(" exit=1", text)

    def test_run_job_logged_propagates_return_code(self) -> None:
        path_holder: list[Path] = []

        def capture_path() -> int:
            return 3

        original_configure = job_logging.configure_job_log

        def configure_and_capture(name: str) -> Path:
            path = original_configure(name)
            path_holder.append(path)
            return path

        with mock.patch.object(job_logging, "configure_job_log", side_effect=configure_and_capture):
            code = job_logging.run_job_logged("wrapped_job", capture_path)

        self.assertEqual(code, 3)
        text = path_holder[0].read_text(encoding="utf-8")
        self.assertIn(" exit=3", text)

    def test_log_line_without_session_only_prints(self) -> None:
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            log_line("console only")
        self.assertEqual(stdout.getvalue(), "console only\n")
        self.assertEqual(list(self.log_dir.glob("*.log")), [])


if __name__ == "__main__":
    unittest.main()
