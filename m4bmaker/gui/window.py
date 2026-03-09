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

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
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

from m4bmaker.models import Book, Chapter, PipelineResult
from m4bmaker.gui.player import AudioPlayerWidget
from m4bmaker.gui.widgets import ChapterTable, CoverWidget, FolderDropZone
from m4bmaker.gui.worker import (
    ConvertWorker,
    LoadM4bWorker,
    LoadWorker,
    PreflightWorker,
    SaveChaptersWorker,
)
from m4bmaker.preflight import format_preflight_summary

_BITRATES = ["32k", "48k", "64k", "96k", "128k", "192k", "256k", "320k"]
_DEFAULT_BITRATE = "96k"
_DONATE_URL = "https://buymeacoffee.com/sageframe"
_GITHUB_URL = "https://github.com/sageframe-no-kaji"


def _muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #7a7a7a; font-size: 12px; background: transparent;")
    return lbl


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("m4bmaker")
        self.setMinimumSize(QSize(700, 560))
        self.resize(960, 760)

        self._book: Optional[Book] = None
        self._mode: str = "build"  # "build" or "edit"
        self._m4b_total_duration: float = 0.0
        self._load_worker: Optional[LoadWorker] = None
        self._m4b_load_worker: Optional[LoadM4bWorker] = None
        self._convert_worker: Optional[ConvertWorker] = None
        self._preflight_worker: Optional[PreflightWorker] = None
        self._save_worker: Optional[SaveChaptersWorker] = None
        self._extra_windows: list["MainWindow"] = []

        self._build_menu_bar()
        self._build_ui()

    # ── Menu bar ──────────────────────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        # File menu
        file_menu = mb.addMenu("File")

        new_action = QAction("New Window", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_window)
        file_menu.addAction(new_action)

        open_action = QAction("Open Folder\u2026", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(lambda: self._folder_zone._browse())
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        quit_action = QAction("Quit m4bmaker", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = mb.addMenu("Help")

        about_action = QAction("About m4bmaker", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        donate_action = QAction("♥  Buy Me a Coffee…", self)
        donate_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_DONATE_URL))
        )
        help_menu.addAction(donate_action)

        github_action = QAction("  GitHub…", self)
        github_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_URL))
        )
        help_menu.addAction(github_action)

    def _new_window(self) -> None:
        win = MainWindow()
        win.show()
        self._extra_windows.append(win)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About m4bmaker",
            "<b>m4bmaker</b><br>"
            "Convert audio files to M4B audiobooks.<br><br>"
            "Uses ffmpeg for encoding and chapter metadata.<br><br>"
            f'<a href="{_GITHUB_URL}"> GitHub</a> &nbsp;&nbsp; '
            f'<a href="{_DONATE_URL}">♥ Buy Me a Coffee</a>',
        )

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

        self._folder_zone = FolderDropZone(accept_m4b=True)
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
        layout.addWidget(self._build_analysis_section())
        layout.addWidget(self._build_encoding_section())
        layout.addWidget(self._build_output_section())
        layout.addStretch()
        return tab

    def _build_analysis_section(self) -> QGroupBox:
        box = QGroupBox("Audio Analysis")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 14, 10, 10)

        self._analysis_label = QLabel("No analysis yet.")
        self._analysis_label.setWordWrap(True)
        layout.addWidget(self._analysis_label)

        self._analysis_box = box
        box.setVisible(False)
        return box

    def _build_meta_section(self) -> QGroupBox:
        box = QGroupBox("Audiobook")
        hbox = QHBoxLayout(box)
        hbox.setContentsMargins(10, 16, 10, 12)
        hbox.setSpacing(16)

        # Left — cover thumbnail
        self._cover_widget = CoverWidget()
        self._cover_widget.cover_changed.connect(self._on_cover_changed)
        hbox.addWidget(self._cover_widget, 0, Qt.AlignmentFlag.AlignTop)

        # Right — metadata (QGridLayout forces left-aligned labels on macOS)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(10)
        grid.setColumnStretch(1, 1)

        self._title_edit = QLineEdit()
        self._author_edit = QLineEdit()
        self._narrator_edit = QLineEdit()
        self._genre_edit = QLineEdit()

        for i, (label_text, widget) in enumerate((
            ("Title", self._title_edit),
            ("Author", self._author_edit),
            ("Narrator", self._narrator_edit),
            ("Genre", self._genre_edit),
        )):
            lbl = _muted_label(label_text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(widget, i, 1)
            widget.textChanged.connect(self._update_output_preview)

        hbox.addLayout(grid, stretch=1)
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
        self._chapter_table.currentCellChanged.connect(self._on_chapter_selected)
        layout.addWidget(self._chapter_table, stretch=1)

        hint = QLabel(
            "Double-click or press a key to edit a title  ·  "
            "Enter = next row  ·  Shift+Enter = previous row  ·  "
            "Right-click for bulk tools"
        )
        hint.setStyleSheet("color: #7a7a7a; font-size: 11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self._player = AudioPlayerWidget()
        layout.addWidget(self._player)
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

        donate_lbl = QLabel(
            f'<a href="{_DONATE_URL}" style="color: #c45a2d; text-decoration: none;">'
            "\u2665 Support</a>"
        )
        donate_lbl.setOpenExternalLinks(True)
        donate_lbl.setStyleSheet("font-size: 11px; background: transparent;")
        donate_lbl.setToolTip("Support m4bmaker development")
        btn_row.addWidget(donate_lbl)

        layout.addLayout(btn_row)

        return layout

    # ── Helpers ───────────────────────────────────────────────────────────────

    # ── Close-while-running guard (Feature 5) ────────────────────────────────

    def _is_busy(self) -> bool:
        return (
            self._convert_worker is not None and self._convert_worker.isRunning()
        ) or (
            self._save_worker is not None and self._save_worker.isRunning()
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._is_busy():
            reply = QMessageBox.question(
                self,
                "Cancel Conversion?",
                "A conversion is in progress.\nAre you sure you want to quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        super().closeEvent(event)

    def _update_controls(self) -> None:
        has_book = self._book is not None
        busy = self._convert_worker is not None and self._convert_worker.isRunning()
        save_busy = self._save_worker is not None and self._save_worker.isRunning()
        self._convert_btn.setEnabled(has_book and not busy and not save_busy)
        self._tabs.setTabEnabled(1, has_book)
        if self._mode == "edit":
            self._convert_btn.setText("Save Chapter Edits")
            self._build_encoding_section_visibility(False)
        else:
            self._convert_btn.setText("Convert to M4B")
            self._build_encoding_section_visibility(True)

    def _build_encoding_section_visibility(self, visible: bool) -> None:
        # Find encoding and output group boxes by iterating the build tab layout
        build_tab = self._tabs.widget(0)
        if build_tab is None:
            return
        layout = build_tab.layout()
        if layout is None:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, QGroupBox) and w.title() in (
                "Encoding",
                "Output Location",
            ):
                w.setVisible(visible)

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
        self._analysis_box.setVisible(False)
        self._player.stop()
        self._update_controls()
        self._status_label.setText("Scanning…")
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)  # indeterminate spinner

        if p.is_dir():
            self._mode = "build"
            self._load_worker = LoadWorker(p)
            self._load_worker.finished.connect(self._on_load_finished)
            self._load_worker.error.connect(self._on_load_error)
            self._load_worker.start()
        else:
            self._mode = "edit"
            self._m4b_load_worker = LoadM4bWorker(p)
            self._m4b_load_worker.finished.connect(self._on_m4b_loaded)
            self._m4b_load_worker.error.connect(self._on_load_error)
            self._m4b_load_worker.start()

    def _on_load_finished(self, book: Book) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._apply_book_to_ui(book)
        # Start preflight analysis in the background
        self._preflight_worker = PreflightWorker(book.files)
        self._preflight_worker.finished.connect(self._on_preflight_finished)
        self._preflight_worker.start()

    def _on_m4b_loaded(self, payload: object) -> None:
        book, total_duration = payload  # type: ignore[misc]
        self._m4b_total_duration = total_duration
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._apply_book_to_ui(book)

    def _on_preflight_finished(self, analysis: object) -> None:
        summary = format_preflight_summary(analysis)  # type: ignore[arg-type]
        self._analysis_label.setText(summary)
        self._analysis_box.setVisible(True)

    def _on_chapter_selected(
        self, row: int, _col: int, _prev_row: int, _prev_col: int
    ) -> None:
        if self._book is None or row < 0 or row >= len(self._book.chapters):
            return
        ch = self._book.chapters[row]
        start_ms = int(ch.start_time * 1000)
        # In edit mode the source is the .m4b itself; in build mode each chapter
        # carries its own source_file.
        if self._mode == "edit" and self._folder_zone.path() is not None:
            src = self._folder_zone.path()
        else:
            src = ch.source_file
        if src is not None:
            if self._player.is_playing:
                # Already playing — seek to the new chapter without restarting
                self._player.load(src, start_ms)
            else:
                # Not playing — load and position but stay paused
                self._player.load_paused(src, start_ms)

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

        if self._mode == "edit":
            self._do_save_chapters()
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

    def _do_save_chapters(self) -> None:
        source = self._folder_zone.path()
        if source is None:
            return
        chapters = self._gather_chapters_from_table()
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)
        self._status_label.setText("Saving chapter edits…")
        self._convert_btn.setEnabled(False)

        self._save_worker = SaveChaptersWorker(
            source=source,
            chapters=chapters,
            total_duration=self._m4b_total_duration,
            dest=source,  # in-place edit
        )
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.error.connect(self._on_convert_error)
        self._save_worker.start()

    def _gather_chapters_from_table(self) -> list[Chapter]:
        assert self._book is not None
        from copy import deepcopy

        chapters = deepcopy(self._book.chapters)
        for ch, new_title in zip(chapters, self._chapter_table.titles()):
            ch.title = new_title
        return chapters

    def _on_save_finished(self, dest: object) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._status_label.setText(f"Saved — {Path(str(dest)).name}")
        self._update_controls()
        msg = QMessageBox(self)
        msg.setWindowTitle("Saved")
        msg.setIcon(QMessageBox.Icon.NoIcon)
        mins = self._m4b_total_duration / 60
        msg.setText(
            f"✅ Chapter metadata saved\n\n"
            f"{Path(str(dest)).name}\n\n"
            f"{len(self._book.chapters) if self._book else 0} chapter(s)  ·  {mins:.1f} min"
        )
        msg.exec()

    def _on_progress(self, msg: str, fraction: float) -> None:
        self._status_label.setText(msg)
        self._progress_bar.setValue(int(fraction * 100))

    def _on_convert_finished(self, result: PipelineResult) -> None:
        self._progress_bar.setValue(100)
        self._status_label.setText(f"Done — {result.output_file.name}")
        self._update_controls()
        mins = result.duration_seconds / 60
        msg = QMessageBox(self)
        msg.setWindowTitle("Saved")
        msg.setIcon(QMessageBox.Icon.NoIcon)
        msg.setText(
            f"✅ Audiobook saved\n\n"
            f"{result.output_file}\n\n"
            f"{result.chapter_count} chapter(s)  ·  {mins:.1f} min"
        )
        msg.exec()

    def _on_convert_error(self, msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._status_label.setText("Conversion failed.")
        self._update_controls()
        QMessageBox.critical(self, "Conversion Error", msg)
