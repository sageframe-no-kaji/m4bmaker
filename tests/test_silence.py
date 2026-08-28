"""Tests for m4bmaker.silence — silence detection and chapter derivation (#23).

The parser and the derivation rules are tested against captured ffmpeg output;
one integration test at the end runs real ffmpeg over generated audio, because
a parser that passes on a hand-written sample and fails on the real stream is
the failure mode that matters here.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.encoder import write_concat_list
from m4bmaker.errors import EncodeCancelled, M4BError
from m4bmaker.silence import (
    DEFAULT_MIN_CHAPTER,
    detect_silence,
    parse_silence_spans,
    silence_to_chapters,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Verbatim ffmpeg 8.1 stderr for three tones separated by two 2s silences.
REAL_STDERR = """\
  Stream #0:0: Audio: mp3 (mp3float), 44100 Hz, mono, fltp, 64 kb/s
Stream mapping:
  Stream #0:0 -> #0:0 (mp3 (mp3float) -> pcm_s16le (native))
Press [q] to stop, [?] for help
Output #0, null, to 'pipe:':
[Parsed_silencedetect_0 @ 0x7f0] silence_start: 4.999909
[Parsed_silencedetect_0 @ 0x7f0] silence_end: 7.000091 | silence_duration: 2.000181
[Parsed_silencedetect_0 @ 0x7f0] silence_start: 11.999932
[Parsed_silencedetect_0 @ 0x7f0] silence_end: 14.000068 | silence_duration: 2.000136
[out#0/null @ 0x7f1] video:0KiB audio:1637KiB subtitle:0KiB other streams:0KiB
size=N/A time=00:00:19.00 bitrate=N/A speed=1.88e+03x elapsed=0:00:00.01
"""


def _popen_mock(returncode: int = 0, stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = iter([])
    proc.stderr = iter(stderr.splitlines(keepends=True))
    proc.wait.return_value = returncode
    return proc


def _concat(tmp_path: Path) -> Path:
    path = tmp_path / "concat.txt"
    path.write_text("file /nonexistent.mp3\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_silence_spans
# ---------------------------------------------------------------------------


class TestParseSilenceSpans:
    def test_parses_realistic_stderr(self) -> None:
        spans = parse_silence_spans(REAL_STDERR)
        assert spans == [(4.999909, 7.000091), (11.999932, 14.000068)]

    def test_no_silence_returns_empty(self) -> None:
        assert parse_silence_spans("Stream mapping:\nsize=N/A time=00:00:10.00\n") == []

    def test_unterminated_final_start_closes_at_eof(self) -> None:
        # The book ends mid-silence — common, since books often end on a fade.
        stderr = (
            "[Parsed_silencedetect_0 @ 0x0] silence_start: 4.0\n"
            "[Parsed_silencedetect_0 @ 0x0] silence_end: 7.0 | silence_duration: 3.0\n"
            "[Parsed_silencedetect_0 @ 0x0] silence_start: 17.5\n"
            "size=N/A time=00:00:19.00 bitrate=N/A\n"
        )
        assert parse_silence_spans(stderr) == [(4.0, 7.0), (17.5, 19.0)]

    def test_unterminated_start_dropped_when_eof_unknown(self) -> None:
        # No time= line at all: the span cannot be placed, so it is not guessed.
        stderr = "[Parsed_silencedetect_0 @ 0x0] silence_start: 4.0\n"
        assert parse_silence_spans(stderr) == []

    def test_interleaved_log_lines_do_not_break_pairing(self) -> None:
        stderr = (
            "[Parsed_silencedetect_0 @ 0x0] silence_start: 4.0\n"
            "[mp3 @ 0x0] some unrelated warning\n"
            "size=N/A time=00:00:05.00 bitrate=N/A\n"
            "[Parsed_silencedetect_0 @ 0x0] silence_end: 7.0 | silence_duration: 3.0\n"
            "size=N/A time=00:00:19.00 bitrate=N/A\n"
        )
        assert parse_silence_spans(stderr) == [(4.0, 7.0)]

    def test_hour_long_timestamps_parse(self) -> None:
        stderr = (
            "[Parsed_silencedetect_0 @ 0x0] silence_start: 3700.5\n"
            "size=N/A time=01:02:00.25 bitrate=N/A\n"
        )
        assert parse_silence_spans(stderr) == [(3700.5, 3720.25)]


# ---------------------------------------------------------------------------
# detect_silence
# ---------------------------------------------------------------------------


class TestDetectSilence:
    def test_returns_parsed_spans(self, tmp_path: Path) -> None:
        with patch(
            "m4bmaker.silence.subprocess.Popen",
            return_value=_popen_mock(stderr=REAL_STDERR),
        ):
            spans = detect_silence(_concat(tmp_path), "ffmpeg")
        assert spans == [(4.999909, 7.000091), (11.999932, 14.000068)]

    def test_command_uses_concat_input_and_silencedetect(self, tmp_path: Path) -> None:
        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            return _popen_mock(stderr=REAL_STDERR)

        with patch("m4bmaker.silence.subprocess.Popen", side_effect=_fake_popen):
            detect_silence(_concat(tmp_path), "ffmpeg")

        cmd = captured[0]
        # The input is the concat list, so timestamps are book-relative.
        assert cmd[cmd.index("-f") + 1] == "concat"
        assert "-safe" in cmd
        af = cmd[cmd.index("-af") + 1]
        assert af.startswith("silencedetect=")
        assert cmd[-1] == "-"

    def test_threshold_and_duration_reach_the_filter(self, tmp_path: Path) -> None:
        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            return _popen_mock(stderr=REAL_STDERR)

        with patch("m4bmaker.silence.subprocess.Popen", side_effect=_fake_popen):
            detect_silence(
                _concat(tmp_path), "ffmpeg", threshold_db=-45.0, min_duration=3.0
            )

        af = captured[0][captured[0].index("-af") + 1]
        assert "noise=-45.0dB" in af
        assert "d=3.0" in af

    def test_raises_on_nonzero_returncode(self, tmp_path: Path) -> None:
        with patch(
            "m4bmaker.silence.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="boom"),
        ):
            with pytest.raises(M4BError, match="silence detection"):
                detect_silence(_concat(tmp_path), "ffmpeg")

    def test_raises_when_ffmpeg_missing(self, tmp_path: Path) -> None:
        with patch(
            "m4bmaker.silence.subprocess.Popen", side_effect=FileNotFoundError()
        ):
            with pytest.raises(M4BError, match="ffmpeg executable not found"):
                detect_silence(_concat(tmp_path), "nope")

    def test_cancellation_raises_encode_cancelled(self, tmp_path: Path) -> None:
        cancel = threading.Event()
        cancel.set()
        proc = _popen_mock(stderr=REAL_STDERR)
        proc.poll.return_value = None
        with patch("m4bmaker.silence.subprocess.Popen", return_value=proc):
            with pytest.raises(EncodeCancelled):
                detect_silence(_concat(tmp_path), "ffmpeg", cancel_event=cancel)
        proc.kill.assert_called_once()

    def test_interrupt_kills_ffmpeg_and_propagates(self, tmp_path: Path) -> None:
        proc = _popen_mock(stderr=REAL_STDERR)
        proc.poll.return_value = None
        with (
            patch("m4bmaker.silence.subprocess.Popen", return_value=proc),
            patch("m4bmaker.silence.time.sleep", side_effect=KeyboardInterrupt),
        ):
            with pytest.raises(KeyboardInterrupt):
                detect_silence(_concat(tmp_path), "ffmpeg")
        proc.kill.assert_called_once()

    def test_progress_reports_seconds_analysed(self, tmp_path: Path) -> None:
        # progress_callback receives seconds of audio analysed, not a fraction:
        # detect_silence does not know the book's total duration.
        proc = _popen_mock(stderr=REAL_STDERR)
        proc.stdout = iter(["out_time_ms=5000000\n", "out_time_ms=10000000\n"])
        seen: list[float] = []
        with patch("m4bmaker.silence.subprocess.Popen", return_value=proc):
            detect_silence(_concat(tmp_path), "ffmpeg", progress_callback=seen.append)
        assert seen == [5.0, 10.0]

    def test_malformed_progress_lines_are_skipped(self, tmp_path: Path) -> None:
        proc = _popen_mock(stderr=REAL_STDERR)
        proc.stdout = iter(["out_time_ms=notanumber\n", "out_time_ms=2000000\n"])
        seen: list[float] = []
        with patch("m4bmaker.silence.subprocess.Popen", return_value=proc):
            detect_silence(_concat(tmp_path), "ffmpeg", progress_callback=seen.append)
        assert seen == [2.0]


# ---------------------------------------------------------------------------
# silence_to_chapters
# ---------------------------------------------------------------------------


class TestSilenceToChapters:
    def test_no_spans_gives_one_chapter_at_zero(self) -> None:
        chapters = silence_to_chapters([], total_duration=600.0)
        assert len(chapters) == 1
        assert chapters[0].start_time == 0.0

    def test_first_chapter_starts_at_zero_despite_leading_silence(self) -> None:
        # The book opens with 5s of room tone; chapter 1 still starts at 0.0.
        chapters = silence_to_chapters([(0.0, 5.0), (100.0, 103.0)], 300.0)
        assert chapters[0].start_time == 0.0

    def test_chapter_starts_where_silence_ends(self) -> None:
        # The pause belongs to the chapter before it, the way a reader hears it.
        chapters = silence_to_chapters([(100.0, 103.5)], total_duration=300.0)
        assert [c.start_time for c in chapters] == [0.0, 103.5]

    def test_short_chapter_boundary_is_dropped(self) -> None:
        # A dramatic pause 4s in must not become a four-second chapter.
        chapters = silence_to_chapters([(4.0, 5.0), (100.0, 102.0)], 300.0)
        assert [c.start_time for c in chapters] == [0.0, 102.0]

    def test_short_boundaries_measured_against_last_kept(self) -> None:
        # A run of close pauses collapses rather than accumulating: 40 is kept,
        # 50 and 60 are each within 30s of it, 100 clears it again.
        chapters = silence_to_chapters(
            [(38.0, 40.0), (48.0, 50.0), (58.0, 60.0), (98.0, 100.0)], 300.0
        )
        assert [c.start_time for c in chapters] == [0.0, 40.0, 100.0]

    def test_boundary_too_close_to_the_end_is_dropped(self) -> None:
        chapters = silence_to_chapters([(295.0, 297.0)], total_duration=300.0)
        assert [c.start_time for c in chapters] == [0.0]

    def test_unknown_total_duration_keeps_boundaries(self) -> None:
        # total_duration 0.0 means "not known" — it must not read as "the book
        # ended at zero" and cut every boundary.
        chapters = silence_to_chapters([(100.0, 102.0)], total_duration=0.0)
        assert [c.start_time for c in chapters] == [0.0, 102.0]

    def test_titles_are_numbered_in_order(self) -> None:
        chapters = silence_to_chapters([(100.0, 102.0), (200.0, 202.0)], 600.0)
        assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]
        assert [c.index for c in chapters] == [1, 2, 3]

    def test_start_times_increase_monotonically(self) -> None:
        chapters = silence_to_chapters(
            [(100.0, 102.0), (200.0, 202.0), (300.0, 302.0)], 600.0
        )
        times = [c.start_time for c in chapters]
        assert times == sorted(times)
        assert len(set(times)) == len(times)

    def test_chapters_carry_no_source_file(self) -> None:
        # These are positions in the assembled book, not per-file markers.
        chapters = silence_to_chapters([(100.0, 102.0)], 600.0)
        assert all(c.source_file is None for c in chapters)

    def test_custom_min_chapter_length_is_honoured(self) -> None:
        spans = [(10.0, 12.0), (20.0, 22.0)]
        assert len(silence_to_chapters(spans, 100.0, min_chapter_length=5.0)) == 3
        assert len(silence_to_chapters(spans, 100.0, min_chapter_length=30.0)) == 1

    def test_default_min_chapter_is_thirty_seconds(self) -> None:
        assert DEFAULT_MIN_CHAPTER == 30.0


# ---------------------------------------------------------------------------
# Integration — real ffmpeg over generated audio
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestDetectSilenceIntegration:
    def _make_book(self, tmp_path: Path) -> tuple[Path, float]:
        """Three 35s tones separated by 2s of true silence. Returns concat, total.

        The tones are longer than the 30s default minimum chapter length on
        purpose: shorter ones would be correctly collapsed into a single
        chapter, and the test would be asserting the wrong thing.
        """
        ffmpeg = shutil.which("ffmpeg")
        assert ffmpeg is not None
        parts: list[Path] = []
        for i, freq in enumerate((400, 600, 800)):
            tone = tmp_path / f"tone{i}.wav"
            subprocess.run(
                [
                    ffmpeg,
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={freq}:duration=35",
                    "-ac",
                    "1",
                    str(tone),
                    "-y",
                ],
                check=True,
            )
            if parts:
                gap = tmp_path / f"gap{i}.wav"
                subprocess.run(
                    [
                        ffmpeg,
                        "-loglevel",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=44100:cl=mono:d=2",
                        "-ac",
                        "1",
                        str(gap),
                        "-y",
                    ],
                    check=True,
                )
                parts.append(gap)
            parts.append(tone)

        concat = tmp_path / "concat.txt"
        write_concat_list(parts, concat)
        return concat, 35 * 3 + 2 * 2

    def test_detects_both_silences(self, tmp_path: Path) -> None:
        concat, _total = self._make_book(tmp_path)
        ffmpeg = shutil.which("ffmpeg")
        assert ffmpeg is not None
        spans = detect_silence(concat, ffmpeg)
        assert len(spans) == 2, f"expected 2 silence spans, got {spans}"

    def test_derives_three_chapters_at_the_defaults(self, tmp_path: Path) -> None:
        concat, total = self._make_book(tmp_path)
        ffmpeg = shutil.which("ffmpeg")
        assert ffmpeg is not None
        chapters = silence_to_chapters(detect_silence(concat, ffmpeg), total)
        assert len(chapters) == 3, f"expected 3 chapters, got {chapters}"
        # Chapter 2 starts when the first gap ends: 35s tone + 2s gap.
        assert chapters[1].start_time == pytest.approx(37.0, abs=0.2)
        assert chapters[2].start_time == pytest.approx(74.0, abs=0.2)

    def test_silent_free_audio_yields_one_chapter(self, tmp_path: Path) -> None:
        ffmpeg = shutil.which("ffmpeg")
        assert ffmpeg is not None
        tone = tmp_path / "solid.wav"
        subprocess.run(
            [
                ffmpeg,
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=40",
                "-ac",
                "1",
                str(tone),
                "-y",
            ],
            check=True,
        )
        concat = tmp_path / "concat.txt"
        write_concat_list([tone], concat)
        assert detect_silence(concat, ffmpeg) == []
        assert len(silence_to_chapters([], 40.0)) == 1
