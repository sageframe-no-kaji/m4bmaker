"""Tests for m4bmaker.encoder — concat list writing and ffmpeg encode."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.encoder import (
    _format_ms,
    _progress_reader,
    _render_bar,
    encode,
    write_concat_list,
)

# ---------------------------------------------------------------------------
# write_concat_list
# ---------------------------------------------------------------------------


class TestWriteConcatList:
    def test_writes_all_files(self, tmp_path: Path) -> None:
        files = [tmp_path / f"track{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list(files, dest)
        content = dest.read_text()
        for f in files:
            assert f.resolve().as_posix() in content

    def test_format_is_file_single_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "track.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        line = dest.read_text().strip()
        assert line.startswith("file '")
        assert line.endswith("'")

    def test_absolute_paths_used(self, tmp_path: Path) -> None:
        f = tmp_path / "track.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        content = dest.read_text()
        assert f.resolve().as_posix() in content
        # Posix paths always use forward slashes
        assert "file '" in content

    def test_apostrophe_in_filename_escaped(self, tmp_path: Path) -> None:
        f = tmp_path / "it's a track.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        content = dest.read_text()
        assert "\\'" in content  # apostrophe escaped for ffmpeg

    def test_apostrophe_in_parent_directory_escaped(self, tmp_path: Path) -> None:
        # Regression test for issue #8: reporter's path was
        # "The Listener's Bible ESV/..." — apostrophe in the directory name,
        # not the filename.  The concat demuxer line must escape it the same way.
        parent = tmp_path / "The Listener's Bible ESV"
        parent.mkdir()
        f = parent / "track01.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        line = dest.read_text().strip()
        # Must be "file '<posix-path-with-escaped-apostrophe>'"
        assert line.startswith("file '")
        assert line.endswith("'")
        assert "\\'" in line  # apostrophe in directory component escaped
        # The filename itself must be unmodified (no apostrophe in it)
        assert "track01.mp3" in line

    def test_apostrophe_concat_line_exact_format(self, tmp_path: Path) -> None:
        # Verify the complete concat demuxer line format matches the ffmpeg spec:
        # file '<path-with-escaped-single-quotes>'
        parent = tmp_path / "O'Brien Audiobooks"
        parent.mkdir()
        f = parent / "O'Brien Chapter 1.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        line = dest.read_text().strip()
        posix = f.resolve().as_posix()
        expected_inner = posix.replace("'", "\\'")
        assert line == f"file '{expected_inner}'"

    def test_multiple_apostrophes_in_path_all_escaped(self, tmp_path: Path) -> None:
        parent = tmp_path / "it's troy's"
        parent.mkdir()
        f = parent / "can't stop.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        line = dest.read_text().strip()
        # Three apostrophes total across dir + filename — all must be escaped
        assert line.count("\\'") == 3

    def test_encode_passes_concat_path_as_list_arg(self, tmp_path: Path) -> None:
        # Apostrophe safety at the subprocess level: the concat file path is
        # passed as a list element, never interpolated into a shell string.
        # A path with an apostrophe must survive the round-trip through Popen.
        parent = tmp_path / "The Listener's Bible"
        parent.mkdir()
        concat = parent / "concat.txt"
        meta = parent / "meta.txt"
        output = parent / "out.m4b"
        for p in (concat, meta):
            p.write_bytes(b"\x00")

        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            return _popen_mock()

        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        cmd = captured[0]
        # The path containing the apostrophe must appear verbatim as its own
        # list element — no shell quoting, no mangling.
        assert str(concat) in cmd
        assert str(output) in cmd

    def test_space_in_path_preserved_quoted(self, tmp_path: Path) -> None:
        f = tmp_path / "my track 01.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        content = dest.read_text()
        assert "my track 01.mp3" in content

    def test_file_is_utf8(self, tmp_path: Path) -> None:
        f = tmp_path / "café.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        dest.read_bytes().decode("utf-8")  # must not raise


# ---------------------------------------------------------------------------
# Helpers for encode() tests
# ---------------------------------------------------------------------------


def _make_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    concat = tmp_path / "concat.txt"
    meta = tmp_path / "meta.txt"
    cover = tmp_path / "cover.jpg"
    output = tmp_path / "out.m4b"
    for p in (concat, meta, cover):
        p.write_bytes(b"\x00")
    return concat, meta, cover, output


def _popen_mock(returncode: int = 0, stderr: str = "") -> MagicMock:
    """Return a mock Popen process."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = iter([])
    proc.stderr = iter([stderr] if stderr else [])
    proc.wait.return_value = returncode
    return proc


# ---------------------------------------------------------------------------
# encode — command construction
# ---------------------------------------------------------------------------


class TestEncodeCommandConstruction:
    def _run_encode(
        self,
        tmp_path: Path,
        cover: Path | None = None,
        bitrate: str = "96k",
        channels: int = 1,
    ) -> list[str]:
        """Run encode() with a mocked Popen and return the captured command."""
        concat, meta, _cover, output = _make_paths(tmp_path)
        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            return _popen_mock()

        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
            encode(concat, meta, cover, output, bitrate, channels, "ffmpeg")

        return captured[0]

    def test_aac_codec_in_command(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path)
        assert "-c:a" in cmd
        assert "aac" in cmd

    def test_default_bitrate_96k(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path, bitrate="96k")
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "96k"

    def test_custom_bitrate_128k(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path, bitrate="128k")
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "128k"

    def test_mono_default_channels(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path, channels=1)
        idx = cmd.index("-ac")
        assert cmd[idx + 1] == "1"

    def test_stereo_channels(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path, channels=2)
        idx = cmd.index("-ac")
        assert cmd[idx + 1] == "2"

    def test_no_cover_excludes_map_2v(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path, cover=None)
        assert "2:v" not in cmd

    def test_cover_present_includes_map_2v(self, tmp_path: Path) -> None:
        _, _, cover, _ = _make_paths(tmp_path)
        cmd = self._run_encode(tmp_path, cover=cover)
        assert "2:v" in cmd
        assert "-disposition:v" in cmd
        assert "attached_pic" in cmd

    def test_cover_input_added_to_command(self, tmp_path: Path) -> None:
        _, _, cover, _ = _make_paths(tmp_path)
        cmd = self._run_encode(tmp_path, cover=cover)
        assert str(cover) in cmd

    def test_map_metadata_and_chapters_from_input_1(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path)
        assert "-map_metadata" in cmd
        idx_m = cmd.index("-map_metadata")
        assert cmd[idx_m + 1] == "1"
        assert "-map_chapters" in cmd
        idx_c = cmd.index("-map_chapters")
        assert cmd[idx_c + 1] == "1"

    def test_faststart_flag_present(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path)
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_output_path_last_arg(self, tmp_path: Path) -> None:
        _, _, _, output = _make_paths(tmp_path)
        concat, meta = tmp_path / "concat.txt", tmp_path / "meta.txt"
        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            return _popen_mock()

        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        assert captured[0][-1] == str(output)

    def test_progress_and_nostdin_flags_in_command(self, tmp_path: Path) -> None:
        cmd = self._run_encode(tmp_path)
        assert "-progress" in cmd
        idx = cmd.index("-progress")
        assert cmd[idx + 1] == "pipe:1"
        assert "-nostdin" in cmd


# ---------------------------------------------------------------------------
# encode — error handling
# ---------------------------------------------------------------------------


class TestEncodeErrorHandling:
    def test_nonzero_returncode_exits(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="ffmpeg: error details"),
        ):
            with pytest.raises(SystemExit, match="ffmpeg exited"):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

    def test_stderr_included_in_exit_message(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="unique_error_string_xyz"),
        ):
            with pytest.raises(SystemExit, match="unique_error_string_xyz"):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

    def test_ffmpeg_not_found_exits(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(SystemExit, match="not found"):
                encode(concat, meta, None, output, "96k", 1, "/nonexistent/ffmpeg")


# ---------------------------------------------------------------------------
# Progress bar helpers and live encoding progress
# ---------------------------------------------------------------------------


class TestProgressBar:
    def test_format_ms_under_one_hour(self) -> None:
        assert _format_ms(90000) == "0:01:30"

    def test_format_ms_over_one_hour(self) -> None:
        assert _format_ms(3661000) == "1:01:01"

    def test_format_ms_zero(self) -> None:
        assert _format_ms(0) == "0:00:00"

    def test_render_bar_empty(self) -> None:
        bar = _render_bar(0.0, width=4)
        assert bar == "[\u2591\u2591\u2591\u2591]"

    def test_render_bar_full(self) -> None:
        bar = _render_bar(1.0, width=4)
        assert bar == "[\u2588\u2588\u2588\u2588]"

    def test_render_bar_half(self) -> None:
        bar = _render_bar(0.5, width=4)
        assert bar == "[\u2588\u2588\u2591\u2591]"

    def test_render_bar_clamped_above_one(self) -> None:
        bar = _render_bar(2.0, width=4)
        assert bar == "[\u2588\u2588\u2588\u2588]"

    def test_progress_reader_parses_out_time_ms(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        lines = ["out_time_ms=30000000\n", "progress=continue\n"]
        done = threading.Event()
        with patch("sys.stdout.isatty", return_value=True):
            _progress_reader(iter(lines), 60000, done)
        captured = capsys.readouterr()
        # 30000000 µs → 30000 ms → 50% of 60000 ms
        assert "50%" in captured.out

    def test_progress_reader_ignores_non_time_lines(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Lines that are not out_time_ms= should be silently ignored."""
        lines = ["progress=continue\n", "speed=1.0x\n"]
        done = threading.Event()
        with patch("sys.stdout.isatty", return_value=True):
            _progress_reader(iter(lines), 60000, done)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_progress_reader_stops_when_done_set(self) -> None:
        """Reader exits early when done event is pre-set."""
        lines = ["out_time_ms=1000000\n"] * 100
        done = threading.Event()
        done.set()
        # Must return without processing all lines
        _progress_reader(iter(lines), 10000, done)  # should not hang

    def test_progress_reader_handles_invalid_int(self) -> None:
        """ValueError on bad int after out_time_ms= is silently skipped."""
        lines = ["out_time_ms=notanint\n"]
        done = threading.Event()
        # Must not raise
        _progress_reader(iter(lines), 60000, done)

    def test_encode_writes_100_percent_bar_on_tty_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When isatty=True, returncode=0, and total_ms>0, the 100% bar is written."""
        concat, meta, _, output = _make_paths(tmp_path)
        proc = _popen_mock(returncode=0)

        with (
            patch("m4bmaker.encoder.subprocess.Popen", return_value=proc),
            patch("sys.stdout.isatty", return_value=True),
        ):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg", total_ms=10000)
        captured = capsys.readouterr()
        assert "100%" in captured.out

    def test_encode_clears_line_on_tty_when_no_total_ms(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When isatty=True but total_ms=0, the clear-line branch runs."""
        concat, meta, _, output = _make_paths(tmp_path)
        proc = _popen_mock(returncode=0)

        with (
            patch("m4bmaker.encoder.subprocess.Popen", return_value=proc),
            patch("sys.stdout.isatty", return_value=True),
        ):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg", total_ms=0)
        captured = capsys.readouterr()
        # Clear-line sequence should have been written
        assert "\r" in captured.out
