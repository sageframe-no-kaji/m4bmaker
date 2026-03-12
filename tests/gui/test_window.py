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
from m4bmaker.gui.widgets import ChapterTable  # noqa: E402
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


# ── folder cleared ────────────────────────────────────────────────────────────


class TestFolderCleared:
    def test_cleared_resets_book(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert w._book is not None
        w._on_folder_cleared()
        assert w._book is None

    def test_cleared_disables_convert(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._on_folder_cleared()
        assert not w._convert_btn.isEnabled()

    def test_cleared_resets_mode_to_build(self, win, tmp_path):
        w, _ = win
        w._mode = "edit"
        w._on_folder_cleared()
        assert w._mode == "build"

    def test_cleared_resets_mode_badge(self, win, tmp_path):
        w, _ = win
        w._mode_badge.setText("Edit")
        w._on_folder_cleared()
        assert w._mode_badge.text() == "Build"

    def test_folder_changed_build_badge(self, win, tmp_path):
        w, _ = win
        with patch("m4bmaker.gui.window.LoadWorker") as MockLW:
            MockLW.return_value = MagicMock()
            w._on_folder_changed(tmp_path)
        assert w._mode_badge.text() == "Build"

    def test_folder_changed_edit_badge(self, win, tmp_path):
        w, _ = win
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        with patch("m4bmaker.gui.window.LoadM4bWorker") as MockW:
            MockW.return_value = MagicMock()
            w._on_folder_changed(m4b)
        assert w._mode_badge.text() == "Edit"


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

    def test_preflight_snaps_bitrate_to_source(self, win):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        # source is 32 kbps (32000 bps)
        analysis = AudioAnalysis(
            file_count=4,
            sample_rates=Counter({22050: 4}),
            channels=Counter({1: 4}),
            bit_rates=Counter({32000: 4}),
        )
        w._on_preflight_finished(analysis)
        assert w._bitrate_combo.currentText() == "32k"

    def test_preflight_snaps_mono(self, win):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        w._stereo_radio.setChecked(True)  # start on stereo
        analysis = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 2}),
            channels=Counter({1: 2}),
            bit_rates=Counter({64000: 2}),
        )
        w._on_preflight_finished(analysis)
        assert w._mono_radio.isChecked()
        assert not w._stereo_radio.isChecked()

    def test_preflight_snaps_stereo(self, win):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        analysis = AudioAnalysis(
            file_count=2,
            sample_rates=Counter({44100: 2}),
            channels=Counter({2: 2}),
            bit_rates=Counter({128000: 2}),
        )
        w._on_preflight_finished(analysis)
        assert w._stereo_radio.isChecked()

    def test_preflight_mixed_channels_leaves_selection_unchanged(self, win):
        from collections import Counter
        from m4bmaker.preflight import AudioAnalysis

        w, _ = win
        assert w._mono_radio.isChecked()  # default
        analysis = AudioAnalysis(
            file_count=3,
            sample_rates=Counter({44100: 3}),
            channels=Counter({1: 2, 2: 1}),  # mixed
            bit_rates=Counter({96000: 3}),
        )
        w._on_preflight_finished(analysis)
        assert w._mono_radio.isChecked()  # unchanged


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

    def test_chapter_selected_calls_player_load_paused_when_stopped(
        self, win, tmp_path
    ):
        """Selecting a chapter when not playing calls load_paused (no auto-play)."""
        from unittest.mock import PropertyMock

        w, _ = win
        book = _make_book(tmp_path)
        w._book = book
        w._mode = "build"
        with patch.object(
            type(w._player), "is_playing", new_callable=PropertyMock, return_value=False
        ):
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
        with patch.object(
            type(w._player), "is_playing", new_callable=PropertyMock, return_value=True
        ):
            with patch.object(w._player, "load") as mock_load:
                w._on_chapter_selected(0, 0, -1, 0)
        mock_load.assert_called_once()


# ── Queue integration ─────────────────────────────────────────────────────────


class TestQueueIntegration:
    def test_add_to_queue_btn_exists(self, win):
        w, _ = win
        assert hasattr(w, "_add_to_queue_btn")

    def test_add_to_queue_btn_disabled_initially(self, win):
        w, _ = win
        assert not w._add_to_queue_btn.isEnabled()

    def test_add_to_queue_btn_enabled_after_load(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert w._add_to_queue_btn.isEnabled()

    def test_add_to_queue_btn_disabled_in_edit_mode(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._mode = "edit"
        w._update_controls()
        assert not w._add_to_queue_btn.isEnabled()

    def test_on_add_to_queue_adds_job(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._folder_zone._path = tmp_path
        with patch.object(w, "_show_queue_window"):
            w._on_add_to_queue()
        assert len(w._queue_manager.jobs) == 1

    def test_on_add_to_queue_shows_queue_window(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._folder_zone._path = tmp_path
        with patch.object(w, "_show_queue_window") as mock_show:
            w._on_add_to_queue()
        mock_show.assert_called_once()

    def test_on_add_to_queue_updates_status(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        w._folder_zone._path = tmp_path
        with patch.object(w, "_show_queue_window"):
            w._on_add_to_queue()
        assert "queue" in w._status_label.text().lower()

    def test_on_add_to_queue_noop_when_no_book(self, win):
        w, _ = win
        w._on_add_to_queue()  # should not raise
        assert len(w._queue_manager.jobs) == 0

    def test_show_queue_window_creates_window(self, win):
        w, _ = win
        assert w._queue_window is None
        w._show_queue_window()
        assert w._queue_window is not None

    def test_show_queue_window_reuses_instance(self, win):
        w, _ = win
        w._show_queue_window()
        first = w._queue_window
        w._show_queue_window()
        assert w._queue_window is first

    def test_close_event_allowed_when_queue_idle(self, win):
        from PySide6.QtGui import QCloseEvent

        w, _ = win
        event = QCloseEvent()
        w.closeEvent(event)
        assert event.isAccepted()

    def test_close_event_prompts_when_queue_running(self, win):
        from unittest.mock import PropertyMock

        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QMessageBox

        w, _ = win
        event = QCloseEvent()
        with patch.object(
            type(w._queue_manager),
            "is_running",
            new_callable=PropertyMock,
            return_value=True,
        ):
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ):
                w.closeEvent(event)
        assert not event.isAccepted()

    def test_toggle_dark_mode_syncs_queue_window(self, win):
        w, _ = win
        w._show_queue_window()
        w._dark_action.setChecked(True)
        with patch.object(w._queue_window, "apply_stylesheet") as mock_apply:
            w._toggle_dark_mode()
        mock_apply.assert_called_once_with(True)


# ── Split into chapters ───────────────────────────────────────────────────────


class TestSplitIntoChapters:
    def test_split_btn_exists(self, win):
        w, _ = win
        assert hasattr(w, "_split_btn")

    def test_split_btn_hidden_in_build_mode(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        assert not w._split_btn.isVisible()

    def test_split_btn_visible_in_edit_mode(self, win, tmp_path):
        w, _ = win
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        w._mode = "edit"
        w._book = _make_book(tmp_path)
        w._update_controls()
        assert w._split_btn.isVisible()

    def test_split_btn_disabled_initially(self, win):
        w, _ = win
        w._mode = "edit"
        w._update_controls()
        # no book loaded → disabled
        assert not w._split_btn.isEnabled()

    def test_split_btn_enabled_after_load_in_edit_mode(self, win, tmp_path):
        w, _ = win
        w._mode = "edit"
        w._book = _make_book(tmp_path)
        w._update_controls()
        assert w._split_btn.isEnabled()

    def test_on_split_noop_when_no_book(self, win):
        w, _ = win
        w._on_split_chapters()  # should not raise

    def test_on_split_noop_when_no_source_path(self, win, tmp_path):
        w, _ = win
        w._mode = "edit"
        w._book = _make_book(tmp_path)
        # folder_zone path is None
        w._on_split_chapters()  # should not raise

    def test_on_split_starts_worker(self, win, tmp_path):
        from m4bmaker.gui.worker import SplitWorker

        w, _ = win
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        w._mode = "edit"
        w._book = _make_book(tmp_path)
        w._folder_zone._edit.setText(str(m4b))
        w._m4b_total_duration = 120.0

        out_dir = str(tmp_path / "chapters")
        with patch(
            "m4bmaker.gui.window.QFileDialog.getExistingDirectory",
            return_value=out_dir,
        ):
            with patch.object(SplitWorker, "start"):
                w._on_split_chapters()
        assert w._split_worker is not None

    def test_on_split_noop_when_dialog_cancelled(self, win, tmp_path):
        m4b = tmp_path / "book.m4b"
        m4b.write_bytes(b"\x00")
        w, _ = win
        w._mode = "edit"
        w._book = _make_book(tmp_path)
        w._folder_zone._edit.setText(str(m4b))

        with patch(
            "m4bmaker.gui.window.QFileDialog.getExistingDirectory",
            return_value="",
        ):
            w._on_split_chapters()
        assert w._split_worker is None

    def test_on_split_finished_updates_status(self, win, tmp_path):
        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        out = tmp_path / "chapters"
        out.mkdir()
        w._on_split_finished(out)
        text = w._status_label.text().lower()
        assert "chapters" in text or "split" in text

    def test_on_split_error_shows_dialog(self, win, tmp_path):
        from PySide6.QtWidgets import QMessageBox

        w, _ = win
        w._on_load_finished(_make_book(tmp_path))
        with patch.object(QMessageBox, "critical") as mock_crit:
            w._on_split_error("ffmpeg died")
        mock_crit.assert_called_once()
        text = w._status_label.text().lower()
        assert "split" in text or "failed" in text


# ── helpers for chapter-editing tests ─────────────────────────────────────────


def _make_multi_book(tmp_path: Path, n: int = 5) -> Book:
    """Create a book with *n* chapters (10 s each), each backed by its own file."""
    files = []
    chapters = []
    for i in range(n):
        f = tmp_path / f"{i + 1:02d}.mp3"
        f.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
        files.append(f)
        chapters.append(
            Chapter(
                index=i + 1,
                start_time=i * 10.0,
                title=f"Chapter {i + 1}",
                source_file=f,
            )
        )
    return Book(
        files=files,
        chapters=chapters,
        metadata=BookMetadata(title="Test", author="A", narrator="N", genre="G"),
        total_duration=n * 10.0,
    )


def _load_multi(w, tmp_path, n=5):
    """Load a multi-chapter book into the window and return the book.

    Calls ``_apply_book_to_ui`` directly instead of ``_on_load_finished`` to
    avoid spawning a PreflightWorker thread (which runs ffprobe and crashes
    on teardown when the QThread is destroyed mid-run).  Player load methods
    are also stubbed out so ``_on_chapter_selected`` doesn't start workers.
    """
    book = _make_multi_book(tmp_path, n)
    w._player.load = lambda *a, **kw: None
    w._player.load_paused = lambda *a, **kw: None
    w._apply_book_to_ui(book)
    return book


# ── chapter move up / down ────────────────────────────────────────────────────


class TestChapterMoveUp:
    def test_move_up_swaps_chapters(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_move_up()
        assert w._book.chapters[0].title == "Chapter 2"
        assert w._book.chapters[1].title == "Chapter 1"

    def test_move_up_swaps_files_in_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        original_file_0 = w._book.files[0]
        original_file_1 = w._book.files[1]
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_move_up()
        assert w._book.files[0] == original_file_1
        assert w._book.files[1] == original_file_0

    def test_move_up_skips_files_in_edit_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._mode = "edit"
        original_files = list(w._book.files)
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_move_up()
        assert w._book.files == original_files

    def test_move_up_at_row_0_is_noop(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        w._on_chapter_move_up()
        assert w._book.chapters[0].title == "Chapter 1"

    def test_move_up_reindexes_start_times(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_move_up()
        # After swap, start_times are rebuilt from durations
        assert w._book.chapters[0].start_time == 0.0
        assert w._book.chapters[1].start_time == 10.0


class TestChapterMoveDown:
    def test_move_down_swaps_chapters(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        w._on_chapter_move_down()
        assert w._book.chapters[0].title == "Chapter 2"
        assert w._book.chapters[1].title == "Chapter 1"

    def test_move_down_swaps_files_in_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        original_file_0 = w._book.files[0]
        original_file_1 = w._book.files[1]
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        w._on_chapter_move_down()
        assert w._book.files[0] == original_file_1
        assert w._book.files[1] == original_file_0

    def test_move_down_skips_files_in_edit_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._mode = "edit"
        original_files = list(w._book.files)
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        w._on_chapter_move_down()
        assert w._book.files == original_files

    def test_move_down_at_last_row_is_noop(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(2, ChapterTable.COL_TITLE)
        w._on_chapter_move_down()
        assert w._book.chapters[2].title == "Chapter 3"


# ── chapter remove ────────────────────────────────────────────────────────────


class TestChapterRemove:
    def test_remove_deletes_chapter_and_file_in_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_remove()
        assert len(w._book.chapters) == 2
        assert len(w._book.files) == 2
        assert w._book.chapters[0].title == "Chapter 1"
        assert w._book.chapters[1].title == "Chapter 3"

    def test_remove_keeps_files_in_edit_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._mode = "edit"
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_remove()
        assert len(w._book.chapters) == 2
        assert len(w._book.files) == 3  # files untouched

    def test_remove_updates_durations(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_remove()
        assert len(w._chapter_durations) == 2

    def test_remove_noop_no_selection(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._chapter_table.setCurrentCell(-1, 0)
        w._on_chapter_remove()
        assert len(w._book.chapters) == 5  # unchanged


# ── chapter merge ─────────────────────────────────────────────────────────────


class TestChapterMerge:
    def _select_range(self, w, start, end):
        """Simulate shift-click selection of rows start..end (inclusive)."""
        from PySide6.QtCore import QItemSelectionModel

        sel_model = w._chapter_table.selectionModel()
        sel_model.clearSelection()
        for r in range(start, end + 1):
            idx = w._chapter_table.model().index(r, 0)
            sel_model.select(
                idx,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )

    def test_merge_collapses_chapters(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        self._select_range(w, 1, 3)  # rows 1,2,3 → merge into row 1
        w._on_chapter_merge()
        assert len(w._book.chapters) == 3
        assert w._book.chapters[0].title == "Chapter 1"
        assert w._book.chapters[1].title == "Chapter 2"  # keeps first selected title
        assert w._book.chapters[2].title == "Chapter 5"

    def test_merge_sums_durations(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        self._select_range(w, 1, 3)
        w._on_chapter_merge()
        # 3 rows of 10s each merged → 30s
        assert w._chapter_durations[1] == pytest.approx(30.0)

    def test_merge_preserves_all_files_in_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        self._select_range(w, 1, 3)
        w._on_chapter_merge()
        assert len(w._book.files) == 5  # all files still present

    def test_merge_sets_chapters_merged_in_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        assert w._chapters_merged is False
        self._select_range(w, 0, 1)
        w._on_chapter_merge()
        assert w._chapters_merged is True

    def test_merge_does_not_set_chapters_merged_in_edit_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        w._mode = "edit"
        self._select_range(w, 0, 1)
        w._on_chapter_merge()
        assert w._chapters_merged is False

    def test_merge_hides_file_ops_after_build_merge(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        self._select_range(w, 0, 1)
        w._on_chapter_merge()
        # Use isHidden() — checks the widget's own flag, not the parent chain.
        assert w._ch_up_btn.isHidden()
        assert w._ch_down_btn.isHidden()
        assert w._ch_remove_btn.isHidden()
        assert not w._ch_merge_btn.isHidden()

    def test_merge_noop_single_selection(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        self._select_range(w, 1, 1)
        w._on_chapter_merge()
        assert len(w._book.chapters) == 3  # unchanged

    def test_chapters_merged_resets_on_new_book(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        self._select_range(w, 0, 1)
        w._on_chapter_merge()
        assert w._chapters_merged is True
        # Load a fresh book
        _load_multi(w, tmp_path, n=3)
        assert w._chapters_merged is False

    def test_merge_reindexes_start_times(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        self._select_range(w, 1, 3)
        w._on_chapter_merge()
        # ch0: 0s, ch1 (merged): 10s, ch2 (was ch5): 40s
        assert w._book.chapters[0].start_time == pytest.approx(0.0)
        assert w._book.chapters[1].start_time == pytest.approx(10.0)
        assert w._book.chapters[2].start_time == pytest.approx(40.0)


# ── chapter prev / next ───────────────────────────────────────────────────────


class TestChapterPrevNext:
    def test_prev_moves_to_previous_row(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(2, ChapterTable.COL_TITLE)
        w._on_chapter_prev()
        assert w._chapter_table.currentRow() == 1

    def test_prev_at_row_0_stays(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        w._on_chapter_prev()
        assert w._chapter_table.currentRow() == 0

    def test_next_moves_to_next_row(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        w._on_chapter_next()
        assert w._chapter_table.currentRow() == 1

    def test_next_at_last_row_stays(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(2, ChapterTable.COL_TITLE)
        w._on_chapter_next()
        assert w._chapter_table.currentRow() == 2

    def test_prev_btn_disabled_at_row_0(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(0, ChapterTable.COL_TITLE)
        # trigger signal manually
        w._on_chapter_selected(0, 0, -1, -1)
        assert not w._ch_prev_btn.isEnabled()

    def test_next_btn_disabled_at_last_row(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(2, ChapterTable.COL_TITLE)
        w._on_chapter_selected(2, 0, -1, -1)
        assert not w._ch_next_btn.isEnabled()

    def test_both_btns_enabled_at_middle_row(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(1, ChapterTable.COL_TITLE)
        w._on_chapter_selected(1, 0, -1, -1)
        assert w._ch_prev_btn.isEnabled()
        assert w._ch_next_btn.isEnabled()


# ── insert time ───────────────────────────────────────────────────────────────


class TestInsertTime:
    def test_insert_time_build_mode_adds_cumulative_offset(self, win, tmp_path):
        """In build mode, player position is file-local; Insert Time must add
        the chapter's cumulative start_time to get the correct global time."""
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        # Simulate: chapter 3 (start_time=20.0s), player at 3.5s into that file
        w._chapter_table.setCurrentCell(2, ChapterTable.COL_TITLE)
        with patch.object(
            type(w._player),
            "current_position_ms",
            new_callable=lambda: property(lambda self: 3500),
        ):
            w._on_insert_time()
        # Expected: 20000 + 3500 = 23500 ms
        times = w._chapter_table.times_ms()
        assert times[2] == 23500

    def test_insert_time_edit_mode_uses_raw_position(self, win, tmp_path):
        """In edit mode, player loads the single .m4b — positions are global.
        Insert Time should use the raw position without adding any offset."""
        w, _ = win
        _load_multi(w, tmp_path, n=5)
        w._mode = "edit"
        w._chapter_table.setCurrentCell(2, ChapterTable.COL_TITLE)
        with patch.object(
            type(w._player),
            "current_position_ms",
            new_callable=lambda: property(lambda self: 45000),
        ):
            w._on_insert_time()
        times = w._chapter_table.times_ms()
        assert times[2] == 45000

    def test_insert_time_noop_no_selection(self, win, tmp_path):
        """Insert Time with no row selected should be a no-op."""
        w, _ = win
        _load_multi(w, tmp_path, n=3)
        w._chapter_table.setCurrentCell(-1, 0)
        # Should not raise
        w._on_insert_time()


# ── update_chapter_buttons visibility ─────────────────────────────────────────


class TestUpdateChapterButtons:
    def test_buttons_visible_in_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._update_chapter_buttons()
        assert not w._ch_up_btn.isHidden()
        assert not w._ch_down_btn.isHidden()
        assert not w._ch_remove_btn.isHidden()
        assert not w._ch_merge_btn.isHidden()

    def test_buttons_visible_in_edit_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._mode = "edit"
        w._update_chapter_buttons()
        assert not w._ch_up_btn.isHidden()
        assert not w._ch_down_btn.isHidden()
        assert not w._ch_remove_btn.isHidden()
        assert not w._ch_merge_btn.isHidden()

    def test_remove_btn_label_build_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._update_chapter_buttons()
        assert w._ch_remove_btn.text() == "Remove File"

    def test_remove_btn_label_edit_mode(self, win, tmp_path):
        w, _ = win
        _load_multi(w, tmp_path)
        w._mode = "edit"
        w._update_chapter_buttons()
        assert w._ch_remove_btn.text() == "Remove Chapter"

    def test_no_book_hides_merge(self, win):
        w, _ = win
        w._update_chapter_buttons()
        assert w._ch_merge_btn.isHidden()
