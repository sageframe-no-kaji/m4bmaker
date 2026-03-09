"""Phase 6D verification — MainWindow.

Covers:
  - Initial state (no folder loaded)
  - Folder scanning / load flow (LoadWorker mocked)
  - Metadata auto-fill from Book
  - Cover detection inline with metadata
  - Chapter editing reflected in _collect_book_edits
  - Output path computation (nested / flat / custom)
  - Encoding flow (ConvertWorker mocked)
  - Error handling: load error, convert error, missing ffmpeg
  - UI remains enabled/disabled at correct points (responsiveness proxy)
  - Chapters tab enabled only after load
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: F401, E402

from m4bmaker.gui.window import MainWindow  # noqa: E402
from m4bmaker.models import Book, BookMetadata, Chapter, PipelineResult  # noqa: E402

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_book(tmp_path: Path) -> Book:
    f = tmp_path / "01.mp3"
    f.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
    return Book(
        files=[f],
        chapters=[Chapter(index=1, start_time=0.0, title="Intro", source_file=f)],
        metadata=BookMetadata(
            title="My Book",
            author="Jane Doe",
            narrator="John Smith",
            genre="Fiction",
        ),
        cover=None,
    )


def _make_pipeline_result(tmp_path: Path) -> PipelineResult:
    return PipelineResult(
        output_file=tmp_path / "My Book.m4b",
        chapter_count=1,
        duration_seconds=120.0,
    )


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def win(qapp, tmp_path):
    w = MainWindow()
    w.show()
    yield w, tmp_path
    w._is_busy = lambda: False  # type: ignore[method-assign]  # prevent dialog on teardown
    w.close()
    qapp.processEvents()  # drain pending Qt events so the next test starts clean


# ── initial state ─────────────────────────────────────────────────────────────


class TestInitialState:
    def test_convert_btn_disabled(self, win):
        w, _ = win
        assert not w._convert_btn.isEnabled()

    def test_chapters_tab_disabled(self, win):
        w, _ = win
        assert not w._tabs.isTabEnabled(1)

    def test_folder_zone_empty(self, win):
        w, _ = win
        assert w._folder_zone.path() is None

    def test_status_label_present(self, win):
        w, _ = win
        assert w._status_label is not None

    def test_default_bitrate(self, win):
        w, _ = win
        assert w._bitrate_combo.currentText() == "96k"

    def test_mono_default(self, win):
        w, _ = win
        assert w._mono_radio.isChecked()

    def test_nested_output_default(self, win):
        w, _ = win
        assert w._out_nested.isChecked()


# ── folder loading ────────────────────────────────────────────────────────────


class TestFolderLoading:
    def test_book_applied_to_ui(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        w._on_load_finished(book)
        assert w._title_edit.text() == "My Book"
        assert w._author_edit.text() == "Jane Doe"
        assert w._narrator_edit.text() == "John Smith"
        assert w._genre_edit.text() == "Fiction"

    def test_chapters_tab_enabled_after_load(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert w._tabs.isTabEnabled(1)

    def test_convert_btn_enabled_after_load(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert w._convert_btn.isEnabled()

    def test_chapter_table_populated(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert w._chapter_table.rowCount() == 1
        assert w._chapter_table.item(0, 2).text() == "Intro"

    def test_load_error_disables_convert(self, win):
        w, _ = win
        with patch("m4bmaker.gui.window.QMessageBox.critical"):
            w._on_load_error("boom")
        assert not w._convert_btn.isEnabled()

    def test_load_error_shows_message(self, win):
        w, _ = win
        with patch("m4bmaker.gui.window.QMessageBox.critical") as mock_crit:
            w._on_load_error("boom")
        mock_crit.assert_called_once()
        assert "boom" in mock_crit.call_args[0]

    def test_on_folder_changed_starts_load_worker(self, win, tmp_path):
        w, _ = win
        with (
            patch("m4bmaker.gui.worker.shutil.which", return_value="/usr/bin/ffprobe"),
            patch(
                "m4bmaker.gui.worker.load_audiobook", return_value=_make_book(tmp_path)
            ),
        ):
            w._on_folder_changed(tmp_path)
            assert w._load_worker is not None
            w._load_worker.wait(3000)


# ── metadata auto-fill ────────────────────────────────────────────────────────


class TestMetadataAutoFill:
    def test_all_fields_filled(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        book.metadata.genre = "Sci-Fi"
        w._on_load_finished(book)
        assert w._genre_edit.text() == "Sci-Fi"

    def test_empty_fields_on_empty_metadata(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        book.metadata.title = ""
        book.metadata.author = ""
        w._on_load_finished(book)
        assert w._title_edit.text() == ""
        assert w._author_edit.text() == ""

    def test_collect_edits_picks_up_changes(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._title_edit.setText("Edited Title")
        w._author_edit.setText("New Author")
        book = w._collect_book_edits()
        assert book.metadata.title == "Edited Title"
        assert book.metadata.author == "New Author"

    def test_collect_edits_narrator_genre(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._narrator_edit.setText("Narrator X")
        w._genre_edit.setText("History")
        book = w._collect_book_edits()
        assert book.metadata.narrator == "Narrator X"
        assert book.metadata.genre == "History"


# ── cover ─────────────────────────────────────────────────────────────────────


class TestCoverInline:
    def test_cover_none_on_load(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert w._cover_widget.cover_path() is None

    def test_cover_set_when_book_has_cover(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 20)
        book.cover = img
        w._on_load_finished(book)
        assert w._cover_widget.cover_path() == img

    def test_on_cover_changed_updates_book(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        img = tmp_path / "new.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 20)
        w._on_cover_changed(img)
        assert w._book.cover == img  # type: ignore[union-attr]


# ── chapter editing ───────────────────────────────────────────────────────────


class TestChapterEditing:
    def test_edited_title_in_collect(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._chapter_table.item(0, 2).setText("Revised Intro")
        book = w._collect_book_edits()
        assert book.chapters[0].title == "Revised Intro"

    def test_original_book_not_mutated(self, win, tmp_path):
        w, _ = win
        orig = _make_book(tmp_path)
        w._on_load_finished(orig)
        w._chapter_table.item(0, 2).setText("Changed")
        w._collect_book_edits()
        assert w._book.chapters[0].title == "Intro"  # type: ignore[union-attr]


# ── output path computation ───────────────────────────────────────────────────


class TestOutputPath:
    def test_nested_path(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._out_nested.setChecked(True)
        out = w._computed_output_path()
        assert out is not None
        assert out.name == "My Book.m4b"
        assert "Jane Doe" in str(out)
        assert "My Book" in str(out.parent)

    def test_flat_path(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._out_flat.setChecked(True)
        out = w._computed_output_path()
        assert out is not None
        assert "Jane Doe" in out.name
        assert "My Book" in out.name

    def test_custom_path_empty_returns_none(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._out_custom.setChecked(True)
        w._custom_path_edit.setText("")
        assert w._computed_output_path() is None

    def test_custom_path_set(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._out_custom.setChecked(True)
        dest = str(tmp_path / "out.m4b")
        w._custom_path_edit.setText(dest)
        assert w._computed_output_path() == Path(dest)

    def test_output_preview_updates_on_title_change(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._title_edit.setText("New Title")
        assert "New Title" in w._out_nested.text()

    def test_browse_custom_output_sets_path(self, win, tmp_path):
        """Lines 376-382: browse dialog sets custom output path."""
        w, _ = win
        dest = str(tmp_path / "my book.m4b")
        with patch(
            "m4bmaker.gui.window.QFileDialog.getSaveFileName",
            return_value=(dest, ""),
        ):
            w._browse_custom_output()
        assert w._custom_path_edit.text() == dest

    def test_browse_custom_output_appends_extension(self, win, tmp_path):
        """Line 381: path without .m4b extension gets it appended."""
        w, _ = win
        dest = str(tmp_path / "my book")
        with patch(
            "m4bmaker.gui.window.QFileDialog.getSaveFileName",
            return_value=(dest, ""),
        ):
            w._browse_custom_output()
        assert w._custom_path_edit.text() == dest + ".m4b"


# ── encoding flow ─────────────────────────────────────────────────────────────


class TestEncoding:
    def test_convert_disabled_while_running(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._out_nested.setChecked(True)

        worker_mock = MagicMock()
        worker_mock.isRunning.return_value = True
        with patch("m4bmaker.gui.window.ConvertWorker", return_value=worker_mock):
            w._on_convert()
        assert not w._convert_btn.isEnabled()

    def test_convert_no_book_is_noop(self, win):
        w, _ = win
        # no book loaded — _on_convert should return immediately
        with patch("m4bmaker.gui.window.ConvertWorker") as mock_worker:
            w._on_convert()
        mock_worker.assert_not_called()

    def test_convert_custom_path_empty_shows_warning(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._out_custom.setChecked(True)
        w._custom_path_edit.setText("")
        with patch("m4bmaker.gui.window.QMessageBox.warning") as mock_warn:
            w._on_convert()
        mock_warn.assert_called_once()

    def test_progress_updates_bar_and_label(self, win):
        w, _ = win
        w._progress_bar.setVisible(True)
        w._progress_bar.setRange(0, 100)
        w._on_progress("Encoding…", 0.5)
        assert w._progress_bar.value() == 50
        assert w._status_label.text() == "Encoding…"

    def test_convert_finished_shows_dialog(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        result = _make_pipeline_result(tmp_path)
        with patch("m4bmaker.gui.window.QMessageBox") as mock_mb:
            mock_mb.return_value.exec.return_value = None
            w._on_convert_finished(result)
        mock_mb.assert_called_once()

    def test_convert_error_shows_dialog(self, win):
        w, _ = win
        with patch("m4bmaker.gui.window.QMessageBox.critical") as mock_crit:
            w._on_convert_error("ffmpeg not found")
        mock_crit.assert_called_once()
        assert "ffmpeg not found" in mock_crit.call_args[0]

    def test_convert_error_re_enables_convert_btn(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        with patch("m4bmaker.gui.window.QMessageBox.critical"):
            w._on_convert_error("boom")
        assert w._convert_btn.isEnabled()

    def test_stereo_flag_passed_to_worker(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._stereo_radio.setChecked(True)
        w._out_nested.setChecked(True)

        captured_kwargs: dict = {}

        class _FakeWorker(MagicMock):
            def __init__(self_inner, *args, **kwargs):  # type: ignore[misc]
                captured_kwargs.update(kwargs)
                super().__init__()
                self_inner.isRunning = MagicMock(return_value=True)

            def start(self_inner):  # type: ignore[misc]
                pass

            progress = MagicMock()
            finished = MagicMock()
            error = MagicMock()

        with patch("m4bmaker.gui.window.ConvertWorker", side_effect=_FakeWorker):
            w._on_convert()

        assert captured_kwargs.get("stereo") is True

    def test_bitrate_passed_to_worker(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._bitrate_combo.setCurrentText("128k")
        w._out_nested.setChecked(True)

        captured_kwargs: dict = {}

        class _FakeWorker(MagicMock):
            def __init__(self_inner, *args, **kwargs):  # type: ignore[misc]
                captured_kwargs.update(kwargs)
                super().__init__()
                self_inner.isRunning = MagicMock(return_value=True)

            def start(self_inner):  # type: ignore[misc]
                pass

            progress = MagicMock()
            finished = MagicMock()
            error = MagicMock()

        with patch("m4bmaker.gui.window.ConvertWorker", side_effect=_FakeWorker):
            w._on_convert()

        assert captured_kwargs.get("bitrate") == "128k"


# ── missing ffmpeg ────────────────────────────────────────────────────────────


class TestMissingFfmpeg:
    def test_load_worker_emits_error_on_sysexit(self, qapp, tmp_path):
        """LoadWorker.error is emitted when ffprobe is missing (sys.exit)."""
        from m4bmaker.gui.worker import LoadWorker

        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.load_audiobook",
            side_effect=SystemExit("ffprobe not found"),
        ):
            worker = LoadWorker(tmp_path)
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors
        assert "ffprobe" in errors[0]

    def test_convert_worker_emits_error_on_sysexit(self, qapp, tmp_path):
        """ConvertWorker.error is emitted when ffmpeg is missing (sys.exit)."""
        from m4bmaker.gui.worker import ConvertWorker

        book = _make_book(tmp_path)
        errors: list[str] = []

        with patch(
            "m4bmaker.gui.worker.run_pipeline",
            side_effect=SystemExit("ffmpeg not found"),
        ):
            worker = ConvertWorker(book=book, output_path=tmp_path / "out.m4b")
            worker.error.connect(errors.append)
            worker.start()
            worker.wait(3000)

        qapp.processEvents()
        assert errors
        assert "ffmpeg" in errors[0]


# ── Audio Analysis section ────────────────────────────────────────────────────


class TestAnalysisSection:
    def test_analysis_box_hidden_initially(self, win):
        w, _ = win
        assert w._analysis_label.text() == "No analysis yet."

    def test_analysis_box_shown_after_preflight(self, win):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        analysis = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 2}),
            channels=Counter({2: 2}),
        )
        w._on_preflight_finished(analysis)
        assert w._settings_tabs.currentIndex() == 0  # switched to Analysis tab

    def test_analysis_label_updated(self, win):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        analysis = AudioAnalysis(
            file_count=1,
            sample_rates=Counter({44100: 1}),
            channels=Counter({1: 1}),
        )
        w._on_preflight_finished(analysis)
        assert "44100" in w._analysis_label.text()

    def test_analysis_box_hidden_on_new_folder(self, win, tmp_path):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        analysis = AudioAnalysis(file_count=1, sample_rates=Counter({44100: 1}))
        w._on_preflight_finished(analysis)
        assert w._settings_tabs.currentIndex() == 0  # Analysis tab active

        # Simulate folder changed — analysis label should reset
        with patch("m4bmaker.gui.window.LoadWorker") as MockLW:
            mock_worker = MagicMock()
            MockLW.return_value = mock_worker
            w._on_folder_changed(tmp_path)
        assert w._analysis_label.text() == "No analysis yet."


# ── Edit mode (m4b file) ──────────────────────────────────────────────────────


class TestEditMode:
    def test_mode_is_build_initially(self, win):
        w, _ = win
        assert w._mode == "build"

    def test_folder_changed_with_m4b_sets_edit_mode(self, win, tmp_path):
        w, _ = win
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")

        with patch("m4bmaker.gui.window.LoadM4bWorker") as MockW:
            mock_worker = MagicMock()
            MockW.return_value = mock_worker
            w._on_folder_changed(m4b)

        assert w._mode == "edit"
        MockW.assert_called_once_with(m4b)

    def test_folder_changed_with_dir_sets_build_mode(self, win, tmp_path):
        w, _ = win
        with patch("m4bmaker.gui.window.LoadWorker") as MockW:
            mock_worker = MagicMock()
            MockW.return_value = mock_worker
            w._on_folder_changed(tmp_path)
        assert w._mode == "build"

    def test_convert_btn_text_edit_mode(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        w._mode = "edit"
        w._book = book
        w._update_controls()
        assert "Save" in w._convert_btn.text()

    def test_convert_btn_text_build_mode(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        w._mode = "build"
        w._book = book
        w._update_controls()
        assert "Convert" in w._convert_btn.text()

    def test_on_m4b_loaded_applies_book(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        w._mode = "edit"
        w._on_m4b_loaded((book, 120.0))
        assert w._book is book
        assert w._m4b_total_duration == 120.0
        assert w._title_edit.text() == "My Book"

    def test_save_chapters_worker_started_in_edit_mode(self, win, tmp_path):
        w, _ = win
        book = _make_book(tmp_path)
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        w._book = book
        w._mode = "edit"
        w._m4b_total_duration = 120.0
        # Set the folder zone path directly via its text field (does not emit signal)
        w._folder_zone._edit.setText(str(m4b))

        with patch("m4bmaker.gui.window.SaveChaptersWorker") as MockW:
            mock_worker = MagicMock()
            mock_worker.isRunning.return_value = False
            MockW.return_value = mock_worker
            w._on_convert()

        MockW.assert_called_once()

    def test_on_save_finished_updates_status(self, win, tmp_path):
        w, _ = win
        dest = tmp_path / "book.m4b"
        dest.write_bytes(b"\x00")
        with patch("m4bmaker.gui.window.QMessageBox"):
            w._on_save_finished(dest)
        assert "book.m4b" in w._status_label.text()


# ── Player in Chapters tab ────────────────────────────────────────────────────


class TestChaptersTabPlayer:
    def test_player_widget_present(self, win):
        w, _ = win
        from m4bmaker.gui.player import AudioPlayerWidget

        assert isinstance(w._player, AudioPlayerWidget)

    def test_chapter_selected_with_no_book_does_nothing(self, win):
        w, _ = win
        # Should not raise
        w._on_chapter_selected(0, 0, -1, 0)

    def test_chapter_selected_out_of_range_does_nothing(self, win, tmp_path):
        w, _ = win
        w._book = _make_book(tmp_path)
        # Index 5 is out of range (book has 1 chapter)
        w._on_chapter_selected(5, 0, -1, 0)  # should not raise

    def test_chapter_selected_calls_player_load_paused_when_stopped(self, win, tmp_path):
        """Selecting a chapter when not playing calls load_paused (no auto-play)."""
        from unittest.mock import PropertyMock

        w, _ = win
        book = _make_book(tmp_path)
        w._book = book
        w._mode = "build"
        with patch.object(type(w._player), "is_playing", new_callable=PropertyMock, return_value=False):
            with patch.object(w._player, "load_paused") as mock_load_paused:
                w._on_chapter_selected(0, 0, -1, 0)
        mock_load_paused.assert_called_once()
        pos_args = mock_load_paused.call_args[0]
        assert pos_args[1] == 0  # start_ms = 0

    def test_chapter_selected_calls_player_load_when_playing(self, win, tmp_path):
        """Selecting a chapter while playing calls load (seek + continue playing)."""
        from unittest.mock import PropertyMock

        w, _ = win
        book = _make_book(tmp_path)
        w._book = book
        w._mode = "build"
        with patch.object(type(w._player), "is_playing", new_callable=PropertyMock, return_value=True):
            with patch.object(w._player, "load") as mock_load:
                w._on_chapter_selected(0, 0, -1, 0)
        mock_load.assert_called_once()
