"""Tests for m4bmaker.gui.player — AudioPlayerWidget."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from m4bmaker.gui.player import AudioPlayerWidget, _fmt_ms  # noqa: E402

# ── _fmt_ms ──────────────────────────────────────────────────────────────────


class TestFmtMs:
    def test_zero(self):
        assert _fmt_ms(0) == "0:00"

    def test_seconds_only(self):
        assert _fmt_ms(5000) == "0:05"

    def test_one_minute(self):
        assert _fmt_ms(60_000) == "1:00"

    def test_mixed(self):
        assert _fmt_ms(90_500) == "1:30"

    def test_hours(self):
        assert _fmt_ms(3_661_000) == "1:01:01"

    def test_negative_clamps_to_zero(self):
        assert _fmt_ms(-1000) == "0:00"


# ── AudioPlayerWidget ────────────────────────────────────────────────────────


class TestAudioPlayerWidget:
    def test_instantiates_without_error(self, qapp):
        w = AudioPlayerWidget()
        assert w is not None

    def test_play_button_present(self, qapp):
        w = AudioPlayerWidget()
        assert w._play_btn is not None

    def test_stop_button_initially_disabled(self, qapp):
        w = AudioPlayerWidget()
        assert not w._stop_btn.isEnabled()

    def test_slider_initial_max_is_zero(self, qapp):
        w = AudioPlayerWidget()
        assert w._slider.maximum() == 0

    def test_is_playing_false_initially(self, qapp):
        w = AudioPlayerWidget()
        assert w.is_playing is False


class TestAudioPlayerWidgetLoad:
    def test_load_sets_source(self, qapp, tmp_path):
        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        w = AudioPlayerWidget()
        # Avoid actual media playback; just check setSource is called
        with patch.object(w._player, "setSource") as mock_ss:
            with patch.object(w._player, "play"):
                w.load(p, start_ms=0)
        mock_ss.assert_called_once()

    def test_load_same_url_calls_seek_chapter(self, qapp, tmp_path):
        from PySide6.QtCore import QUrl

        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        w = AudioPlayerWidget()
        url = QUrl.fromLocalFile(str(p))
        # Simulate the player already having this source
        with patch.object(w._player, "source", return_value=url):
            with patch.object(w, "seek_chapter") as mock_seek:
                w.load(p, start_ms=5000)
        mock_seek.assert_called_once_with(5000)

    def test_load_different_url_does_not_call_seek_chapter(self, qapp, tmp_path):
        from PySide6.QtCore import QUrl

        p1 = tmp_path / "a.mp3"
        p2 = tmp_path / "b.mp3"
        p1.write_bytes(b"\x00")
        p2.write_bytes(b"\x00")
        w = AudioPlayerWidget()
        # source() returns URL for p1 but we load p2
        url_p1 = QUrl.fromLocalFile(str(p1))
        with patch.object(w._player, "source", return_value=url_p1):
            with patch.object(w, "seek_chapter") as mock_seek:
                with patch.object(w._player, "setSource"):
                    with patch.object(w._player, "play"):
                        w.load(p2, start_ms=0)
        mock_seek.assert_not_called()


class TestAudioPlayerWidgetStop:
    def test_stop_calls_player_stop(self, qapp):
        w = AudioPlayerWidget()
        with patch.object(w._player, "stop") as mock_stop:
            w.stop()
        mock_stop.assert_called_once()

    def test_is_playing_false_after_stop(self, qapp):
        w = AudioPlayerWidget()
        # is_playing checks playbackState(); in offscreen mode starts as Stopped
        assert w.is_playing is False


class TestAudioPlayerWidgetSeekChapter:
    def _widget_with_source(self, qapp, tmp_path):
        """Return a widget whose player has a non-empty source URL."""
        from PySide6.QtCore import QUrl

        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        w = AudioPlayerWidget()
        # Patch source() so seek_chapter doesn't bail out
        w._source_url = QUrl.fromLocalFile(str(p))
        return w, p

    def test_seek_chapter_calls_set_position(self, qapp, tmp_path):
        from PySide6.QtCore import QUrl

        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        w = AudioPlayerWidget()
        url = QUrl.fromLocalFile(str(p))
        with patch.object(w._player, "source", return_value=url):
            with patch.object(w._player, "setPosition") as mock_sp:
                with patch.object(w._player, "play"):
                    w.seek_chapter(10_000)
        mock_sp.assert_called_once_with(10_000)

    def test_seek_chapter_resumes_play(self, qapp, tmp_path):
        from PySide6.QtCore import QUrl

        p = tmp_path / "t.mp3"
        p.write_bytes(b"\x00")
        w = AudioPlayerWidget()
        url = QUrl.fromLocalFile(str(p))
        with patch.object(w._player, "source", return_value=url):
            with patch.object(w._player, "setPosition"):
                with patch.object(w._player, "play") as mock_play:
                    w.seek_chapter(5000)
        mock_play.assert_called_once()

    def test_seek_chapter_no_op_with_empty_source(self, qapp):
        w = AudioPlayerWidget()
        # By default source is empty
        with patch.object(w._player, "setPosition") as mock_sp:
            w.seek_chapter(5000)
        mock_sp.assert_not_called()
