"""Phase 6D verification — FolderDropZone, CoverWidget, ChapterTable."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QKeyEvent,
)
from PySide6.QtWidgets import QLineEdit, QStyledItemDelegate  # noqa: E402

from m4bmaker.gui.widgets import (  # noqa: E402
    ChapterTable,
    CoverWidget,
    FindReplaceDialog,
    FolderDropZone,
)
from m4bmaker.models import Chapter  # noqa: E402

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_chapter(index: int, start: float, title: str) -> Chapter:
    return Chapter(index=index, start_time=start, title=title)


def _mime_with_dir(path: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def _mime_with_file(path: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def _make_drop_event(mime: QMimeData) -> QDropEvent:
    event = MagicMock(spec=QDropEvent)
    event.mimeData.return_value = mime
    event.acceptProposedAction = MagicMock()
    return event


def _make_drag_enter_event(mime: QMimeData, accept: bool = True) -> QDragEnterEvent:
    event = MagicMock(spec=QDragEnterEvent)
    event.mimeData.return_value = mime
    event.acceptProposedAction = MagicMock()
    event.ignore = MagicMock()
    return event


# ── FolderDropZone ────────────────────────────────────────────────────────────


class TestFolderDropZone:
    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.w = FolderDropZone()
        yield
        self.w.close()

    def test_initial_path_is_none(self):
        assert self.w.path() is None

    def test_set_path_updates_edit(self, tmp_path: Path):
        self.w.set_path(tmp_path)
        assert self.w.path() == tmp_path

    def test_set_path_emits_signal(self, tmp_path: Path):
        received = []
        self.w.folder_changed.connect(received.append)
        self.w.set_path(tmp_path)
        assert received == [tmp_path]

    def test_browse_sets_path(self, tmp_path: Path):
        with patch(
            "m4bmaker.gui.widgets.QFileDialog.getExistingDirectory",
            return_value=str(tmp_path),
        ):
            self.w._browse()
        assert self.w.path() == tmp_path

    def test_browse_cancelled_keeps_none(self):
        with patch(
            "m4bmaker.gui.widgets.QFileDialog.getExistingDirectory",
            return_value="",
        ):
            self.w._browse()
        assert self.w.path() is None

    def test_drag_enter_folder_accepted(self, tmp_path: Path):
        mime = _mime_with_dir(tmp_path)
        event = _make_drag_enter_event(mime)
        self.w.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()  # type: ignore[attr-defined]

    def test_drag_enter_file_ignored(self, tmp_path: Path):
        f = tmp_path / "file.mp3"
        f.write_bytes(b"x")
        mime = _mime_with_file(f)
        event = _make_drag_enter_event(mime)
        self.w.dragEnterEvent(event)
        event.ignore.assert_called_once()  # type: ignore[attr-defined]

    def test_drag_leave_clears_style(self, tmp_path: Path):
        event = MagicMock(spec=QDragLeaveEvent)
        self.w.dragLeaveEvent(event)
        assert self.w._edit.styleSheet() == ""

    def test_drop_folder_sets_path(self, tmp_path: Path):
        mime = _mime_with_dir(tmp_path)
        event = _make_drop_event(mime)
        self.w.dropEvent(event)
        assert self.w.path() == tmp_path

    def test_clear_btn_hidden_initially(self):
        assert not self.w._clear_btn.isVisible()

    def test_clear_btn_visible_after_set_path(self, tmp_path: Path):
        self.w.set_path(tmp_path)
        assert self.w._clear_btn.isVisibleTo(self.w)

    def test_clear_emits_folder_cleared(self, tmp_path: Path):
        received = []
        self.w.folder_cleared.connect(lambda: received.append(True))
        self.w.set_path(tmp_path)
        self.w._on_clear_clicked()
        assert received == [True]
        assert self.w.path() is None
        assert not self.w._clear_btn.isVisible()

    def test_is_accepted_swallows_oserror_from_dead_mount(self, tmp_path: Path):
        """L7: a stat() failure (e.g. dead network mount) must not propagate —
        the hover is simply rejected rather than hanging/raising."""
        bogus = tmp_path / "unreachable"
        with patch.object(Path, "is_dir", side_effect=OSError("stale handle")):
            assert self.w._is_accepted(bogus) is False


class TestFolderDropZoneM4b:
    """Tests for the accept_m4b=True variant — Edit… button / _browse_m4b."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.w = FolderDropZone(accept_m4b=True)
        yield
        self.w.close()

    def test_browse_m4b_sets_path(self, tmp_path: Path):
        """_browse_m4b delegates a valid picked path to set_path (M3 async path)."""
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        macos_patch = "m4bmaker.gui.widgets.FolderDropZone._browse_m4b_macos"
        with patch(macos_patch, side_effect=lambda: self.w._handle_m4b_path(str(m4b))):
            self.w._browse_m4b()
        assert self.w.path() == m4b

    def test_browse_m4b_cancelled_is_noop(self):
        macos_patch = "m4bmaker.gui.widgets.FolderDropZone._browse_m4b_macos"
        with patch(macos_patch, side_effect=lambda: self.w._handle_m4b_path("")):
            self.w._browse_m4b()
        assert self.w.path() is None

    def test_browse_m4b_wrong_extension_shows_warning(self, tmp_path: Path):
        mp3 = tmp_path / "audio.mp3"
        mp3.write_bytes(b"\x00")
        received: list = []
        self.w.folder_changed.connect(received.append)
        macos_patch = "m4bmaker.gui.widgets.FolderDropZone._browse_m4b_macos"
        with (
            patch(
                macos_patch,
                side_effect=lambda: self.w._handle_m4b_path(str(mp3)),
            ),
            patch("m4bmaker.gui.widgets.QMessageBox.warning") as mock_warn,
        ):
            self.w._browse_m4b()
        mock_warn.assert_called_once()
        assert received == []

    # ── async QProcess picker (M3) ──────────────────────────────────────────

    def test_browse_m4b_macos_starts_qprocess(self):
        """_browse_m4b_macos must not block — it starts a QProcess and returns."""
        with patch("m4bmaker.gui.widgets.QProcess.start") as mock_start:
            self.w._browse_m4b_macos()
        mock_start.assert_called_once()
        assert self.w._m4b_picker_proc is not None

    def test_picker_finished_success_sets_path(self, tmp_path: Path):
        from PySide6.QtCore import QByteArray, QProcess

        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        # Never actually spawn osascript in tests — only its result handling
        # is under test here.
        with patch("m4bmaker.gui.widgets.QProcess.start"):
            self.w._browse_m4b_macos()
        proc = self.w._m4b_picker_proc
        assert proc is not None
        with patch.object(
            proc, "readAllStandardOutput", return_value=QByteArray(str(m4b).encode())
        ):
            self.w._on_m4b_picker_finished(0, QProcess.ExitStatus.NormalExit)
        assert self.w.path() == m4b
        assert self.w._m4b_picker_proc is None

    def test_picker_finished_nonzero_exit_is_noop(self):
        """A non-zero exit means the user cancelled the panel — no path change."""
        from PySide6.QtCore import QProcess

        with patch("m4bmaker.gui.widgets.QProcess.start"):
            self.w._browse_m4b_macos()
        self.w._on_m4b_picker_finished(1, QProcess.ExitStatus.NormalExit)
        assert self.w.path() is None
        assert self.w._m4b_picker_proc is None

    def test_picker_error_falls_back_to_qfiledialog(self, tmp_path: Path):
        from PySide6.QtCore import QProcess

        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        with patch("m4bmaker.gui.widgets.QProcess.start"):
            self.w._browse_m4b_macos()
        with patch(
            "m4bmaker.gui.widgets.QFileDialog.getOpenFileName",
            return_value=(str(m4b), ""),
        ):
            self.w._on_m4b_picker_error(QProcess.ProcessError.FailedToStart)
        assert self.w.path() == m4b
        assert self.w._m4b_picker_proc is None

    def test_drag_enter_m4b_accepted(self, tmp_path: Path):
        f = tmp_path / "book.m4b"
        f.write_bytes(b"\x00")
        mime = _mime_with_file(f)
        event = _make_drag_enter_event(mime)
        self.w.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()

    def test_drop_m4b_sets_path(self, tmp_path: Path):
        f = tmp_path / "book.m4b"
        f.write_bytes(b"\x00")
        mime = _mime_with_file(f)
        event = _make_drop_event(mime)
        self.w.dropEvent(event)
        assert self.w.path() == f


class TestCoverWidget:

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.w = CoverWidget()
        yield
        self.w.close()

    def test_initial_cover_is_none(self):
        assert self.w.cover_path() is None

    def test_set_cover_nonexistent_shows_placeholder(self, tmp_path: Path):
        self.w.set_cover(tmp_path / "missing.jpg")
        assert self.w._thumb.text() == "Cover"

    def test_set_cover_none_shows_placeholder(self):
        self.w.set_cover(None)
        assert self.w._thumb.text() == "Cover"

    def test_set_cover_real_image(self, tmp_path: Path):
        # Write a 1×1 PNG (minimal valid PNG bytes)
        png = tmp_path / "cover.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.w.set_cover(png)
        assert self.w.cover_path() == png

    def test_browse_sets_cover(self, tmp_path: Path):
        png = tmp_path / "cover.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        received = []
        self.w.cover_changed.connect(received.append)
        with patch(
            "m4bmaker.gui.widgets.QFileDialog.getOpenFileName",
            return_value=(str(png), ""),
        ):
            self.w._browse()
        assert received == [png]

    def test_browse_cancelled_no_signal(self):
        received = []
        self.w.cover_changed.connect(received.append)
        with patch(
            "m4bmaker.gui.widgets.QFileDialog.getOpenFileName",
            return_value=("", ""),
        ):
            self.w._browse()
        assert received == []

    def test_drop_image_accepted(self, tmp_path: Path):
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        mime = _mime_with_file(img)
        event = _make_drop_event(mime)
        received = []
        self.w.cover_changed.connect(received.append)
        self.w.dropEvent(event)
        assert received == [img]

    def test_drag_enter_non_image_ignored(self, tmp_path: Path):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\xff\xfb\x90\x00")
        mime = _mime_with_file(f)
        event = _make_drag_enter_event(mime)
        self.w.dragEnterEvent(event)
        event.ignore.assert_called_once()  # type: ignore[attr-defined]

    def test_set_cover_non_null_pixmap_displays_thumb(self, tmp_path: Path):
        """Lines 176-185: pixmap loads OK → thumbnail shows image, text cleared."""
        png = tmp_path / "cover.png"
        png.write_bytes(b"\x89PNG" + b"\x00" * 20)
        mock_pix = MagicMock()
        mock_pix.isNull.return_value = False
        mock_pix.scaled.return_value = MagicMock()
        with (
            patch("m4bmaker.gui.widgets.QPixmap", return_value=mock_pix),
            patch.object(self.w._thumb, "setPixmap"),  # bypass strict type check
        ):
            self.w.set_cover(png)
        assert self.w._thumb.text() == ""
        assert self.w.cover_path() == png
        mock_pix.scaled.assert_called_once()

    def test_drag_enter_image_accepted(self, tmp_path: Path):
        """Lines 217-218: image URL accepted, style and event updated."""
        img = tmp_path / "art.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        mime = _mime_with_file(img)
        event = _make_drag_enter_event(mime)
        self.w.dragEnterEvent(event)
        event.acceptProposedAction.assert_called_once()  # type: ignore[attr-defined]

    def test_drag_leave_resets_thumb_style(self):
        """Line 223: dragLeave resets thumbnail stylesheet."""
        event = MagicMock(spec=QDragLeaveEvent)
        self.w.dragLeaveEvent(event)  # must not raise


class TestCoverWidgetUrlDownload:
    """M4: URL cover art downloads run in a QThread worker, not the UI thread."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.w = CoverWidget()
        yield
        self.w.close()

    def test_browse_url_rejects_http(self):
        with (
            patch(
                "m4bmaker.gui.widgets.QInputDialog.getText",
                return_value=("http://example.com/cover.jpg", True),
            ),
            patch("m4bmaker.gui.widgets.QMessageBox.warning") as mock_warn,
        ):
            self.w._browse_url()
        mock_warn.assert_called_once()
        assert self.w._download_worker is None

    def test_browse_url_cancelled_is_noop(self):
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText", return_value=("", False)
        ):
            self.w._browse_url()
        assert self.w._download_worker is None

    def test_browse_url_starts_worker_and_disables_button(self):
        with (
            patch(
                "m4bmaker.gui.widgets.QInputDialog.getText",
                return_value=("https://example.com/cover.jpg", True),
            ),
            patch("m4bmaker.gui.widgets._CoverDownloadWorker.start") as mock_start,
        ):
            self.w._browse_url()
        mock_start.assert_called_once()
        assert self.w._download_worker is not None
        assert not self.w._url_btn.isEnabled()

    def test_download_finished_sets_cover_and_reenables_button(self, tmp_path: Path):
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)
        self.w._url_btn.setEnabled(False)
        received = []
        self.w.cover_changed.connect(received.append)
        self.w._on_download_finished(img)
        assert self.w.cover_path() == img
        assert received == [img]
        assert self.w._url_btn.isEnabled()

    def test_download_error_reenables_button_and_shows_message(self):
        self.w.show()
        self.w._url_btn.setEnabled(False)
        with patch("m4bmaker.gui.widgets.QMessageBox.critical") as mock_crit:
            self.w._on_download_error("boom")
        mock_crit.assert_called_once()
        assert self.w._url_btn.isEnabled()

    def test_download_error_no_dialog_when_not_visible(self):
        """A closed/hidden widget must not spawn a modal (mirrors window.py guard)."""
        self.w._url_btn.setEnabled(False)
        with patch("m4bmaker.gui.widgets.QMessageBox.critical") as mock_crit:
            self.w._on_download_error("boom")
        mock_crit.assert_not_called()
        assert self.w._url_btn.isEnabled()

    def test_browse_url_uses_download_cover(self, tmp_path: Path, qapp):
        """The worker's run() delegates to m4bmaker.cover.download_cover."""
        from m4bmaker.gui.widgets import _CoverDownloadWorker

        dest = tmp_path / "downloaded_cover.jpg"
        dest.write_bytes(b"\xff\xd8\xff")
        with patch("m4bmaker.gui.widgets.download_cover", return_value=dest) as mock_dl:
            worker = _CoverDownloadWorker("https://example.com/cover.jpg")
            results: list = []
            worker.result_ready.connect(results.append)
            worker.start()
            worker.wait(3000)
        qapp.processEvents()
        assert results == [dest]
        mock_dl.assert_called_once()
        assert mock_dl.call_args[0][0] == "https://example.com/cover.jpg"

    def test_worker_emits_error_on_m4berror(self, qapp):
        from m4bmaker.errors import M4BError
        from m4bmaker.gui.widgets import _CoverDownloadWorker

        with patch(
            "m4bmaker.gui.widgets.download_cover",
            side_effect=M4BError("bad content type"),
        ):
            worker = _CoverDownloadWorker("https://example.com/cover.jpg")
            errors: list = []
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)
        qapp.processEvents()
        assert errors == ["bad content type"]


# ── ChapterTable ──────────────────────────────────────────────────────────────


class TestChapterTablePopulate:
    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        yield
        self.t.close()

    def test_empty_populate(self):
        self.t.populate([])
        assert self.t.rowCount() == 0

    def test_row_count_matches_chapters(self):
        chapters = [_make_chapter(i, i * 60.0, f"Ch {i}") for i in range(1, 6)]
        self.t.populate(chapters)
        assert self.t.rowCount() == 5

    def test_chapter_number_column(self):
        self.t.populate([_make_chapter(3, 0.0, "Title")])
        assert self.t.item(0, ChapterTable.COL_NUM).text() == "3"  # type: ignore[union-attr]  # noqa: E501

    def test_timestamp_mm_ss(self):
        self.t.populate([_make_chapter(1, 75.0, "T")])  # 1 min 15 sec
        assert self.t.item(0, ChapterTable.COL_TIME).text() == "1:15.000"  # type: ignore[union-attr]  # noqa: E501

    def test_timestamp_h_mm_ss(self):
        self.t.populate([_make_chapter(1, 3661.0, "T")])  # 1h 1m 1s
        assert self.t.item(0, ChapterTable.COL_TIME).text() == "1:01:01.000"  # type: ignore[union-attr]  # noqa: E501

    def test_title_column_editable(self):
        self.t.populate([_make_chapter(1, 0.0, "Hello")])
        item = self.t.item(0, ChapterTable.COL_TITLE)
        assert item is not None
        assert item.flags() & Qt.ItemFlag.ItemIsEditable

    def test_num_column_not_editable(self):
        self.t.populate([_make_chapter(1, 0.0, "Hello")])
        item = self.t.item(0, ChapterTable.COL_NUM)
        assert item is not None
        assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)

    def test_titles_returns_all(self):
        chapters = [_make_chapter(i, float(i), f"Chapter {i}") for i in range(1, 4)]
        self.t.populate(chapters)
        assert self.t.titles() == ["Chapter 1", "Chapter 2", "Chapter 3"]

    def test_populate_clears_previous(self):
        self.t.populate([_make_chapter(1, 0.0, "Old")])
        self.t.populate([_make_chapter(1, 0.0, "New"), _make_chapter(2, 60.0, "New2")])
        assert self.t.rowCount() == 2
        assert self.t.item(0, ChapterTable.COL_TITLE).text() == "New"  # type: ignore[union-attr]  # noqa: E501


class TestChapterTableBulkEdit:
    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        chapters = [
            _make_chapter(1, 0.0, "01. Opening"),
            _make_chapter(2, 60.0, "02. middle part"),
            _make_chapter(3, 120.0, "03. THE END"),
        ]
        self.t.populate(chapters)
        yield
        self.t.close()

    def test_remove_numeric_prefix_all(self):
        self.t._remove_numeric()
        assert self.t.titles() == ["Opening", "middle part", "THE END"]

    def test_title_case_all(self):
        self.t._title_case()
        assert self.t.item(1, ChapterTable.COL_TITLE).text() == "02. Middle Part"  # type: ignore[union-attr]  # noqa: E501

    def test_sentence_case_all(self):
        self.t._sentence_case()
        # "02. middle part" → "02. middle part"[0].upper() + rest.lower()
        assert self.t.item(2, ChapterTable.COL_TITLE).text() == "03. the end"  # type: ignore[union-attr]  # noqa: E501

    def test_add_prefix_all(self):
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText", return_value=("X-", True)
        ):
            self.t._add_prefix()
        assert self.t.item(0, ChapterTable.COL_TITLE).text() == "X-01. Opening"  # type: ignore[union-attr]  # noqa: E501

    def test_add_suffix_all(self):
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText", return_value=(" [end]", True)
        ):
            self.t._add_suffix()
        assert self.t.item(0, ChapterTable.COL_TITLE).text() == "01. Opening [end]"  # type: ignore[union-attr]  # noqa: E501

    def test_find_replace_plain(self):
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("Opening", "Intro", False, False),
            ),
        ):
            self.t._find_replace()
        assert self.t.item(0, ChapterTable.COL_TITLE).text() == "01. Intro"  # type: ignore[union-attr]  # noqa: E501

    def test_find_replace_literal_default_does_not_treat_dot_as_wildcard(self):
        """L5: 'Find' is literal by default — '1.5' must not match '125'."""
        self.t.populate(
            [
                _make_chapter(1, 0.0, "Track 1.5"),
                _make_chapter(2, 60.0, "Track 125"),
            ]
        )
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("1.5", "X", False, False),
            ),
        ):
            self.t._find_replace()
        assert self.t.titles() == ["Track X", "Track 125"]

    def test_find_replace_literal_replacement_inserted_verbatim(self):
        """Backslash sequences in Replace must not be treated as a regex template."""
        self.t.populate([_make_chapter(1, 0.0, "Opening")])
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("Opening", r"A\1B", False, False),
            ),
        ):
            self.t._find_replace()
        assert self.t.titles() == [r"A\1B"]

    def test_find_replace_regex_mode_uses_backreferences(self):
        """Regex checkbox opts back into pattern matching (old behaviour)."""
        self.t.populate([_make_chapter(1, 0.0, "Chapter 12")])
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=(r"(\d+)", r"[\1]", False, True),
            ),
        ):
            self.t._find_replace()
        assert self.t.titles() == ["Chapter [12]"]

    def test_find_replace_invalid_regex_shows_warning(self):
        original = self.t.titles()
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("(unterminated", "X", False, True),
            ),
            patch("m4bmaker.gui.widgets.QMessageBox.warning") as mock_warn,
        ):
            self.t._find_replace()
        mock_warn.assert_called_once()
        assert self.t.titles() == original

    def test_find_replace_empty_find_is_noop(self):
        original = self.t.titles()
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog, "values", return_value=("", "X", False, False)
            ),
        ):
            self.t._find_replace()
        assert self.t.titles() == original

    def test_find_replace_cancelled_is_noop(self):
        original = self.t.titles()
        with patch.object(
            FindReplaceDialog,
            "exec",
            return_value=FindReplaceDialog.DialogCode.Rejected,
        ):
            self.t._find_replace()
        assert self.t.titles() == original

    def test_selected_rows_returns_all_when_none_selected(self):
        self.t.clearSelection()
        assert self.t._selected_rows() == [0, 1, 2]

    def test_selected_rows_returns_only_selected(self):
        self.t.selectRow(1)
        assert self.t._selected_rows() == [1]


class TestChapterTableSelectedOnlyEdit:
    """Bulk ops apply only to selected rows when a selection exists."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        self.t.populate(
            [
                _make_chapter(1, 0.0, "alpha"),
                _make_chapter(2, 60.0, "beta"),
                _make_chapter(3, 120.0, "gamma"),
            ]
        )
        self.t.selectRow(1)  # only row 1
        yield
        self.t.close()

    def test_title_case_only_selected(self):
        self.t._title_case()
        assert self.t.titles() == ["alpha", "Beta", "gamma"]

    def test_remove_numeric_only_selected(self):
        # none have numeric prefix, so no change; verifies scope only
        self.t._remove_numeric()
        assert self.t.titles() == ["alpha", "beta", "gamma"]


# ── FindReplaceDialog ─────────────────────────────────────────────────────────


class TestFindReplaceDialog:
    def test_values_returns_correct_tuple(self, qapp):
        dlg = FindReplaceDialog()
        dlg._find_edit.setText("foo")
        dlg._replace_edit.setText("bar")
        dlg._case_box.setChecked(True)
        assert dlg.values() == ("foo", "bar", True, False)

    def test_case_insensitive_default(self, qapp):
        dlg = FindReplaceDialog()
        _, _, case, _ = dlg.values()
        assert case is False

    def test_regex_unchecked_by_default(self, qapp):
        dlg = FindReplaceDialog()
        _, _, _, use_regex = dlg.values()
        assert use_regex is False

    def test_regex_checkbox_reflected_in_values(self, qapp):
        dlg = FindReplaceDialog()
        dlg._regex_box.setChecked(True)
        _, _, _, use_regex = dlg.values()
        assert use_regex is True


# ── _TitleDelegate ─────────────────────────────────────────────────────────


class TestTitleDelegate:
    """Lines 240-243: createEditor schedules selectAll on the line-edit."""

    def test_create_editor_selects_all_for_line_edit(self, qapp):
        from m4bmaker.gui import widgets as _w

        table = ChapterTable()
        table.populate([_make_chapter(1, 0.0, "test")])
        delegate = _w._TitleDelegate(table)
        index = table.model().index(0, ChapterTable.COL_TITLE)
        real_editor = QLineEdit()
        with patch.object(
            QStyledItemDelegate, "createEditor", return_value=real_editor
        ):
            with patch("m4bmaker.gui.widgets.QTimer") as mock_timer:
                editor = delegate.createEditor(table.viewport(), None, index)
        assert editor is real_editor
        mock_timer.singleShot.assert_called_once_with(0, real_editor.selectAll)
        real_editor.close()
        table.close()


# ── ChapterTable keyboard navigation ───────────────────────────────────────


class TestChapterTableKeyboard:
    """Lines 338-360: keyPressEvent navigation."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        self.t.populate(
            [
                _make_chapter(1, 0.0, "Row 0"),
                _make_chapter(2, 60.0, "Row 1"),
                _make_chapter(3, 120.0, "Row 2"),
            ]
        )
        yield
        self.t.close()

    @staticmethod
    def _key(
        key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> QKeyEvent:
        return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)

    def test_enter_moves_to_next_row(self):
        self.t.setCurrentCell(1, ChapterTable.COL_TITLE)
        self.t.keyPressEvent(self._key(Qt.Key.Key_Return))
        assert self.t.currentRow() == 2

    def test_shift_enter_moves_to_prev_row(self):
        self.t.setCurrentCell(1, ChapterTable.COL_TITLE)
        self.t.keyPressEvent(
            self._key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        )
        assert self.t.currentRow() == 0

    def test_tab_moves_to_next_row(self):
        self.t.setCurrentCell(0, ChapterTable.COL_TITLE)
        self.t.keyPressEvent(self._key(Qt.Key.Key_Tab))
        assert self.t.currentRow() == 1

    def test_backtab_moves_to_prev_row(self):
        self.t.setCurrentCell(1, ChapterTable.COL_TITLE)
        self.t.keyPressEvent(self._key(Qt.Key.Key_Backtab))
        assert self.t.currentRow() == 0

    def test_other_key_falls_through(self):
        """Non-navigation keys call super().keyPressEvent without error."""
        self.t.setCurrentCell(0, ChapterTable.COL_TITLE)
        self.t.keyPressEvent(self._key(Qt.Key.Key_Escape))
        assert self.t.currentRow() == 0  # no movement


# ── ChapterTable context menu ───────────────────────────────────────────────


class TestChapterTableContextMenu:
    """Lines 365-374: _show_context_menu builds and shows a QMenu."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        self.t.populate([_make_chapter(1, 0.0, "Test Chapter")])
        yield
        self.t.close()

    def test_show_context_menu_executes(self):
        with patch("m4bmaker.gui.widgets.QMenu") as mock_menu_cls:
            mock_menu = MagicMock()
            mock_menu_cls.return_value = mock_menu
            self.t._show_context_menu(QPoint(0, 0))
        mock_menu.exec.assert_called_once()
        assert mock_menu.addAction.call_count >= 2


# ── FindReplace re.error fallback ──────────────────────────────────────────


class TestFindReplaceFallback:
    """Literal mode (default, L5): regex metacharacters in Find are matched
    verbatim, so a string like ``[unclosed`` — invalid as a regex — still
    matches literally without raising or needing any fallback."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        self.t.populate(
            [
                _make_chapter(1, 0.0, "[unclosed bracket title"),
                _make_chapter(2, 60.0, "Normal Chapter"),
            ]
        )
        yield
        self.t.close()

    def test_literal_mode_case_insensitive_matches_metacharacters(self):
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("[unclosed", "REPLACED", False, False),
            ),
        ):
            self.t._find_replace()
        assert self.t.titles()[0] == "REPLACED bracket title"

    def test_literal_mode_case_sensitive_matches_metacharacters(self):
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("[unclosed", "REPLACED", True, False),
            ),
        ):
            self.t._find_replace()
        assert self.t.titles()[0] == "REPLACED bracket title"


# ── ChapterTable undo ──────────────────────────────────────────────────────────


class TestChapterTableUndo:
    """QUndoStack integration: bulk ops and time inserts are undoable."""

    @pytest.fixture(autouse=True)
    def widget(self, qapp):
        self.t = ChapterTable()
        self.t.populate(
            [
                _make_chapter(1, 0.0, "alpha"),
                _make_chapter(2, 60.0, "beta"),
                _make_chapter(3, 120.0, "gamma"),
            ]
        )
        yield
        self.t.close()

    # ── populate clears the stack ─────────────────────────────────────────────

    def test_populate_clears_undo_stack(self):
        self.t._title_case()
        assert self.t._undo_stack.canUndo()
        self.t.populate([_make_chapter(1, 0.0, "fresh")])
        assert not self.t._undo_stack.canUndo()

    # ── bulk title ops ────────────────────────────────────────────────────────

    def test_undo_title_case(self):
        original = self.t.titles()
        self.t._title_case()
        assert self.t.titles() == ["Alpha", "Beta", "Gamma"]
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    def test_undo_sentence_case(self):
        original = self.t.titles()
        self.t._sentence_case()
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    def test_undo_remove_numeric(self):
        self.t.populate(
            [
                _make_chapter(1, 0.0, "01. alpha"),
                _make_chapter(2, 60.0, "02. beta"),
            ]
        )
        original = self.t.titles()
        self.t._remove_numeric()
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    def test_undo_add_prefix(self):
        original = self.t.titles()
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText",
            return_value=("X-", True),
        ):
            self.t._add_prefix()
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    def test_undo_add_suffix(self):
        original = self.t.titles()
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText",
            return_value=("-end", True),
        ):
            self.t._add_suffix()
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    def test_undo_sequential_prefix(self):
        original = self.t.titles()
        self.t._add_sequential_prefix()
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    def test_undo_find_replace(self):
        original = self.t.titles()
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("alpha", "REPLACED", False, False),
            ),
        ):
            self.t._find_replace()
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    # ── no-op ops don't push to stack ────────────────────────────────────────

    def test_noop_find_replace_does_not_push(self):
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("NOMATCH", "X", False, False),
            ),
        ):
            self.t._find_replace()
        assert not self.t._undo_stack.canUndo()

    def test_cancelled_prefix_does_not_push(self):
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText",
            return_value=("", False),
        ):
            self.t._add_prefix()
        assert not self.t._undo_stack.canUndo()

    # ── multiple undo steps ───────────────────────────────────────────────────

    def test_two_ops_two_undos(self):
        original = self.t.titles()
        self.t._title_case()
        with patch(
            "m4bmaker.gui.widgets.QInputDialog.getText",
            return_value=("X-", True),
        ):
            self.t._add_prefix()
        assert self.t.titles() == ["X-Alpha", "X-Beta", "X-Gamma"]
        self.t._undo_stack.undo()
        assert self.t.titles() == ["Alpha", "Beta", "Gamma"]
        self.t._undo_stack.undo()
        assert self.t.titles() == original

    # ── time insert undo ──────────────────────────────────────────────────────

    def test_undo_set_chapter_time(self):
        old_text = self.t.item(0, ChapterTable.COL_TIME).text()  # type: ignore[union-attr]  # noqa: E501
        old_ms = self.t.item(0, ChapterTable.COL_TIME).data(  # type: ignore[union-attr]
            1
        )  # Qt.ItemDataRole.UserRole == 1 after Qt.UserRole alias
        self.t.set_chapter_time(0, 90_000)  # 1 min 30 sec
        assert self.t.item(0, ChapterTable.COL_TIME).text() == "1:30.000"  # type: ignore[union-attr]  # noqa: E501
        self.t._undo_stack.undo()
        assert self.t.item(0, ChapterTable.COL_TIME).text() == old_text  # type: ignore[union-attr]  # noqa: E501
        assert (
            self.t.item(0, ChapterTable.COL_TIME).data(1) == old_ms  # type: ignore[union-attr]  # noqa: E501
        )

    def test_set_chapter_time_out_of_range_no_crash(self):
        # row -1 and row == rowCount should be silent no-ops
        self.t.set_chapter_time(-1, 5000)
        self.t.set_chapter_time(self.t.rowCount(), 5000)
        assert not self.t._undo_stack.canUndo()


# ── _ms_to_display (Phase 3) ──────────────────────────────────────────────────────


from m4bmaker.gui.widgets import _ms_to_display  # noqa: E402


class TestMsToDisplay:
    def test_zero(self):
        assert _ms_to_display(0) == "0:00.000"

    def test_whole_seconds(self):
        assert _ms_to_display(5000) == "0:05.000"

    def test_sub_second(self):
        assert _ms_to_display(5450) == "0:05.450"

    def test_minutes(self):
        assert _ms_to_display(75_000) == "1:15.000"

    def test_minutes_with_millis(self):
        assert _ms_to_display(75_123) == "1:15.123"

    def test_boundary_one_hour(self):
        assert _ms_to_display(3_600_000) == "1:00:00.000"

    def test_hours(self):
        assert _ms_to_display(3_661_000) == "1:01:01.000"

    def test_hours_with_millis(self):
        assert _ms_to_display(3_661_500) == "1:01:01.500"

    def test_large_minutes_no_hours(self):
        assert _ms_to_display(3599_000) == "59:59.000"

    def test_millis_zero_padded(self):
        # 1 ms should format as .001 not .1
        assert _ms_to_display(1) == "0:00.001"

    def test_millis_ten_padded(self):
        # 10 ms should format as .010
        assert _ms_to_display(10) == "0:00.010"


# ── _parse_time_input + _TimeDelegate (Phase 4) ───────────────────────────────


from m4bmaker.gui.widgets import _parse_time_input  # noqa: E402


class TestParseTimeInput:
    def test_m_ss(self):
        assert _parse_time_input("1:30") == 90_000

    def test_m_ss_with_millis(self):
        assert _parse_time_input("1:30.500") == 90_500

    def test_m_ss_with_short_millis(self):
        # 1-digit fraction → right-padded: .5 == .500
        assert _parse_time_input("1:30.5") == 90_500

    def test_m_ss_with_two_digit_millis(self):
        # 2-digit fraction → right-padded: .45 == .450
        assert _parse_time_input("1:30.45") == 90_450

    def test_h_mm_ss(self):
        assert _parse_time_input("1:01:00") == 3_660_000

    def test_h_mm_ss_with_millis(self):
        assert _parse_time_input("1:01:00.250") == 3_660_250

    def test_zero(self):
        assert _parse_time_input("0:00") == 0

    def test_zero_with_millis(self):
        assert _parse_time_input("0:00.000") == 0

    def test_leading_whitespace_stripped(self):
        assert _parse_time_input("  1:30  ") == 90_000

    def test_invalid_empty(self):
        assert _parse_time_input("") is None

    def test_invalid_seconds_out_of_range(self):
        # seconds > 59 must reject
        assert _parse_time_input("1:60") is None

    def test_invalid_no_colon(self):
        assert _parse_time_input("130") is None

    def test_invalid_letters(self):
        assert _parse_time_input("one:30") is None

    def test_invalid_negative(self):
        assert _parse_time_input("-1:30") is None

    def test_invalid_trailing_garbage(self):
        assert _parse_time_input("1:30abc") is None


class TestTimeDelegate:
    """Integration: _TimeDelegate wired into ChapterTable.COL_TIME."""

    @pytest.fixture(autouse=True)
    def table(self, qapp):
        from m4bmaker.gui.widgets import ChapterTable

        self.t = ChapterTable()
        self.t.populate([_make_chapter(1, 75.0, "Title")])  # 1:15.000
        yield
        self.t.close()

    def test_time_cell_is_editable(self):
        """COL_TIME items must have ItemIsEditable flag."""
        item = self.t.item(0, ChapterTable.COL_TIME)
        assert item is not None
        assert bool(item.flags() & Qt.ItemFlag.ItemIsEditable)

    def test_valid_input_updates_display(self, qapp):
        """Valid typed time updates the cell display and UserRole data."""
        from m4bmaker.gui.widgets import _TimeDelegate
        from unittest.mock import MagicMock

        delegate = _TimeDelegate(self.t)
        editor = MagicMock()
        editor.text.return_value = "2:15.500"
        model = MagicMock()
        index = MagicMock()
        index.row.return_value = 0

        delegate.setModelData(editor, model, index)

        item = self.t.item(0, ChapterTable.COL_TIME)
        assert item is not None
        assert item.text() == "2:15.500"
        assert item.data(Qt.ItemDataRole.UserRole) == 135_500

    def test_invalid_input_leaves_cell_unchanged(self, qapp):
        """Invalid typed time must not change the cell at all."""
        from m4bmaker.gui.widgets import _TimeDelegate
        from unittest.mock import MagicMock

        original_item = self.t.item(0, ChapterTable.COL_TIME)
        assert original_item is not None
        original_text = original_item.text()  # "1:15.000"
        delegate = _TimeDelegate(self.t)
        editor = MagicMock()
        editor.text.return_value = "not_a_time"
        model = MagicMock()
        index = MagicMock()
        index.row.return_value = 0

        delegate.setModelData(editor, model, index)

        item = self.t.item(0, ChapterTable.COL_TIME)
        assert item is not None
        assert item.text() == original_text

    def test_valid_input_is_undoable(self, qapp):
        """Changes made via the delegate participate in undo."""
        from m4bmaker.gui.widgets import _TimeDelegate
        from unittest.mock import MagicMock

        delegate = _TimeDelegate(self.t)
        editor = MagicMock()
        editor.text.return_value = "3:00.000"
        model = MagicMock()
        index = MagicMock()
        index.row.return_value = 0

        delegate.setModelData(editor, model, index)
        item = self.t.item(0, ChapterTable.COL_TIME)
        assert item is not None
        assert item.text() == "3:00.000"

        self.t._undo_stack.undo()
        item = self.t.item(0, ChapterTable.COL_TIME)
        assert item is not None
        assert item.text() == "1:15.000"

    def test_zero_ms_is_valid(self, qapp):
        """Timestamp 0:00 is valid and must not be rejected."""
        from m4bmaker.gui.widgets import _TimeDelegate
        from unittest.mock import MagicMock

        delegate = _TimeDelegate(self.t)
        editor = MagicMock()
        editor.text.return_value = "0:00"
        model = MagicMock()
        index = MagicMock()
        index.row.return_value = 0

        delegate.setModelData(editor, model, index)

        item = self.t.item(0, ChapterTable.COL_TIME)
        assert item is not None
        assert item.data(Qt.ItemDataRole.UserRole) == 0
