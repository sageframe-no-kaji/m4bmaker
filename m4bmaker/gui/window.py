"""Main application window.

Layout
------
┌─ Source ───────────────────────────────────────────────────┐
│  [ /path/to/folder                           ] [ Browse ]  │
└────────────────────────────────────────────────────────────┘
┌─ Build ──────────────────────┬─ Chapters ──────────────────┐
│  ┌─ Audiobook ─────────────┐ │  ┌─ flat table ───────────┐ │
│  │ [cover] Title           │ │  │  # │ Time │ Title      │ │
│  │         Author          │ │  │  …                      │ │
│  │         Narrator        │ │  └────────────────────────┘ │
│  │         Genre           │ │  (Enter / Shift+Enter move) │
│  └─────────────────────────┘ │  (right-click: bulk tools)  │
│  ┌─ Encoding ──────────────┐ │                             │
│  │ Bitrate [96k▾] ○M ●S   │ │                             │
│  └─────────────────────────┘ │                             │
│  ┌─ Output Location ───────┐ │                             │
│  │ ● …/Author/Title/T.m4b │ │                             │
│  │ ○ …/Author - Title.m4b │ │                             │
│  │ ○ Custom [path][Browse] │ │                             │
│  └─────────────────────────┘ │                             │
└──────────────────────────────┴─────────────────────────────┘
[ ▓▓▓░░░░ ]  Scanning…
                    [ Convert to M4B ]
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from m4bmaker.models import Book, PipelineResult
from m4bmaker.gui.widgets import ChapterTable, CoverWidget, FolderDropZone
from m4bmaker.gui.worker import ConvertWorker, LoadWorker

_BITRATES = ["32k", "48k", "64k", "96k", "128k", "192k", "256k", "320k"]
_DEFAULT_BITRATE = "96k"


def _muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #7a7a7a; font-size: 12px; background: transparent;")
    return lbl


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("m4bmaker")
        self.setMinimumSize(QSize(820, 640))
        self.resize(860, 720)

        self._book: Optional[Book] = None
        self._load_worker: Optional[LoadWorker] = None
        self._convert_worker: Optional[ConvertWorker] = None

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        outer.addWidget(self._build_folder_section())
        outer.addWidget(self._build_tabs(), stretch=1)
        outer.addLayout(self._build_bottom_bar())

        self._update_controls()

    # ── Folder section ────────────────────────────────────────────────────────

    def _build_folder_section(self) -> QGroupBox:
        box = QGroupBox("Source")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(0)

        self._folder_zone = FolderDropZone()
        self._folder_zone.folder_changed.connect(self._on_folder_changed)
        layout.addWidget(self._folder_zone)
        return box

    # ── Tab widget ────────────────────────────────────────────────────────────

    def _build_tabs(self) -> QTabWidget:
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_build_tab(), "Build")
        self._tabs.addTab(self._build_chapters_tab(), "Chapters")
        return self._tabs

    # ── Build tab ─────────────────────────────────────────────────────────────

    def _build_build_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_meta_section())
        layout.addWidget(self._build_encoding_section())
        layout.addWidget(self._build_output_section())
        layout.addStretch()
        return tab

    def _build_meta_section(self) -> QGroupBox:
        box = QGroupBox("Audiobook")
        row = QHBoxLayout(box)
        row.setContentsMargins(10, 16, 10, 12)
        row.setSpacing(16)

        # Left — cover thumbnail
        self._cover_widget = CoverWidget()
        self._cover_widget.cover_changed.connect(self._on_cover_changed)
        row.addWidget(self._cover_widget, 0, Qt.AlignmentFlag.AlignTop)

        # Right — metadata form
        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._title_edit = QLineEdit()
        self._author_edit = QLineEdit()
        self._narrator_edit = QLineEdit()
        self._genre_edit = QLineEdit()

        for label, widget in (
            ("Title", self._title_edit),
            ("Author", self._author_edit),
            ("Narrator", self._narrator_edit),
            ("Genre", self._genre_edit),
        ):
            form.addRow(_muted_label(label), widget)
            widget.textChanged.connect(self._update_output_preview)

        row.addLayout(form, stretch=1)
        return box

    def _build_encoding_section(self) -> QGroupBox:
        box = QGroupBox("Encoding")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(14)

        layout.addWidget(_muted_label("Bitrate"))

        self._bitrate_combo = QComboBox()
        self._bitrate_combo.addItems(_BITRATES)
        self._bitrate_combo.setCurrentText(_DEFAULT_BITRATE)
        self._bitrate_combo.setFixedWidth(90)
        layout.addWidget(self._bitrate_combo)

        layout.addSpacing(10)
        layout.addWidget(_muted_label("Channels"))

        self._mono_radio = QRadioButton("Mono")
        self._stereo_radio = QRadioButton("Stereo")
        self._mono_radio.setChecked(True)
        chan_group = QButtonGroup(self)
        chan_group.addButton(self._mono_radio)
        chan_group.addButton(self._stereo_radio)
        layout.addWidget(self._mono_radio)
        layout.addWidget(self._stereo_radio)
        layout.addStretch()
        return box

    def _build_output_section(self) -> QGroupBox:
        box = QGroupBox("Output Location")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 16, 10, 12)
        layout.setSpacing(7)

        self._out_group = QButtonGroup(self)

        self._out_nested = QRadioButton()  # label set dynamically
        self._out_flat = QRadioButton()  # label set dynamically
        self._out_custom = QRadioButton("Custom")
        self._out_nested.setChecked(True)
        self._out_group.addButton(self._out_nested, 0)
        self._out_group.addButton(self._out_flat, 1)
        self._out_group.addButton(self._out_custom, 2)

        layout.addWidget(self._out_nested)
        layout.addWidget(self._out_flat)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)
        custom_row.addWidget(self._out_custom)
        self._custom_path_edit = QLineEdit()
        self._custom_path_edit.setPlaceholderText("Choose output path…")
        self._custom_path_edit.setEnabled(False)
        self._custom_browse_btn = QPushButton("Browse")
        self._custom_browse_btn.setFixedWidth(72)
        self._custom_browse_btn.setEnabled(False)
        self._custom_browse_btn.clicked.connect(self._browse_custom_output)
        custom_row.addWidget(self._custom_path_edit)
        custom_row.addWidget(self._custom_browse_btn)
        layout.addLayout(custom_row)

        self._out_custom.toggled.connect(self._custom_path_edit.setEnabled)
        self._out_custom.toggled.connect(self._custom_browse_btn.setEnabled)
        self._out_group.buttonClicked.connect(lambda _: self._update_output_preview())

        self._update_output_preview()
        return box

    # ── Chapters tab ──────────────────────────────────────────────────────────

    def _build_chapters_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._chapter_table = ChapterTable()
        layout.addWidget(self._chapter_table, stretch=1)

        hint = QLabel(
            "Double-click or press a key to edit a title  ·  "
            "Enter = next row  ·  Shift+Enter = previous row  ·  "
            "Right-click for bulk tools"
        )
        hint.setStyleSheet("color: #7a7a7a; font-size: 11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return tab

    # ── Bottom bar (progress + convert) ──────────────────────────────────────

    def _build_bottom_bar(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(6)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("Select a folder to begin.")
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._convert_btn = QPushButton("Convert to M4B")
        self._convert_btn.setObjectName("convertBtn")
        self._convert_btn.setFixedHeight(44)
        self._convert_btn.setFixedWidth(210)
        self._convert_btn.clicked.connect(self._on_convert)
        btn_row.addStretch()
        btn_row.addWidget(self._convert_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return layout

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_controls(self) -> None:
        has_book = self._book is not None
        busy = self._convert_worker is not None and self._convert_worker.isRunning()
        self._convert_btn.setEnabled(has_book and not busy)
        self._tabs.setTabEnabled(1, has_book)

    def _update_output_preview(self) -> None:
        author = self._author_edit.text().strip() or "Author"
        title = self._title_edit.text().strip() or "Title"
        self._out_nested.setText(f"…/{author}/{title}/{title}.m4b")
        self._out_flat.setText(f"…/{author} – {title}.m4b")

    def _computed_output_path(self) -> Optional[Path]:
        folder = self._folder_zone.path()
        author = self._author_edit.text().strip() or "Unknown Author"
        title = self._title_edit.text().strip() or "Unknown Title"
        base = folder.parent if folder else Path.home()

        choice = self._out_group.checkedId()
        if choice == 0:
            return base / author / title / f"{title}.m4b"
        if choice == 1:
            return base / f"{author} – {title}.m4b"
        # choice == 2 (custom)
        t = self._custom_path_edit.text().strip()
        return Path(t) if t else None

    def _apply_book_to_ui(self, book: Book) -> None:
        self._book = book
        self._title_edit.setText(book.metadata.title)
        self._author_edit.setText(book.metadata.author)
        self._narrator_edit.setText(book.metadata.narrator)
        self._genre_edit.setText(book.metadata.genre)
        self._cover_widget.set_cover(book.cover)
        self._chapter_table.populate(book.chapters)
        self._update_output_preview()
        self._update_controls()
        self._status_label.setText(
            f"Loaded {len(book.files)} file(s) · {len(book.chapters)} chapter(s)."
        )

    def _collect_book_edits(self) -> Book:
        """Deep-copy the book and apply current UI field values."""
        assert self._book is not None
        book = deepcopy(self._book)
        book.metadata.title = self._title_edit.text().strip()
        book.metadata.author = self._author_edit.text().strip()
        book.metadata.narrator = self._narrator_edit.text().strip()
        book.metadata.genre = self._genre_edit.text().strip()
        book.cover = self._cover_widget.cover_path()
        for ch, new_title in zip(book.chapters, self._chapter_table.titles()):
            ch.title = new_title
        return book

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_folder_changed(self, p: Path) -> None:
        self._book = None
        self._update_controls()
        self._status_label.setText("Scanning…")
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)  # indeterminate spinner

        self._load_worker = LoadWorker(p)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_load_finished(self, book: Book) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._apply_book_to_ui(book)

    def _on_load_error(self, msg: str) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setVisible(False)
        self._status_label.setText("Error loading folder.")
        self._update_controls()
        QMessageBox.critical(self, "Load Error", msg)

    def _on_cover_changed(self, p: Path) -> None:
        if self._book:
            self._book.cover = p

    def _browse_custom_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save M4B As", "", "M4B audiobook (*.m4b)"
        )
        if path:
            if not path.lower().endswith(".m4b"):
                path += ".m4b"
            self._custom_path_edit.setText(path)

    def _on_convert(self) -> None:
        if not self._book:
            return
        out = self._computed_output_path()
        if not out:
            QMessageBox.warning(
                self,
                "No Output Path",
                "Please specify a custom output path.",
            )
            return

        book = self._collect_book_edits()
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._status_label.setText("Starting…")
        self._convert_btn.setEnabled(False)

        self._convert_worker = ConvertWorker(
            book=book,
            output_path=out,
            bitrate=self._bitrate_combo.currentText(),
            stereo=self._stereo_radio.isChecked(),
        )
        self._convert_worker.progress.connect(self._on_progress)
        self._convert_worker.finished.connect(self._on_convert_finished)
        self._convert_worker.error.connect(self._on_convert_error)
        self._convert_worker.start()

    def _on_progress(self, msg: str, fraction: float) -> None:
        self._status_label.setText(msg)
        self._progress_bar.setValue(int(fraction * 100))

    def _on_convert_finished(self, result: PipelineResult) -> None:
        self._progress_bar.setValue(100)
        self._status_label.setText(f"Done — {result.output_file.name}")
        self._update_controls()
        mins = result.duration_seconds / 60
        QMessageBox.information(
            self,
            "Done",
            f"Saved to:\n{result.output_file}\n\n"
            f"{result.chapter_count} chapter(s)  ·  {mins:.1f} min",
        )

    def _on_convert_error(self, msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._status_label.setText("Conversion failed.")
        self._update_controls()
        QMessageBox.critical(self, "Conversion Error", msg)
