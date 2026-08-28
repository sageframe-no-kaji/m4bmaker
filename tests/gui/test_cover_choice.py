"""Cover chooser dialog and the lookup's cover-application path.

The property that matters: dismissing the dialog must never be the destructive
option, and a cover the user already chose is never replaced without asking.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402

from m4bmaker.audnexus import AudnexusBook  # noqa: E402
from m4bmaker.gui.cover_choice import CoverChoiceDialog, describe_cover  # noqa: E402
from m4bmaker.gui.window import MainWindow  # noqa: E402
from m4bmaker.models import Book, BookMetadata, Chapter  # noqa: E402

DIALOG = "m4bmaker.gui.window.CoverChoiceDialog"


def _image(path: Path, width: int, height: int) -> Path:
    """Write a real decodable image of the given size."""
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.darkCyan)
    assert pixmap.save(str(path), "PNG")
    return path


def _make_book(tmp_path: Path, cover: Path | None = None) -> Book:
    f = tmp_path / "01.mp3"
    f.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
    return Book(
        files=[f],
        chapters=[Chapter(index=1, start_time=0.0, title="Ch 1", source_file=f)],
        metadata=BookMetadata(title="T", author="A", narrator="N"),
        cover=cover,
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


# ── describe_cover ────────────────────────────────────────────────────────────


class TestDescribeCover:
    def test_reports_pixel_dimensions(self, qapp, tmp_path):
        path = _image(tmp_path / "c.png", 640, 480)
        assert describe_cover(path) == "640 x 480 px"

    def test_unreadable_image_still_describes(self, qapp, tmp_path):
        path = tmp_path / "broken.png"
        path.write_bytes(b"not an image")
        assert describe_cover(path) == "unreadable image"


# ── the dialog ────────────────────────────────────────────────────────────────


class TestCoverChoiceDialog:
    def test_choosing_fetched_returns_it(self, qapp, tmp_path):
        current = _image(tmp_path / "cur.png", 200, 200)
        fetched = _image(tmp_path / "new.png", 1400, 1400)
        dialog = CoverChoiceDialog(current, fetched)
        dialog._use_fetched()
        assert dialog.chosen() == fetched

    def test_choosing_current_returns_it(self, qapp, tmp_path):
        current = _image(tmp_path / "cur.png", 200, 200)
        fetched = _image(tmp_path / "new.png", 1400, 1400)
        dialog = CoverChoiceDialog(current, fetched)
        dialog._keep_current()
        assert dialog.chosen() == current

    def test_dismissed_dialog_chooses_nothing(self, qapp, tmp_path):
        current = _image(tmp_path / "cur.png", 200, 200)
        fetched = _image(tmp_path / "new.png", 1400, 1400)
        dialog = CoverChoiceDialog(current, fetched)
        assert dialog.chosen() is None

    def test_builds_with_an_unreadable_image(self, qapp, tmp_path):
        # A cover Qt cannot decode must still produce a usable dialog.
        current = tmp_path / "broken.png"
        current.write_bytes(b"not an image")
        fetched = _image(tmp_path / "new.png", 800, 800)
        dialog = CoverChoiceDialog(current, fetched)
        assert dialog.chosen() is None


# ── application path ──────────────────────────────────────────────────────────


class TestOfferCover:
    def test_no_existing_cover_applies_without_asking(self, win, tmp_path):
        w, _ = win
        w._apply_book_to_ui(_make_book(tmp_path))
        fetched = _image(tmp_path / "new.png", 900, 900)
        with patch(DIALOG) as dialog:
            w._offer_cover(fetched)
        dialog.assert_not_called()
        assert w._cover_widget.cover_path() == fetched

    def test_existing_cover_asks(self, win, tmp_path):
        w, _ = win
        current = _image(tmp_path / "cur.png", 200, 200)
        w._apply_book_to_ui(_make_book(tmp_path, cover=current))
        fetched = _image(tmp_path / "new.png", 900, 900)
        instance = MagicMock()
        instance.chosen.return_value = fetched
        with patch(DIALOG, return_value=instance) as dialog:
            w._offer_cover(fetched)
        dialog.assert_called_once()
        assert w._cover_widget.cover_path() == fetched

    def test_keeping_current_leaves_it_alone(self, win, tmp_path):
        w, _ = win
        current = _image(tmp_path / "cur.png", 200, 200)
        w._apply_book_to_ui(_make_book(tmp_path, cover=current))
        fetched = _image(tmp_path / "new.png", 900, 900)
        instance = MagicMock()
        instance.chosen.return_value = current
        with patch(DIALOG, return_value=instance):
            w._offer_cover(fetched)
        assert w._cover_widget.cover_path() == current

    def test_dismissing_keeps_the_existing_cover(self, win, tmp_path):
        # Doing nothing must never be the destructive option.
        w, _ = win
        current = _image(tmp_path / "cur.png", 200, 200)
        w._apply_book_to_ui(_make_book(tmp_path, cover=current))
        fetched = _image(tmp_path / "new.png", 900, 900)
        instance = MagicMock()
        instance.chosen.return_value = None
        with patch(DIALOG, return_value=instance):
            w._offer_cover(fetched)
        assert w._cover_widget.cover_path() == current

    def test_missing_fetched_file_is_ignored(self, win, tmp_path):
        w, _ = win
        current = _image(tmp_path / "cur.png", 200, 200)
        w._apply_book_to_ui(_make_book(tmp_path, cover=current))
        with patch(DIALOG) as dialog:
            w._offer_cover(tmp_path / "does-not-exist.png")
        dialog.assert_not_called()
        assert w._cover_widget.cover_path() == current

    def test_lookup_result_routes_through_the_chooser(self, win, tmp_path):
        w, _ = win
        current = _image(tmp_path / "cur.png", 200, 200)
        w._apply_book_to_ui(_make_book(tmp_path, cover=current))
        fetched = _image(tmp_path / "new.png", 900, 900)
        instance = MagicMock()
        instance.chosen.return_value = fetched
        book = AudnexusBook(asin="B017V4IM1G", title="T")
        with patch(DIALOG, return_value=instance) as dialog:
            w._on_lookup_finished(book, [], "done.", str(fetched))
        dialog.assert_called_once()
        assert w._cover_widget.cover_path() == fetched

    def test_lookup_without_a_cover_asks_nothing(self, win, tmp_path):
        w, _ = win
        current = _image(tmp_path / "cur.png", 200, 200)
        w._apply_book_to_ui(_make_book(tmp_path, cover=current))
        book = AudnexusBook(asin="B017V4IM1G", title="T")
        with patch(DIALOG) as dialog:
            w._on_lookup_finished(book, [], "done.", "")
        dialog.assert_not_called()
        assert w._cover_widget.cover_path() == current
