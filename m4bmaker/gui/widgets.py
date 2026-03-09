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
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QPixmap
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

_THUMB_BASE = (
    f"background-color: {_GROUND_WARM};"
    f"border: 1px solid {_RULE};"
    "border-radius: 3px;"
    f"color: {_INK_MUTED};"
    "font-size: 11px;"
)
_THUMB_DRAG = (
    f"background-color: {_GROUND_WARM};"
    f"border: 1px solid {_ACCENT};"
    "border-radius: 3px;"
    f"color: {_INK_MUTED};"
    "font-size: 11px;"
)


# ── FolderDropZone ────────────────────────────────────────────────────────────


class FolderDropZone(QFrame):
    """Path line-edit + Browse button; also accepts drag-and-drop folders."""

    folder_changed = Signal(object)  # Path

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Drag a folder here or click Browse…")
        self._edit.setReadOnly(True)
        layout.addWidget(self._edit)

        btn = QPushButton("Browse")
        btn.setFixedWidth(80)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    # ── public interface ──────────────────────────────────────────────────────

    def path(self) -> Optional[Path]:
        t = self._edit.text().strip()
        return Path(t) if t else None

    def set_path(self, p: Path) -> None:
        self._edit.setText(str(p))
        self.folder_changed.emit(p)

    # ── actions ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Audiobook Folder")
        if folder:
            self.set_path(Path(folder))

    # ── drag-and-drop ─────────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and Path(urls[0].toLocalFile()).is_dir():
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
            if p.is_dir():
                self.set_path(p)
        event.acceptProposedAction()


# ── CoverWidget ───────────────────────────────────────────────────────────────


class CoverWidget(QFrame):
    """80×80 thumbnail + 'Choose…' button; accepts image drag-and-drop."""

    cover_changed = Signal(object)  # Path

    _SIZE = 80
    _EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._cover_path: Optional[Path] = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._thumb = QLabel()
        self._thumb.setFixedSize(self._SIZE, self._SIZE)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(_THUMB_BASE)
        self._thumb.setText("Cover")
        layout.addWidget(self._thumb)

        btn = QPushButton("Choose…")
        btn.setFixedWidth(self._SIZE)
        btn.setFixedHeight(26)
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

    # ── public interface ──────────────────────────────────────────────────────

    def set_cover(self, path: Optional[Path]) -> None:
        self._cover_path = path
        if path and path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                self._thumb.setPixmap(
                    pix.scaled(
                        self._SIZE,
                        self._SIZE,
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


class _TitleDelegate(QStyledItemDelegate):
    """Auto-select all text when entering edit mode."""

    def createEditor(self, parent, option, index):  # type: ignore[no-untyped-def]  # noqa: E501
        editor = super().createEditor(parent, option, index)
        if editor is not None and hasattr(editor, "selectAll"):
            QTimer.singleShot(0, editor.selectAll)
        return editor


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

    # ── public interface ──────────────────────────────────────────────────────

    def populate(self, chapters: list[Any]) -> None:
        """Replace table contents with *chapters*."""
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

    def _remove_numeric(self) -> None:
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText(
                    re.sub(r"^\d+[\s.\-\u2013\u2014:]+", "", item.text()).strip()
                )

    def _add_prefix(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Prefix", "Prefix to add:")
        if ok and text:
            for row in self._selected_rows():
                item = self.item(row, self.COL_TITLE)
                if item:
                    item.setText(text + item.text())

    def _add_suffix(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Suffix", "Suffix to add:")
        if ok and text:
            for row in self._selected_rows():
                item = self.item(row, self.COL_TITLE)
                if item:
                    item.setText(item.text() + text)

    def _title_case(self) -> None:
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText(item.text().title())

    def _sentence_case(self) -> None:
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                t = item.text()
                item.setText(t[:1].upper() + t[1:].lower() if t else t)


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
