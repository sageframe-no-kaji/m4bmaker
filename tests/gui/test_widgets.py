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
        assert self.t.item(0, ChapterTable.COL_TIME).text() == "1:15"  # type: ignore[union-attr]  # noqa: E501

    def test_timestamp_h_mm_ss(self):
        self.t.populate([_make_chapter(1, 3661.0, "T")])  # 1h 1m 1s
        assert self.t.item(0, ChapterTable.COL_TIME).text() == "1:01:01"  # type: ignore[union-attr]  # noqa: E501

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
                FindReplaceDialog, "values", return_value=("Opening", "Intro", False)
            ),
        ):
            self.t._find_replace()
        assert self.t.item(0, ChapterTable.COL_TITLE).text() == "01. Intro"  # type: ignore[union-attr]  # noqa: E501

    def test_find_replace_empty_find_is_noop(self):
        original = self.t.titles()
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(FindReplaceDialog, "values", return_value=("", "X", False)),
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
        assert dlg.values() == ("foo", "bar", True)

    def test_case_insensitive_default(self, qapp):
        dlg = FindReplaceDialog()
        _, _, case = dlg.values()
        assert case is False


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
    """Lines 393-406: invalid-regex find falls back to plain-string replace."""

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

    def test_invalid_regex_case_insensitive_uses_re_escape(self):
        """Lines 400-403: case_sensitive=False → re.sub(re.escape(find), ...)."""
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("[unclosed", "REPLACED", False),
            ),
        ):
            self.t._find_replace()
        assert self.t.titles()[0] == "REPLACED bracket title"

    def test_invalid_regex_case_sensitive_uses_str_replace(self):
        """Lines 404-406: case_sensitive=True → str.replace()."""
        with (
            patch.object(
                FindReplaceDialog,
                "exec",
                return_value=FindReplaceDialog.DialogCode.Accepted,
            ),
            patch.object(
                FindReplaceDialog,
                "values",
                return_value=("[unclosed", "REPLACED", True),
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
                return_value=("alpha", "REPLACED", False),
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
                return_value=("NOMATCH", "X", False),
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
        old_ms = self.t.item(  # type: ignore[union-attr]
            0, ChapterTable.COL_TIME
        ).data(1)  # Qt.ItemDataRole.UserRole == 1 after Qt.UserRole alias
        self.t.set_chapter_time(0, 90_000)  # 1 min 30 sec
        assert self.t.item(0, ChapterTable.COL_TIME).text() == "1:30"  # type: ignore[union-attr]  # noqa: E501
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
