"""Detect Chapters button and DetectChaptersWorker — closes #23.

Detection is slow and destructive of the existing chapter list, so the button
is explicit, gated on a loaded book, confirmed before it runs, and cancellable.
Those four properties are what this file pins.

See tests/gui/test_window.py's module docstring for why Qt tests run offscreen
and why a live QThread at teardown aborts the process.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from m4bmaker.gui.window import MainWindow  # noqa: E402
from m4bmaker.gui.worker import DetectChaptersWorker  # noqa: E402
from m4bmaker.models import Book, BookMetadata, Chapter  # noqa: E402

QMB = "m4bmaker.gui.window.QMessageBox"


def _make_book(tmp_path: Path) -> Book:
    f = tmp_path / "01.mp3"
    f.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
    return Book(
        files=[f],
        chapters=[Chapter(index=1, start_time=0.0, title="Ch 1", source_file=f)],
        metadata=BookMetadata(title="T", author="A", narrator="N"),
        cover=None,
        total_duration=600.0,
    )


@pytest.fixture
def win(qapp, tmp_path):
    w = MainWindow()
    w.show()
    yield w, tmp_path
    w._is_busy = lambda: False  # type: ignore[method-assign]
    w.close()
    w.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()


def _detected() -> list[Chapter]:
    return [
        Chapter(index=1, start_time=0.0, title="Chapter 1", source_file=None),
        Chapter(index=2, start_time=120.0, title="Chapter 2", source_file=None),
        Chapter(index=3, start_time=300.0, title="Chapter 3", source_file=None),
    ]


# ── the button ────────────────────────────────────────────────────────────────


class TestDetectButton:
    def test_button_exists_on_chapters_tab(self, win):
        w, _ = win
        assert w._detect_btn is not None
        assert w._detect_btn.text() == "Detect Chapters"

    def test_disabled_with_no_book_loaded(self, win):
        w, _ = win
        assert not w._detect_btn.isEnabled()

    def test_enabled_once_a_book_is_loaded(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        assert w._detect_btn.isEnabled()

    def test_no_book_is_a_noop(self, win):
        w, _ = win
        with patch(f"{QMB}.question") as ask:
            w._on_detect_chapters()
        ask.assert_not_called()


# ── confirmation before replacing chapters ────────────────────────────────────


class TestConfirmation:
    def test_confirms_before_replacing(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        with (
            patch(f"{QMB}.question") as ask,
            patch("m4bmaker.gui.window.DetectChaptersWorker") as worker,
        ):
            ask.return_value = MagicMock()  # not StandardButton.Yes
            w._on_detect_chapters()
        ask.assert_called_once()
        worker.assert_not_called()

    def test_confirmation_names_how_many_will_be_replaced(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        with (
            patch(f"{QMB}.question") as ask,
            patch("m4bmaker.gui.window.DetectChaptersWorker"),
        ):
            ask.return_value = MagicMock()
            w._on_detect_chapters()
        assert "1 chapter(s)" in ask.call_args[0][2]

    def test_declining_leaves_chapters_untouched(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        w._apply_book_to_ui(book)
        with (
            patch(f"{QMB}.question") as ask,
            patch("m4bmaker.gui.window.DetectChaptersWorker"),
        ):
            ask.return_value = MagicMock()
            w._on_detect_chapters()
        assert [c.title for c in w._book.chapters] == ["Ch 1"]

    def test_accepting_starts_the_worker(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        from PySide6.QtWidgets import QMessageBox

        started = MagicMock()
        started.isRunning.return_value = True
        with (
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.Yes),
            patch(
                "m4bmaker.gui.window.DetectChaptersWorker", return_value=started
            ) as cls,
        ):
            w._on_detect_chapters()
        cls.assert_called_once()
        started.start.assert_called_once()
        # The worker gets the book's files and its known total duration.
        assert cls.call_args.kwargs["total_duration"] == 600.0
        w._detect_worker = None


# ── results ───────────────────────────────────────────────────────────────────


class TestDetectResults:
    def test_detected_chapters_replace_the_table(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        w._on_detect_finished(_detected())
        assert w._chapter_table.rowCount() == 3
        assert [c.title for c in w._book.chapters] == [
            "Chapter 1",
            "Chapter 2",
            "Chapter 3",
        ]

    def test_status_reports_the_count(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        w._on_detect_finished(_detected())
        assert "3 chapter(s)" in w._status_label.text()

    def test_non_list_payload_is_rejected(self, win, tmp_path):
        # L8: validate the payload shape rather than trusting the signal.
        w, _ = win
        book = _make_book(tmp_path)
        w._apply_book_to_ui(book)
        w._on_detect_finished("not a list")
        assert [c.title for c in w._book.chapters] == ["Ch 1"]

    def test_error_shows_a_dialog(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        with patch(f"{QMB}.critical") as crit:
            w._on_detect_error("ffmpeg blew up")
        crit.assert_called_once()
        assert "ffmpeg blew up" in crit.call_args[0]

    def test_cancellation_is_not_an_error(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        with patch(f"{QMB}.critical") as crit:
            w._on_detect_cancelled()
        crit.assert_not_called()
        assert "ancel" in w._status_label.text()

    def test_button_re_enabled_after_completion(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        w._on_detect_finished(_detected())
        assert w._detect_btn.isEnabled()


# ── the worker ────────────────────────────────────────────────────────────────


class TestDetectChaptersWorker:
    def test_follows_the_cancellable_pattern(self, tmp_path):
        worker = DetectChaptersWorker(files=[tmp_path / "a.mp3"], total_duration=60.0)
        assert isinstance(worker._cancel_event, threading.Event)
        assert not worker._cancel_event.is_set()
        worker.request_cancel()
        assert worker._cancel_event.is_set()

    def test_exposes_the_expected_signals(self, tmp_path):
        worker = DetectChaptersWorker(files=[], total_duration=0.0)
        for name in ("progress", "result_ready", "cancelled", "error"):
            assert hasattr(worker, name)

    def test_run_emits_detected_chapters(self, tmp_path):
        f = tmp_path / "01.mp3"
        f.write_bytes(b"\x00")
        worker = DetectChaptersWorker(files=[f], total_duration=600.0)
        received: list[object] = []
        worker.result_ready.connect(received.append)
        with (
            patch("m4bmaker.gui.worker.find_ffmpeg", return_value="ffmpeg"),
            patch(
                "m4bmaker.gui.worker.detect_silence",
                return_value=[(100.0, 120.0), (280.0, 300.0)],
            ),
        ):
            worker.run()
        assert len(received) == 1
        assert [c.start_time for c in received[0]] == [0.0, 120.0, 300.0]

    def test_run_emits_error_on_failure(self, tmp_path):
        from m4bmaker.errors import M4BError

        f = tmp_path / "01.mp3"
        f.write_bytes(b"\x00")
        worker = DetectChaptersWorker(files=[f], total_duration=600.0)
        errors: list[str] = []
        worker.error.connect(errors.append)
        with (
            patch("m4bmaker.gui.worker.find_ffmpeg", return_value="ffmpeg"),
            patch(
                "m4bmaker.gui.worker.detect_silence",
                side_effect=M4BError("no ffmpeg"),
            ),
        ):
            worker.run()
        assert errors == ["no ffmpeg"]

    def test_run_emits_cancelled_when_aborted(self, tmp_path):
        from m4bmaker.errors import EncodeCancelled

        f = tmp_path / "01.mp3"
        f.write_bytes(b"\x00")
        worker = DetectChaptersWorker(files=[f], total_duration=600.0)
        seen: list[bool] = []
        worker.cancelled.connect(lambda: seen.append(True))
        with (
            patch("m4bmaker.gui.worker.find_ffmpeg", return_value="ffmpeg"),
            patch(
                "m4bmaker.gui.worker.detect_silence",
                side_effect=EncodeCancelled("stopped"),
            ),
        ):
            worker.run()
        assert seen == [True]

    def test_progress_converts_seconds_to_a_fraction(self, tmp_path):
        worker = DetectChaptersWorker(files=[], total_duration=200.0)
        seen: list[tuple[str, float]] = []
        worker.progress.connect(lambda m, f: seen.append((m, f)))
        worker._on_analysed(50.0)
        assert seen[-1][1] == pytest.approx(0.25)
        assert "25%" in seen[-1][0]

    def test_progress_is_indeterminate_without_a_total(self, tmp_path):
        worker = DetectChaptersWorker(files=[], total_duration=0.0)
        seen: list[tuple[str, float]] = []
        worker.progress.connect(lambda m, f: seen.append((m, f)))
        worker._on_analysed(50.0)
        assert seen[-1][1] == 0.0
