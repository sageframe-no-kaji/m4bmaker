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

from PySide6.QtCore import QProcess, Qt, QPoint, QThread, QTimer, Signal
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
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from m4bmaker.cover import download_cover
from m4bmaker.errors import M4BError
from m4bmaker.utils import get_temp_root

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
        self._m4b_picker_proc: Optional[QProcess] = None
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self._edit = QLineEdit()
        placeholder = (
            "Drag a folder or .m4b file here"
            "  \u00b7  Build\u2026 for new  \u00b7  Edit\u2026 for existing"
            if self._accept_m4b
            else "Drag a folder here or click Build\u2026"
        )
        self._edit.setPlaceholderText(placeholder)
        self._edit.setReadOnly(True)
        layout.addWidget(self._edit)

        self._clear_btn = QPushButton("\u2715")
        self._clear_btn.setFixedSize(26, 26)
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.setToolTip("Clear")
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        layout.addWidget(self._clear_btn)

        btn = QPushButton("Build\u2026")
        btn.setFixedWidth(80)
        btn.setFixedHeight(34)
        btn.setToolTip("Choose a folder of audio files to build a new M4B")
        btn.clicked.connect(self._browse)
        layout.addWidget(btn)

        if self._accept_m4b:
            m4b_btn = QPushButton("Edit\u2026")
            m4b_btn.setFixedWidth(80)
            m4b_btn.setFixedHeight(34)
            m4b_btn.setToolTip("Choose an existing .m4b file to edit its chapters")
            m4b_btn.clicked.connect(self._browse_m4b)
            layout.addWidget(m4b_btn)

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
        folder = QFileDialog.getExistingDirectory(
            self, "Select Audiobook Folder to Build"
        )
        if folder:
            self.set_path(Path(folder))

    def _browse_m4b(self) -> None:
        """Open a native file picker for .m4b files.

        On macOS: uses osascript (AppleScript ``choose file``) to open the
        real NSOpenPanel with no type filter — avoids the UTI grey-out issue.
        Runs via an async QProcess (M3): a blocking ``subprocess.run`` here
        would freeze the whole event loop for as long as the panel is open,
        and there is no reason to bound how long the user takes to pick.
        On other platforms: falls back to QFileDialog with DontUseNativeDialog.
        """
        import sys as _sys

        if _sys.platform == "darwin":
            self._browse_m4b_macos()
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Edit M4B Chapters",
                "",
                "M4B Audiobooks (*.m4b);;All Files (*)",
                "",
                QFileDialog.Option.DontUseNativeDialog,
            )
            self._handle_m4b_path(path)

    def _handle_m4b_path(self, path: str) -> None:
        """Apply a picked path (from either backend) — shared result handling."""
        if path and path.lower().endswith(".m4b"):
            self.set_path(Path(path))
        elif path:
            QMessageBox.warning(
                self,
                "Not an M4B",
                f"'{Path(path).name}' is not an .m4b file.",
            )

    def _browse_m4b_macos(self) -> None:
        """Start AppleScript ``choose file`` asynchronously via QProcess.

        No timeout — the panel can legitimately stay open indefinitely
        while the user browses; killing it after a fixed window would
        silently discard a real selection.  On any QProcess start error
        (osascript missing, etc.) falls back to QFileDialog.
        """
        script = (
            'set theFile to choose file with prompt "Select an M4B audiobook"\n'
            "return POSIX path of theFile"
        )
        proc = QProcess(self)
        self._m4b_picker_proc = proc
        proc.finished.connect(self._on_m4b_picker_finished)
        proc.errorOccurred.connect(self._on_m4b_picker_error)
        proc.start("osascript", ["-e", script])

    def _on_m4b_picker_finished(
        self, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        proc = self._m4b_picker_proc
        self._m4b_picker_proc = None
        if proc is None:
            return
        path = ""
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            raw: bytes = bytes(proc.readAllStandardOutput().data())
            path = raw.decode("utf-8").strip()
        # A non-zero exit means the user cancelled the panel — no path, no error.
        self._handle_m4b_path(path)

    def _on_m4b_picker_error(self, _error: QProcess.ProcessError) -> None:
        """osascript failed to start — fall back to the Qt dialog."""
        self._m4b_picker_proc = None
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Edit M4B Chapters",
            "",
            "M4B Audiobooks (*.m4b);;All Files (*)",
            "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        self._handle_m4b_path(path)

    def _on_clear_clicked(self) -> None:
        self._edit.setText("")
        self._clear_btn.setVisible(False)
        self.folder_cleared.emit()

    # ── drag-and-drop ─────────────────────────────────────────────────────────

    def _is_accepted(self, p: Path) -> bool:
        if self._accept_m4b and p.suffix.lower() == ".m4b":
            return True
        try:
            return p.is_dir()
        except OSError:
            # L7: a dead network mount can hang/fail stat() during a drag
            # hover — treat it as not-accepted rather than propagating.
            return False

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


# ── cover URL download worker ────────────────────────────────────────────────


class _CoverDownloadWorker(QThread):
    """Download a cover image off the UI thread.

    Delegates to :func:`m4bmaker.cover.download_cover`, which enforces
    https-only, a content-type check, and a size cap, and writes under the
    process-lifetime managed temp root (cleaned at exit) rather than a
    leaked :class:`~tempfile.NamedTemporaryFile`.
    """

    result_ready = Signal(object)  # Path
    error = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            import tempfile as _tempfile

            dest_dir = Path(
                _tempfile.mkdtemp(prefix="m4bmaker_cover_url_", dir=get_temp_root())
            )
            path = download_cover(self._url, dest_dir)
            self.result_ready.emit(path)
        except M4BError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


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
        self._download_worker: Optional[_CoverDownloadWorker] = None
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

        self._url_btn = QPushButton("URL…")
        self._url_btn.setFixedWidth(btn_width)
        self._url_btn.setToolTip("Set cover art from a web URL")
        self._url_btn.clicked.connect(self._browse_url)
        layout.addWidget(self._url_btn)

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
        """Prompt for a cover URL and download it off the UI thread (M4).

        The download itself runs in :class:`_CoverDownloadWorker`, which
        delegates to :func:`m4bmaker.cover.download_cover` (https-only,
        content-type checked, size-capped, written under the managed temp
        root). The URL button is disabled for the duration so a second
        click cannot start an overlapping download.
        """
        url, ok = QInputDialog.getText(
            self,
            "Cover Art URL",
            "Enter image URL:",
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.lower().startswith("https://"):
            QMessageBox.warning(self, "Invalid URL", "Please enter an https:// URL.")
            return

        self._url_btn.setEnabled(False)
        self._download_worker = _CoverDownloadWorker(url)
        self._download_worker.result_ready.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.start()

    def _on_download_finished(self, path: object) -> None:
        self._url_btn.setEnabled(True)
        self._set_and_emit(Path(str(path)))

    def _on_download_error(self, msg: str) -> None:
        self._url_btn.setEnabled(True)
        if self.isVisible():
            QMessageBox.critical(
                self, "Download Error", f"Could not download image:\n{msg}"
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


class _TimeDelegate(QStyledItemDelegate):
    """Delegate for the Time column.

    Parses ``[H:]M:SS[.mmm]`` input on commit.  Invalid input is silently
    discarded and the cell reverts to its previous value without touching
    the undo stack.  Valid input is applied through
    :meth:`ChapterTable.set_chapter_time` so it participates in undo.
    """

    def __init__(self, table: "ChapterTable") -> None:
        super().__init__(table)
        self._table = table

    def createEditor(self, parent, option, index):  # type: ignore[no-untyped-def]  # noqa: E501
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return editor

    def setEditorData(self, editor, index) -> None:  # type: ignore[no-untyped-def]  # noqa: E501
        editor.setText(index.data() or "")
        editor.selectAll()

    def setModelData(self, editor, model, index) -> None:  # type: ignore[no-untyped-def]  # noqa: E501
        ms = _parse_time_input(editor.text())
        if ms is None:
            return  # invalid input — leave the cell unchanged
        self._table.set_chapter_time(index.row(), ms)

    def updateEditorGeometry(self, editor, option, index) -> None:  # type: ignore[no-untyped-def]  # noqa: E501
        editor.setGeometry(option.rect)


# ── ChapterTable helpers ─────────────────────────────────────────────────────


def _ms_to_display(ms: int) -> str:
    """Format *ms* milliseconds as ``M:SS.mmm`` or ``H:MM:SS.mmm``."""
    total_s = ms // 1000
    millis = ms % 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}.{millis:03d}"
    return f"{m}:{s:02d}.{millis:03d}"


def _parse_time_input(text: str) -> "int | None":
    """Parse ``[H:]M:SS[.mmm]`` text to milliseconds, or return *None* if invalid.

    Accepts:
      * ``M:SS``         e.g. ``1:30``
      * ``M:SS.mmm``     e.g. ``1:30.500``
      * ``H:MM:SS``      e.g. ``1:01:30``
      * ``H:MM:SS.mmm``  e.g. ``1:01:30.500``

    Seconds must be in [0, 59].  Milliseconds are 1–3 digits (right-padded).
    """
    text = text.strip()
    m = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?", text)
    if m:
        h, mins, secs, frac = m.groups()
        millis = int(frac.ljust(3, "0")) if frac else 0
        return (int(h) * 3600 + int(mins) * 60 + int(secs)) * 1000 + millis
    m = re.fullmatch(r"(\d+):([0-5]\d)(?:\.(\d{1,3}))?", text)
    if m:
        mins, secs, frac = m.groups()
        millis = int(frac.ljust(3, "0")) if frac else 0
        return (int(mins) * 60 + int(secs)) * 1000 + millis
    return None


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
        self.setColumnWidth(self.COL_TIME, 90)

        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.setItemDelegateForColumn(self.COL_TITLE, _TitleDelegate(self))
        self.setItemDelegateForColumn(self.COL_TIME, _TimeDelegate(self))
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

            # Column 1 — start time (editable via _TimeDelegate)
            ts = _ms_to_display(int(ch.start_time * 1000))
            ti = QTableWidgetItem(ts)
            ti.setFlags(
                Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
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
        ts = _ms_to_display(ms)
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
        menu.addAction('Number as "Chapter X"', self._number_as_chapter)
        menu.addAction("Add Prefix…", self._add_prefix)
        menu.addAction("Add Suffix…", self._add_suffix)
        menu.addSeparator()
        menu.addAction("Title Case", self._title_case)
        menu.addAction("Sentence Case", self._sentence_case)
        menu.addSeparator()
        menu.addAction("Clear Titles", self._clear_titles)
        menu.exec(self.mapToGlobal(pos))

    def _selected_rows(self) -> list[int]:
        """Selected rows, or all rows if nothing is selected."""
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return rows if rows else list(range(self.rowCount()))

    def _find_replace(self) -> None:
        dlg = FindReplaceDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            find, replace, case_sensitive, use_regex = dlg.values()
            if not find:
                return
            before = self._snapshot_titles()
            flags = 0 if case_sensitive else re.IGNORECASE
            if use_regex:
                # L5: regex mode is explicit opt-in — the replacement is a
                # regex template here (backslash refs like \1 are honoured),
                # matching the pre-existing "Find" behaviour.
                try:
                    pattern = re.compile(find, flags)
                except re.error:
                    QMessageBox.warning(
                        self, "Invalid Pattern", f"Not a valid regex: {find!r}"
                    )
                    return
                for row in self._selected_rows():
                    item = self.item(row, self.COL_TITLE)
                    if item:
                        item.setText(pattern.sub(replace, item.text()))
            else:
                # Literal mode (default): match find verbatim and insert
                # replace verbatim too — a callable replacement so re.sub
                # never interprets backslashes/\1 in `replace` as a template.
                pattern = re.compile(re.escape(find), flags)
                for row in self._selected_rows():
                    item = self.item(row, self.COL_TITLE)
                    if item:
                        item.setText(pattern.sub(lambda _m: replace, item.text()))
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

    def _number_as_chapter(self) -> None:
        before = self._snapshot_titles()
        rows = self._selected_rows()
        for seq, row in enumerate(rows, start=1):
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText(f"Chapter {seq}")
        after = self._snapshot_titles()
        if before != after:
            self._undo_stack.push(_TitlesCommand(self, before, after))

    def _clear_titles(self) -> None:
        before = self._snapshot_titles()
        for row in self._selected_rows():
            item = self.item(row, self.COL_TITLE)
            if item:
                item.setText("")
        after = self._snapshot_titles()
        if before != after:
            self._undo_stack.push(_TitlesCommand(self, before, after))


# ── FindReplaceDialog ─────────────────────────────────────────────────────────


class FindReplaceDialog(QDialog):
    """Minimal find / replace dialog used by ChapterTable.

    "Find" matches literally by default (L5) — typing ``1.5`` no longer
    matches ``125`` the way a regex ``.`` wildcard would.  Check "Regex" to
    opt back into pattern matching.
    """

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

        self._regex_box = QCheckBox("Regex")
        self._regex_box.setToolTip(
            "Treat Find as a regular expression\n"
            "(Replace may use \\1, \\2, … back-references)"
        )
        layout.addWidget(self._regex_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, bool, bool]:
        """Return (find, replace, case_sensitive, use_regex)."""
        return (
            self._find_edit.text(),
            self._replace_edit.text(),
            self._case_box.isChecked(),
            self._regex_box.isChecked(),
        )
