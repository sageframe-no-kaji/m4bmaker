"""ASIN lookup consent gate and wiring — closes #4.

The property that matters most here is negative: **no network request may
happen before the user has consented**, and declining must make none. Those are
asserted by patching the worker class and proving it was never constructed.

See tests/gui/test_window.py's module docstring for why Qt tests run offscreen.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from m4bmaker.audnexus import AudnexusBook  # noqa: E402
from m4bmaker.gui import prefs as _prefs  # noqa: E402
from m4bmaker.gui.window import MainWindow  # noqa: E402
from m4bmaker.models import Book, BookMetadata, Chapter  # noqa: E402

QMB = "m4bmaker.gui.window.QMessageBox"
DIALOG = "m4bmaker.gui.window.CoverChoiceDialog"
WORKER = "m4bmaker.gui.window.LookupWorker"
PREF_GET = "m4bmaker.gui.window._prefs_get"
PREF_SET = "m4bmaker.gui.window._prefs_set"

ASIN = "B017V4IM1G"


def _make_book(tmp_path: Path) -> Book:
    f = tmp_path / "01.mp3"
    f.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
    return Book(
        files=[f],
        chapters=[Chapter(index=1, start_time=0.0, title="Ch 1", source_file=f)],
        metadata=BookMetadata(title="T", author="A", narrator="N"),
        cover=None,
        total_duration=600.0,
    )


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path_factory):
    """Never touch the real preferences file from tests."""
    path = tmp_path_factory.mktemp("prefs") / "prefs.json"
    with patch.object(_prefs, "_prefs_path", return_value=path):
        yield


@pytest.fixture
def win(qapp, tmp_path):
    w = MainWindow()
    w.show()
    yield w, tmp_path
    w._is_busy = lambda: False  # type: ignore[method-assign]
    w.close()
    w.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()


def _loaded(win, tmp_path):
    w, _ = win
    w._apply_book_to_ui(_make_book(tmp_path))
    w._asin_edit.setText(ASIN)
    return w


# ── consent gate ──────────────────────────────────────────────────────────────


class TestConsentGate:
    def test_no_request_before_consent(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        with (
            patch(PREF_GET, return_value=False),
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.No),
            patch(WORKER) as worker,
        ):
            w._on_asin_lookup()
        worker.assert_not_called()

    def test_declining_makes_no_request(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        with (
            patch(PREF_GET, return_value=False),
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.No),
            patch(WORKER) as worker,
            patch(PREF_SET) as pref_set,
        ):
            w._on_asin_lookup()
        worker.assert_not_called()
        # Declining must not record consent.
        assert not any(
            c.args[0] == "audnexus_consented" for c in pref_set.call_args_list
        )

    def test_first_lookup_asks(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        with (
            patch(PREF_GET, return_value=False),
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.No) as ask,
            patch(WORKER),
        ):
            w._on_asin_lookup()
        ask.assert_called_once()

    def test_consent_dialog_names_what_is_sent(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        with (
            patch(PREF_GET, return_value=False),
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.No) as ask,
            patch(WORKER),
        ):
            w._on_asin_lookup()
        text = ask.call_args[0][2]
        assert "ASIN" in text
        # It must be explicit about what does NOT leave the machine.
        assert "filenames" in text.lower()
        assert "audio" in text.lower()
        # And it discloses the cover-image fetch rather than leaving it silent.
        assert "cover" in text.lower()

    def test_accepting_records_consent_and_starts_the_worker(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        started = MagicMock()
        started.isRunning.return_value = True
        with (
            patch(PREF_GET, return_value=False),
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.Yes),
            patch(WORKER, return_value=started) as worker,
            patch(PREF_SET) as pref_set,
        ):
            w._on_asin_lookup()
        worker.assert_called_once()
        started.start.assert_called_once()
        pref_set.assert_any_call("audnexus_consented", True)
        w._lookup_worker = None

    def test_consent_is_not_asked_twice(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        started = MagicMock()
        started.isRunning.return_value = True
        with (
            patch(PREF_GET, return_value=True),
            patch(f"{QMB}.question") as ask,
            patch(WORKER, return_value=started),
        ):
            w._on_asin_lookup()
        ask.assert_not_called()
        w._lookup_worker = None

    def test_empty_asin_makes_no_request(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        w._asin_edit.setText("   ")
        with patch(WORKER) as worker, patch(f"{QMB}.question") as ask:
            w._on_asin_lookup()
        worker.assert_not_called()
        ask.assert_not_called()

    def test_no_book_makes_no_request(self, win):
        w, _ = win
        w._asin_edit.setText(ASIN)
        with patch(WORKER) as worker:
            w._on_asin_lookup()
        worker.assert_not_called()


# ── the menu toggle ───────────────────────────────────────────────────────────


class TestConsentToggle:
    def test_toggle_exists_and_is_checkable(self, win):
        w, _ = win
        assert w._lookup_action.isCheckable()

    def test_toggle_writes_the_preference(self, win):
        w, _ = win
        with patch(PREF_SET) as pref_set:
            w._toggle_audnexus_lookup(True)
        pref_set.assert_called_once_with("audnexus_consented", True)

    def test_revoking_makes_the_next_lookup_ask_again(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        with patch(PREF_SET):
            w._toggle_audnexus_lookup(False)
        with (
            patch(PREF_GET, return_value=False),
            patch(f"{QMB}.question", return_value=QMessageBox.StandardButton.No) as ask,
            patch(WORKER) as worker,
        ):
            w._on_asin_lookup()
        ask.assert_called_once()
        worker.assert_not_called()

    def test_defaults_are_correct(self):
        assert _prefs._DEFAULTS["audnexus_consented"] is False
        assert _prefs._DEFAULTS["audnexus_region"] == "us"


# ── region preference ─────────────────────────────────────────────────────────


class TestRegionPreference:
    def test_region_reaches_the_worker(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        started = MagicMock()
        started.isRunning.return_value = True

        def _pref(key):
            return {"audnexus_consented": True, "audnexus_region": "de"}.get(key)

        with (
            patch(PREF_GET, side_effect=_pref),
            patch(WORKER, return_value=started) as worker,
        ):
            w._on_asin_lookup()
        assert worker.call_args.kwargs["region"] == "de"
        w._lookup_worker = None

    def test_missing_region_falls_back_to_us(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        started = MagicMock()
        started.isRunning.return_value = True

        def _pref(key):
            return True if key == "audnexus_consented" else None

        with (
            patch(PREF_GET, side_effect=_pref),
            patch(WORKER, return_value=started) as worker,
        ):
            w._on_asin_lookup()
        assert worker.call_args.kwargs["region"] == "us"
        w._lookup_worker = None


# ── results ───────────────────────────────────────────────────────────────────


class TestLookupResults:
    def _book(self) -> AudnexusBook:
        return AudnexusBook(
            asin=ASIN,
            title="Fetched Title",
            author="Fetched Author",
            narrator="Fetched Narrator",
            genre="Fetched Genre",
            cover_url="https://example.invalid/c.jpg",
        )

    def test_fields_are_populated(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        w._on_lookup_finished(self._book(), [], "done.", "")
        assert w._title_edit.text() == "Fetched Title"
        assert w._author_edit.text() == "Fetched Author"
        assert w._narrator_edit.text() == "Fetched Narrator"
        assert w._genre_edit.text() == "Fetched Genre"

    def test_absent_fields_do_not_blank_existing_values(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        w._title_edit.setText("Mine")
        w._on_lookup_finished(AudnexusBook(asin=ASIN), [], "done.", "")
        assert w._title_edit.text() == "Mine"

    def test_chapters_populate_the_table(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        chapters = [
            Chapter(index=1, start_time=0.0, title="One", source_file=None),
            Chapter(index=2, start_time=90.0, title="Two", source_file=None),
        ]
        w._on_lookup_finished(self._book(), chapters, "applied.", "")
        assert w._chapter_table.rowCount() == 2
        assert [c.title for c in w._book.chapters] == ["One", "Two"]

    def test_the_message_reaches_the_status_line(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        w._on_lookup_finished(self._book(), [], "Applied 19 chapter name(s).", "")
        assert "Applied 19 chapter name(s)." in w._status_label.text()

    def test_nothing_is_written_to_disk(self, win, tmp_path):
        # Lookup populates fields for review; the user still presses Convert.
        w = _loaded(win, tmp_path)
        before = sorted(p.name for p in tmp_path.iterdir())
        w._on_lookup_finished(self._book(), [], "done.", "")
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    def test_cover_is_applied_when_there_is_none(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8\xff\xe0")
        with patch(DIALOG) as dialog:
            w._on_lookup_finished(self._book(), [], "done.", str(cover))
        # Nothing to compare against, so nothing to ask about.
        dialog.assert_not_called()
        assert w._cover_widget.cover_path() == cover

    def test_existing_cover_prompts_rather_than_being_overwritten(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        mine = tmp_path / "mine.jpg"
        mine.write_bytes(b"\xff\xd8\xff\xe0")
        w._cover_widget.set_cover(mine)
        other = tmp_path / "theirs.jpg"
        other.write_bytes(b"\xff\xd8\xff\xe0")
        instance = MagicMock()
        instance.chosen.return_value = mine
        with patch(DIALOG, return_value=instance) as dialog:
            w._on_lookup_finished(self._book(), [], "done.", str(other))
        dialog.assert_called_once()
        assert w._cover_widget.cover_path() == mine

    def test_error_shows_a_dialog(self, win, tmp_path):
        w = _loaded(win, tmp_path)
        with patch(f"{QMB}.critical") as crit:
            w._on_lookup_error("no such ASIN in region 'us'")
        crit.assert_called_once()
        assert "no such ASIN in region 'us'" in crit.call_args[0]
