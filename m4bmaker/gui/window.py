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
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence, QPainter, QPixmap
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
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from m4bmaker.models import Book, Chapter, PipelineResult
from m4bmaker.gui.player import AudioPlayerWidget
from m4bmaker.gui.styles import get_stylesheet
from m4bmaker.gui.widgets import ChapterTable, CoverWidget, FolderDropZone
from m4bmaker.gui.worker import (
    ConvertWorker,
    LoadM4bWorker,
    LoadWorker,
    PreflightWorker,
    SaveChaptersWorker,
)
from m4bmaker.gui.job import job_from_book
from m4bmaker.gui.queue_manager import QueueManager
from m4bmaker.gui.queue_window import QueueWindow
from m4bmaker.preflight import format_preflight_summary
try:
    from PySide6.QtSvg import QSvgRenderer as _QSvgRenderer
    _HAS_SVG = True
except ImportError:
    _HAS_SVG = False

_BITRATES = ["32k", "48k", "64k", "96k", "128k", "192k", "256k", "320k"]
_DEFAULT_BITRATE = "96k"
_DONATE_URL = "https://buymeacoffee.com/sageframe"
_GITHUB_URL = "https://github.com/sageframe-no-kaji"

# Sageframe brand SVG (embedded so the app has no file dependency)
_SAGEFRAME_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 301 301">'
    b'<defs><style>'
    b'.s1{fill:none;stroke:#c45b35;stroke-linecap:square;stroke-miterlimit:10;stroke-width:23px}'
    b'.s2{fill:#eae5dd}</style></defs>'
    b'<circle class="s2" cx="150.5" cy="150.5" r="150.5"/>'
    b'<line class="s1" x1="150.19" y1="52.98" x2="150.19" y2="257.92"/>'
    b'<line class="s1" x1="86.88" y1="106.38" x2="182.15" y2="203.64"/>'
    b'<line class="s1" x1="86.88" y1="236.27" x2="150.19" y2="172.97"/>'
    b'<line class="s1" x1="150.19" y1="43.08" x2="214.12" y2="106.38"/>'
    b'<line class="s1" x1="86.88" y1="106.38" x2="150.19" y2="43.08"/>'
    b'</svg>'
)


def _sageframe_pixmap(size: int = 16) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    if _HAS_SVG:
        renderer = _QSvgRenderer(_SAGEFRAME_SVG)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
    return pix


def _muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #7a7a7a; font-size: 12px; background: transparent;")
    return lbl


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("m4Bookmaker")
        self.setMinimumWidth(760)
        self.setMinimumHeight(520)
        self.resize(775, 800)
        self._dark_mode = False

        self._book: Optional[Book] = None
        self._mode: str = "build"  # "build" or "edit"
        self._m4b_total_duration: float = 0.0
        self._load_worker: Optional[LoadWorker] = None
        self._m4b_load_worker: Optional[LoadM4bWorker] = None
        self._convert_worker: Optional[ConvertWorker] = None
        self._preflight_worker: Optional[PreflightWorker] = None
        self._preflight_sample_rate: Optional[int] = None
        self._save_worker: Optional[SaveChaptersWorker] = None
        self._extra_windows: list["MainWindow"] = []
        self._queue_manager = QueueManager()
        self._queue_window: Optional[QueueWindow] = None

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

        quit_action = QAction("Quit m4Bookmaker", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_action)

        # Queue action
        queue_action = QAction("Show Encode Queue", self)
        queue_action.setShortcut("Ctrl+Shift+Q")
        queue_action.triggered.connect(self._show_queue_window)
        file_menu.addSeparator()
        file_menu.addAction(queue_action)

        # View menu
        view_menu = mb.addMenu("View")
        self._dark_action = QAction("Dark Mode", self)
        self._dark_action.setCheckable(True)
        self._dark_action.triggered.connect(self._toggle_dark_mode)
        view_menu.addAction(self._dark_action)

        # Help menu
        help_menu = mb.addMenu("Help")

        about_action = QAction("About m4Bookmaker", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        support_title = QAction("Support Development", self)
        support_title.setEnabled(False)
        help_menu.addAction(support_title)

        donate_action = QAction("♥  Buy Me a Coffee…", self)
        donate_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_DONATE_URL))
        )
        help_menu.addAction(donate_action)

        help_menu.addSeparator()

        github_action = QAction("GitHub…", self)
        github_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(_GITHUB_URL))
        )
        help_menu.addAction(github_action)

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))

    def _on_dark_mode_btn(self) -> None:
        self._dark_action.setChecked(not self._dark_action.isChecked())
        self._toggle_dark_mode()

    def _toggle_dark_mode(self) -> None:
        self._dark_mode = self._dark_action.isChecked()
        QApplication.instance().setStyleSheet(get_stylesheet(self._dark_mode))
        if hasattr(self, "_dark_btn"):
            self._dark_btn.setText("☀️" if self._dark_mode else "🌙")
        if self._queue_window is not None:
            self._queue_window.apply_stylesheet(self._dark_mode)

    def _new_window(self) -> None:
        win = MainWindow()
        win.show()
        self._extra_windows.append(win)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About m4Bookmaker",
            "<b>m4Bookmaker</b><br>"
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
        layout.setContentsMargins(12, 20, 12, 8)
        layout.setSpacing(4)

        self._folder_zone = FolderDropZone(accept_m4b=True)
        self._folder_zone.folder_changed.connect(self._on_folder_changed)
        self._folder_zone.folder_cleared.connect(self._on_folder_cleared)
        layout.addWidget(self._folder_zone)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(4, 0, 4, 0)
        badge_row.addStretch()
        self._mode_badge = QLabel("Build")
        self._mode_badge.setObjectName("modeBadge")
        badge_row.addWidget(self._mode_badge)
        layout.addLayout(badge_row)

        return box

    # ── Tab widget ────────────────────────────────────────────────────────────

    def _build_tabs(self) -> QTabWidget:
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_build_tab(), "Build")
        self._tabs.addTab(self._build_chapters_tab(), "Chapters")
        return self._tabs

    # ── Build tab ─────────────────────────────────────────────────────────────

    def _build_build_tab(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_meta_section())
        layout.addSpacing(8)
        layout.addWidget(self._build_settings_tabs())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    def _build_settings_tabs(self) -> QTabWidget:
        """Compact horizontal tab strip for Analysis / Encoding / Output."""
        self._settings_tabs = QTabWidget()
        self._settings_tabs.addTab(self._build_analysis_tab_content(), "Analysis")
        self._settings_tabs.addTab(self._build_encoding_tab_content(), "Encoding")
        self._settings_tabs.addTab(self._build_output_tab_content(), "Output")
        self._settings_tabs.setCurrentIndex(1)  # start on Encoding
        return self._settings_tabs

    def _build_analysis_tab_content(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        self._analysis_label = QLabel("No analysis yet.")
        self._analysis_label.setWordWrap(True)
        layout.addWidget(self._analysis_label)
        layout.addStretch()
        return w

    def _build_analysis_section(self) -> None:  # kept for compat; unused
        pass

    def _build_meta_section(self) -> QGroupBox:
        box = QGroupBox("Audiobook")
        hbox = QHBoxLayout(box)
        hbox.setContentsMargins(12, 20, 12, 12)
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

    def _build_encoding_tab_content(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
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
        return w

    def _build_encoding_section(self) -> None:  # kept for compat; unused
        pass

    def _build_output_tab_content(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

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
        return w

    def _build_output_section(self) -> None:  # kept for compat; unused
        pass

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

        # Insert Time button — sets selected chapter start to player position
        insert_row = QHBoxLayout()
        insert_row.setContentsMargins(0, 0, 0, 0)
        self._insert_time_btn = QPushButton("⇥ Insert Time")
        self._insert_time_btn.setToolTip(
            "Set selected chapter start time to current playback position"
        )
        self._insert_time_btn.setEnabled(False)
        self._insert_time_btn.clicked.connect(self._on_insert_time)
        insert_row.addStretch()
        insert_row.addWidget(self._insert_time_btn)
        layout.addLayout(insert_row)

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

        self._status_label = QLabel("")
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # Dark mode toggle (far left)
        self._dark_btn = QPushButton("🌙")
        self._dark_btn.setObjectName("darkModeBtn")
        self._dark_btn.setFixedSize(28, 28)
        self._dark_btn.setToolTip("Toggle dark mode")
        self._dark_btn.clicked.connect(self._on_dark_mode_btn)
        btn_row.addWidget(self._dark_btn)

        self._convert_btn = QPushButton("Convert to M4B")
        self._convert_btn.setObjectName("convertBtn")
        self._convert_btn.setFixedHeight(44)
        self._convert_btn.setFixedWidth(210)
        self._convert_btn.clicked.connect(self._on_convert)

        self._add_to_queue_btn = QPushButton("+ Queue")
        self._add_to_queue_btn.setObjectName("addToQueueBtn")
        self._add_to_queue_btn.setFixedHeight(44)
        self._add_to_queue_btn.setToolTip("Add this book to the encode queue (⌘⇧Q to open queue)")
        self._add_to_queue_btn.clicked.connect(self._on_add_to_queue)

        btn_row.addStretch()
        btn_row.addWidget(self._add_to_queue_btn)
        btn_row.addWidget(self._convert_btn)
        btn_row.addStretch()

        sf_lbl = QLabel(
            f'<a href="{_GITHUB_URL}" style="color: #7a7a7a; text-decoration: none;">'
            "Sageframe</a>"
        )
        sf_lbl.setOpenExternalLinks(True)
        sf_lbl.setStyleSheet("font-size: 11px; background: transparent;")
        btn_row.addWidget(sf_lbl)

        donate_lbl = QLabel(
            f'<a href="{_DONATE_URL}" style="color: #c45a2d; text-decoration: none;">'
            "♥ Support</a>"
        )
        donate_lbl.setOpenExternalLinks(True)
        donate_lbl.setStyleSheet("font-size: 11px; background: transparent;")
        donate_lbl.setToolTip("Support m4Bookmaker development")
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
        queue_busy = self._queue_manager.is_running
        if self._is_busy() or queue_busy:
            msg = (
                "The encode queue is running.\nAre you sure you want to quit?"
                if queue_busy
                else "A conversion is in progress.\nAre you sure you want to quit?"
            )
            reply = QMessageBox.question(
                self,
                "Cancel Conversion?",
                msg,
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
        self._add_to_queue_btn.setEnabled(has_book and self._mode == "build")
        self._tabs.setTabEnabled(1, has_book)
        if self._mode == "edit":
            self._convert_btn.setText("Save Chapter Edits")
            self._build_encoding_section_visibility(False)
        else:
            self._convert_btn.setText("Convert to M4B")
            self._build_encoding_section_visibility(True)

    def _build_encoding_section_visibility(self, visible: bool) -> None:
        self._settings_tabs.setVisible(visible)

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
        self._set_status(
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

    def _collect_job(self):
        """Snapshot current GUI state as a Job for the queue."""
        book = self._collect_book_edits()
        out = self._computed_output_path()
        if out is None:
            return None
        return job_from_book(
            book, out,
            bitrate=self._bitrate_combo.currentText(),
            stereo=self._stereo_radio.isChecked(),
            sample_rate=self._preflight_sample_rate,
        )

    def _on_add_to_queue(self) -> None:
        if self._book is None:
            return
        job = self._collect_job()
        if job is None:
            return
        self._queue_manager.add(job)
        self._show_queue_window()
        self._set_status(f"Added \"{job.title}\" to queue  ({len(self._queue_manager.jobs)} job(s))")

    def _show_queue_window(self) -> None:
        if self._queue_window is None:
            self._queue_window = QueueWindow(self._queue_manager)
            self._queue_window.apply_stylesheet(self._dark_mode)
        self._queue_window.show()
        self._queue_window.raise_()
        self._queue_window.activateWindow()

    def _on_folder_changed(self, p: Path) -> None:
        self._book = None
        self._analysis_label.setText("No analysis yet.")
        self._player.stop()
        self._update_controls()
        self._set_status("Scanning…")
        self._progress_bar.setVisible(True)
        self._progress_bar.setRange(0, 0)  # indeterminate spinner

        if p.is_dir():
            self._mode = "build"
            self._mode_badge.setText("Build")
            self._load_worker = LoadWorker(p)
            self._load_worker.finished.connect(self._on_load_finished)
            self._load_worker.error.connect(self._on_load_error)
            self._load_worker.start()
        else:
            self._mode = "edit"
            self._mode_badge.setText("Edit")
            self._m4b_load_worker = LoadM4bWorker(p)
            self._m4b_load_worker.finished.connect(self._on_m4b_loaded)
            self._m4b_load_worker.error.connect(self._on_load_error)
            self._m4b_load_worker.start()

    def _on_folder_cleared(self) -> None:
        self._preflight_sample_rate = None
        self._book = None
        self._mode = "build"
        self._mode_badge.setText("Build")
        self._analysis_label.setText("No analysis yet.")
        self._chapter_table.populate([])
        self._player.stop()
        self._progress_bar.setVisible(False)
        self._set_status("")
        self._update_controls()

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
        self._settings_tabs.setCurrentIndex(0)  # switch to Analysis tab
        # Auto-configure encoding from detected audio properties
        a = analysis  # type: ignore[assignment]
        if len(a.sample_rates) == 1:  # type: ignore[union-attr]
            self._preflight_sample_rate = next(iter(a.sample_rates))  # type: ignore[union-attr]
        else:
            self._preflight_sample_rate = None  # mixed rates — let ffmpeg decide
        # VBR sources: snap bitrate to safe default
        if len(a.bit_rates) != 1:  # type: ignore[union-attr]
            self._bitrate_combo.setCurrentText("96k")

    def _on_chapter_selected(
        self, row: int, _col: int, _prev_row: int, _prev_col: int
    ) -> None:
        if self._book is None or row < 0 or row >= len(self._book.chapters):
            self._insert_time_btn.setEnabled(False)
            return
        self._insert_time_btn.setEnabled(True)
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

    def _on_insert_time(self) -> None:
        """Set the selected chapter's start time to the current player position."""
        row = self._chapter_table.currentRow()
        if row < 0:
            return
        ms = self._player.current_position_ms
        self._chapter_table.set_chapter_time(row, ms)

    def _on_load_error(self, msg: str) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setVisible(False)
        self._set_status("Error loading folder.")
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
        self._set_status("Starting…")
        self._convert_btn.setEnabled(False)

        self._convert_worker = ConvertWorker(
            book=book,
            output_path=out,
            bitrate=self._bitrate_combo.currentText(),
            stereo=self._stereo_radio.isChecked(),
            sample_rate=self._preflight_sample_rate,
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
        self._set_status("Saving chapter edits…")
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
        times_ms = self._chapter_table.times_ms()
        for i, (ch, new_title) in enumerate(zip(chapters, self._chapter_table.titles())):
            ch.title = new_title
            if i < len(times_ms) and times_ms[i] is not None:
                ch.start_time = times_ms[i] / 1000.0
        return chapters

    def _on_save_finished(self, dest: object) -> None:
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._set_status(f"Saved — {Path(str(dest)).name}")
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
        self._set_status(msg)
        self._progress_bar.setValue(int(fraction * 100))

    def _on_convert_finished(self, result: PipelineResult) -> None:
        self._progress_bar.setValue(100)
        self._set_status(f"Done — {result.output_file.name}")
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
        self._set_status("Conversion failed.")
        self._update_controls()
        QMessageBox.critical(self, "Conversion Error", msg)
