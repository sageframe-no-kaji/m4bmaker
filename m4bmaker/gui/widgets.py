"""Reusable custom Qt widgets for m4bmaker GUI.

Widgets
-------
FolderDropZone  — path line-edit + Browse, accepts folder drag-and-drop
CoverWidget     — thumbnail + Choose button, accepts image drag-and-drop
ChapterTable    — editable flat table with keyboard nav and bulk-edit menu
FindReplaceDialog — simple find / replace dialog
"""

from __future__ import annotations

import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QKeySequence,
    QPixmap,
    QShortcut,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtWidgets import QLineEdit as _QLineEdit  # for selectAll cast
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ── Palette constants used in inline styles ──────────────────────────────────
_GROUND_WARM = "#ebe6dd"
_ACCENT = "#c45a2d"
_RULE = "#d0c9be"
_INK_MUTED = "#7a7a7a"

_THUMB_BASE = ""  # clear drag highlight; normal look handled by QSS
_THUMB_DRAG = f"border: 2px solid {_ACCENT};"  # drag-over accent border only


# ── FolderDropZone ────────────────────────────────────────────────────────────


class FolderDropZone(QFrame):
    """Path line-edit + Browse button; also accepts drag-and-drop.

    When *accept_m4b* is ``True`` (the default in the main window) the
    widget also accepts ``.m4b`` files as well as folders so the user
    can drag an existing audiobook in for chapter editing.
    """

    folder_changed = Signal(object)  # Path (folder or .m4b file)
    folder_cleared = Signal()

    def __init__(
        self, parent: Optional[QWidget] = None, *, accept_m4b: bool = False
    ) -> None:
        super().__init__(parent)
        self._accept_m4b = accept_m4b
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self._edit = QLineEdit()
        placeholder = (
            "Drag a folder or .m4b file here, or click Browse…"
            if self._accept_m4b
            else "Drag a folder here or click Browse…"
        )
        self._edit.setPlaceholderText(placeholder)
        self._edit.setReadOnly(True)
        layout.addWidget(self._edit)

        self._clear_btn = QPushButton("✕")
        self._clear_btn.setFixedSize(26, 26)
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.setToolTip("Clear")
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        layout.addWidget(self._clear_btn)

        btn = QPushButton("Browse")
        btn.setFixedWidth(80)
        btn.setFixedHeight(34)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    # ── public interface ──────────────────────────────────────────────────────

    def path(self) -> Optional[Path]:
        t = self._edit.text().strip()
        return Path(t) if t else None

    def set_path(self, p: Path) -> None:
        self._edit.setText(str(p))
        self._clear_btn.setVisible(True)
        self.folder_changed.emit(p)

    # ── actions ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Audiobook Folder")
        if folder:
            self.set_path(Path(folder))

    def _on_clear_clicked(self) -> None:
        self._edit.setText("")
        self._clear_btn.setVisible(False)
        self.folder_cleared.emit()

    # ── drag-and-drop ─────────────────────────────────────────────────────────

    def _is_accepted(self, p: Path) -> bool:
        return p.is_dir() or (self._accept_m4b and p.suffix.lower() == ".m4b")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and self._is_accepted(Path(urls[0].toLocalFile())):
                self._edit.setStyleSheet(f"QLineEdit {{ border-color: {_ACCENT}; }}")
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._edit.setStyleSheet("")

    def dropEvent(self, event: QDropEvent) -> None:
        self._edit.setStyleSheet("")
        urls = event.mimeData().urls()
        if urls:
            p = Path(urls[0].toLocalFile())
            if self._is_accepted(p):
                self.set_path(p)
        event.acceptProposedAction()


# ── CoverWidget ───────────────────────────────────────────────────────────────


class CoverWidget(QFrame):
    """100×100 thumbnail + ‘Choose…’ + ‘URL…’ buttons; accepts image drag-and-drop."""

    cover_changed = Signal(object)  # Path

    _SIZE = 200
    _EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._cover_path: Optional[Path] = None
        self._build()

    def _build(self) -> None:
        self.setObjectName("coverWidget")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._thumb = QLabel()
        self._thumb.setObjectName("coverThumb")
        self._thumb.setFixedSize(self._SIZE, self._SIZE)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setText("Cover")
        layout.addWidget(self._thumb)

        btn_width = self._SIZE
        btn = QPushButton("Choose…")
        btn.setFixedWidth(btn_width)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

        url_btn = QPushButton("URL…")
        url_btn.setFixedWidth(btn_width)
        url_btn.setToolTip("Set cover art from a web URL")
        url_btn.clicked.connect(self._browse_url)
        layout.addWidget(url_btn)

    # ── public interface ──────────────────────────────────────────────────────

    def set_cover(self, path: Optional[Path]) -> None:
        self._cover_path = path
        if path and path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                inner = self._SIZE - 2  # 1px border on each side
                self._thumb.setPixmap(
                    pix.scaled(
                        inner,
                        inner,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._thumb.setText("")
                return
        self._thumb.setPixmap(QPixmap())
        self._thumb.setText("Cover")

    def cover_path(self) -> Optional[Path]:
        return self._cover_path

    # ── actions ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Cover Image",
            "",
            "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp)",
        )
        if path:
            self._set_and_emit(Path(path))

    def _browse_url(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        url, ok = QInputDialog.getText(
            self,
            "Cover Art URL",
            "Enter image URL:",
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self, "Invalid URL", "Please enter an http:// or https:// URL."
            )
            return
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "m4bmaker/1.0"})
            with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310
                data = response.read()
            suffix = Path(url.split("?")[0]).suffix.lower() or ".jpg"
            if suffix not in self._EXTS:
                suffix = ".jpg"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(data)
            tmp.close()
            self._set_and_emit(Path(tmp.name))
        except urllib.error.URLError as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                self, "Download Error", f"Could not download image:\n{exc.reason}"
            )
        except Exception as exc:  # noqa: BLE001
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                self, "Download Error", f"Could not download image:\n{exc}"
            )

    def _set_and_emit(self, p: Path) -> None:
        self.set_cover(p)
        self.cover_changed.emit(p)

    # ── drag-and-drop ─────────────────────────────────────────────────────────

    def _is_image_url(self, urls: list[Any]) -> bool:
        return bool(urls) and Path(urls[0].toLocalFile()).suffix.lower() in self._EXTS

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._is_image_url(
            list(event.mimeData().urls())
        ):
            self._thumb.setStyleSheet(_THUMB_DRAG)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._thumb.setStyleSheet(_THUMB_BASE)

    def dropEvent(self, event: QDropEvent) -> None:
        self._thumb.setStyleSheet(_THUMB_BASE)
        urls = list(event.mimeData().urls())
        if self._is_image_url(urls):
            self._set_and_emit(Path(urls[0].toLocalFile()))
        event.acceptProposedAction()


# ── Chapter table internals ───────────────────────────────────────────────────


class _TitlesCommand(QUndoCommand):
    """Undo/redo a change to chapter title text (bulk or single cell).

    The change is assumed to be *already applied* when the command is pushed,
    so the first call to redo() is skipped.
    """

    def __init__(  # noqa: E501
        self, table: "ChapterTable", before: list[str], after: list[str]
    ) -> None:
        super().__init__("Edit Titles")
        self._table = table
        self._before = before
        self._after = after
        self._first = True  # change already applied; skip first redo

    def redo(self) -> None:
        if self._first:
            self._first = False
            return
        self._table._apply_titles(self._after)

    def undo(self) -> None:
        self._first = False
        self._table._apply_titles(self._before)


class _TimeCommand(QUndoCommand):
    """Undo/redo a single chapter start-time insertion.

    Likewise assumes the change is already applied on first push.
    """

    def __init__(
        self,
        table: "ChapterTable",
        row: int,
        old_ms: "int | None",
        old_text: str,
        new_ms: int,
    ) -> None:
        super().__init__("Insert Time")
        self._table = table
        self._row = row
        self._old_ms = old_ms
        self._old_text = old_text
        self._new_ms = new_ms
        self._first = True

    def redo(self) -> None:
        if self._first:
            self._first = False
            return
        self._table._do_set_time(self._row, self._new_ms)

    def undo(self) -> None:
        self._first = False
        item = self._table.item(self._row, self._table.COL_TIME)
        if item:
            item.setText(self._old_text)
            item.setData(Qt.ItemDataRole.UserRole, self._old_ms)


class _TitleDelegate(QStyledItemDelegate):
    """Auto-select all text when entering edit mode; records undo snapshots."""

    def __init__(self, table: "ChapterTable") -> None:
        super().__init__(table)
        self._table = table
        self._snapshot_before: list[str] = []

    def createEditor(self, parent, option, index):  # type: ignore[no-untyped-def]  # noqa: E501
        self._snapshot_before = self._table._snapshot_titles()
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, _QLineEdit):
            QTimer.singleShot(0, editor.selectAll)
        return editor

    def setModelData(self, editor, model, index) -> None:  # type: ignore[no-untyped-def]  # noqa: E501
        before = self._snapshot_before
        super().setModelData(editor, model, index)
        after = self._table._snapshot_titles()
        if before != after:
            self._table._undo_stack.push(_TitlesCommand(self._table, before, after))


# ── ChapterTable ──────────────────────────────────────────────────────────────


class ChapterTable(QTableWidget):
    """Flat editable chapter table: # | Time | Title.

    Keyboard behaviour
    ------------------
    Enter          commit edit, move to next row
    Shift+Enter    commit edit, move to previous row
    Tab            move to next row (stays on Title column)
    Shift+Tab      move to previous row
    Any printable  begins editing current cell (title column)

    Right-click context menu provides bulk editing tools.
    """

    COL_NUM, COL_TIME, COL_TITLE = 0, 1, 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(0, 3, parent)
        self._undo_stack = QUndoStack(self)
        self._setup()

    def _setup(self) -> None:
        self.setHorizontalHeaderLabels(["#", "Time", "Title"])
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(self.COL_NUM, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self.COL_TIME, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(self.COL_NUM, 48)
        self.setColumnWidth(self.COL_TIME, 76)

        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.setItemDelegateForColumn(self.COL_TITLE, _TitleDelegate(self))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo_sc.activated.connect(self._undo_stack.undo)

    # ── public interface ──────────────────────────────────────────────────────

    def populate(self, chapters: list[Any]) -> None:
        """Replace table contents with *chapters*."""
        self._undo_stack.clear()
        self.setRowCount(0)
        for ch in chapters:
            row = self.rowCount()
            self.insertRow(row)

            # Column 0 — chapter number (read-only)
            n = QTableWidgetItem(str(ch.index))
            n.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            n.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            n.setForeground(QColor(_INK_MUTED))
            self.setItem(row, self.COL_NUM, n)

            # Column 1 — start time (read-only)
            t = ch.start_time
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            ti = QTableWidgetItem(ts)
            ti.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            ti.setForeground(QColor(_INK_MUTED))
            ti.setData(Qt.ItemDataRole.UserRole, None)  # None = unmodified
            self.setItem(row, self.COL_TIME, ti)

            # Column 2 — title (editable)
            title_item = QTableWidgetItem(ch.title)
            title_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            self.setItem(row, self.COL_TITLE, title_item)

    def titles(self) -> list[str]:
        """Return the current title string for every row."""
        result = []
        for r in range(self.rowCount()):
            item = self.item(r, self.COL_TITLE)
            if item:
                result.append(item.text())
        return result

    def times_ms(self) -> list[int | None]:
        """Return overridden start times in ms, or None if unmodified."""
        result = []
        for r in range(self.rowCount()):
            item = self.item(r, self.COL_TIME)
            result.append(item.data(Qt.ItemDataRole.UserRole) if item else None)
        return result

    def set_chapter_time(self, row: int, ms: int) -> None:
        """Update the chapter start time display and store the ms value (undoable)."""
        if row < 0 or row >= self.rowCount():
            return
        item = self.item(row, self.COL_TIME)
        if not item:
            return
        old_ms = item.data(Qt.ItemDataRole.UserRole)
        old_text = item.text()
        self._do_set_time(row, ms)
        self._undo_stack.push(_TimeCommand(self, row, old_ms, old_text, ms))

    def _do_set_time(self, row: int, ms: int) -> None:
        """Apply a time change without pushing to the undo stack."""
        t = ms / 1000.0
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        item = self.item(row, self.COL_TIME)
        if item:
            item.setText(ts)
            item.setData(Qt.ItemDataRole.UserRole, ms)

    def _snapshot_titles(self) -> list[str]:
        """Return current title text for every row."""
        return [
            (
                self.item(r, self.COL_TITLE).text()
                if self.item(r, self.COL_TITLE)
                else ""
            )
            for r in range(self.rowCount())
        ]

    def _apply_titles(self, titles: list[str]) -> None:
        """Restore title text for every row without touching the undo stack."""
        for r, text in enumerate(titles):
            item = self.item(r, self.COL_TITLE)
            if item:
                item.setText(text)

    # ── keyboard navigation ───────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            row = self.currentRow()
            super().keyPressEvent(event)  # commits edit
            new_row = max(0, row - 1) if shift else min(self.rowCount() - 1, row + 1)
            self.setCurrentCell(new_row, self.COL_TITLE)
            return

        if key == Qt.Key.Key_Tab:
            event.accept()
            self.setCurrentCell(
                min(self.rowCount() - 1, self.currentRow() + 1), self.COL_TITLE
            )
            return

        if key == Qt.Key.Key_Backtab:
            event.accept()
            self.setCurrentCell(max(0, self.currentRow() - 1), self.COL_TITLE)
            return

        super().keyPressEvent(event)

    # ── context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Find / Replace…", self._find_replace)
        menu.addSeparator()
        menu.addAction("Remove Numeric Prefixes", self._remove_numeric)
        menu.addAction("Add Sequential Numeric Prefix", self._add_sequential_prefix)
        menu.addAction("Add Prefix…", self._add_prefix)
        menu.addAction("Add Suffix…", self._add_suffix)
        menu.addSeparator()
        menu.addAction("Title Case", self._title_case)
        menu.addAction("Sentence Case", self._sentence_case)
        menu.exec(self.mapToGlobal(pos))

    def _selected_rows(self) -> list[int]:
        """Selected rows, or all rows if nothing is selected."""
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return rows if rows else list(range(self.rowCount()))

    def _find_replace(self) -> None:  # noqa: C901
        dlg = FindReplaceDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            find, replace, case_sensitive = dlg.values()
            if not find:
                return
            before = self._snapshot_titles()
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                for row in self._selected_rows():
                    item = self.item(row, self.COL_TITLE)
                    if item:
                        item.setText(re.sub(find, replace, item.text(), flags=flags))
            except re.error:
                # Plain-string fallback if pattern is invalid regex
                repl_flags = 0 if case_sensitive else re.IGNORECASE
                for row in self._selected_rows():
                    item = self.item(row, self.COL_TITLE)
                    if item:
                        old = item.text()
                        if not case_sensitive:
                            new = re.sub(
                                re.escape(find), replace, old, flags=repl_flags
                            )
                        else:
                            new = old.replace(find, replace)
                        item.setText(new)
            after = self._snapshot_titles()
            if before != after:
                self._undo_stack.push(_TitlesCommand(self, before, after))

    def _remove_numeric(self) -> None:
        before = self._snapshot_titles()
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText(
                    re.sub(r"^\d+[\s.\-\u2013\u2014:]+", "", item.text()).strip()
                )
        after = self._snapshot_titles()
        if before != after:
            self._undo_stack.push(_TitlesCommand(self, before, after))

    def _add_sequential_prefix(self) -> None:
        before = self._snapshot_titles()
        rows = self._selected_rows()
        for seq, row in enumerate(rows, start=1):
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText(f"{seq}. {item.text()}")
        after = self._snapshot_titles()
        if before != after:
            self._undo_stack.push(_TitlesCommand(self, before, after))

    def _add_prefix(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Prefix", "Prefix to add:")
        if ok and text:
            before = self._snapshot_titles()
            for row in self._selected_rows():
                item = self.item(row, self.COL_TITLE)
                if item:
                    item.setText(text + item.text())
            after = self._snapshot_titles()
            if before != after:
                self._undo_stack.push(_TitlesCommand(self, before, after))

    def _add_suffix(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Suffix", "Suffix to add:")
        if ok and text:
            before = self._snapshot_titles()
            for row in self._selected_rows():
                item = self.item(row, self.COL_TITLE)
                if item:
                    item.setText(item.text() + text)
            after = self._snapshot_titles()
            if before != after:
                self._undo_stack.push(_TitlesCommand(self, before, after))

    def _title_case(self) -> None:
        before = self._snapshot_titles()
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText(item.text().title())
        after = self._snapshot_titles()
        if before != after:
            self._undo_stack.push(_TitlesCommand(self, before, after))

    def _sentence_case(self) -> None:
        before = self._snapshot_titles()
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                t = item.text()
                item.setText(t[:1].upper() + t[1:].lower() if t else t)
        after = self._snapshot_titles()
        if before != after:
            self._undo_stack.push(_TitlesCommand(self, before, after))


# ── FindReplaceDialog ─────────────────────────────────────────────────────────


class FindReplaceDialog(QDialog):
    """Minimal find / replace dialog used by ChapterTable."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find / Replace")
        self.setMinimumWidth(340)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)
        self._find_edit = QLineEdit()
        self._replace_edit = QLineEdit()
        form.addRow("Find:", self._find_edit)
        form.addRow("Replace:", self._replace_edit)
        layout.addLayout(form)

        self._case_box = QCheckBox("Case sensitive")
        layout.addWidget(self._case_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, bool]:
        return (
            self._find_edit.text(),
            self._replace_edit.text(),
            self._case_box.isChecked(),
        )
