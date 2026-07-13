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
from m4bmaker.errors import EncodeCancelled, M4BError

# ---------------------------------------------------------------------------
# write_concat_list
# ---------------------------------------------------------------------------
# NOTE: These tests verify that write_concat_list produces the expected string
# output, but they cannot verify that ffmpeg will actually parse that output
# correctly.  ffmpeg's concat demuxer has subtle quoting rules that differ
# across versions and are not fully representable by string inspection alone.
# If you change the escaping strategy here, run a live end-to-end test against
# a real directory whose name contains the characters you are changing.
# (See issue #8 for an example of unit tests that passed but the live encode
# failed because ffmpeg silently misinterpreted the quoting.)
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

    def test_format_is_file_unquoted(self, tmp_path: Path) -> None:
        f = tmp_path / "track.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        line = dest.read_text().strip()
        # Assert "file " not "file /" — on Windows paths start with "C:/",
        # so checking for a leading slash would fail in CI.
        assert line.startswith("file ")
        assert f.resolve().as_posix() in line
        assert "'" not in line  # no single-quote wrapping

    def test_absolute_paths_used(self, tmp_path: Path) -> None:
        f = tmp_path / "track.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        content = dest.read_text()
        assert f.resolve().as_posix() in content
        # Assert "file " not "file /" — on Windows paths start with "C:/",
        # so checking for a leading slash would fail in CI.
        # as_posix() converts backslashes to forward slashes for both platforms.
        assert content.startswith("file ")

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
        # Unquoted format: starts with "file ", no wrapping quotes
        assert line.startswith("file ")
        assert "\\'" in line  # apostrophe in directory component escaped
        # The filename itself must be unmodified (no apostrophe in it)
        assert "track01.mp3" in line

    def test_apostrophe_concat_line_exact_format(self, tmp_path: Path) -> None:
        # Verify the complete concat demuxer line format: unquoted path with
        # backslash-escaped apostrophes and spaces.
        parent = tmp_path / "O'Brien Audiobooks"
        parent.mkdir()
        f = parent / "O'Brien Chapter 1.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        line = dest.read_text().strip()
        posix = f.resolve().as_posix()
        escaped = (
            posix.replace("\\", "\\\\")
            .replace(" ", "\\ ")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("#", "\\#")
        )
        assert line == f"file {escaped}"

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
            Path(cmd[-1]).write_bytes(b"FAKE-M4B")
            return _popen_mock()

        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        cmd = captured[0]
        # The path containing the apostrophe must appear verbatim as its own
        # list element — no shell quoting, no mangling. The final arg is the
        # ".partial" sibling of output (atomic-encode staging path).
        assert str(concat) in cmd
        assert cmd[-1] == str(output) + ".partial"

    def test_space_in_path_backslash_escaped(self, tmp_path: Path) -> None:
        f = tmp_path / "my track 01.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        content = dest.read_text()
        assert "my\\ track\\ 01.mp3" in content  # spaces are backslash-escaped

    def test_file_is_utf8(self, tmp_path: Path) -> None:
        f = tmp_path / "café.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        dest.read_bytes().decode("utf-8")  # must not raise

    def test_newline_in_path_rejected(self, tmp_path: Path) -> None:
        """A resolved path containing a newline must raise M4BError rather
        than be written unescaped — the concat-demuxer escaping for
        newline/CR/tab is unverified (see module docstring warning)."""
        weird_dir = tmp_path / "weird\ndir"
        # Can't actually mkdir a name with a newline on most filesystems in
        # a portable way for this test, so construct the Path directly and
        # rely on write_concat_list's check operating on the resolved
        # string form rather than requiring the file to exist on disk.
        f = weird_dir / "track.mp3"
        dest = tmp_path / "concat.txt"
        with pytest.raises(M4BError, match="newline"):
            write_concat_list([f], dest)

    def test_carriage_return_in_path_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "weird\rdir" / "track.mp3"
        dest = tmp_path / "concat.txt"
        with pytest.raises(M4BError):
            write_concat_list([f], dest)

    def test_tab_in_path_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "weird\tdir" / "track.mp3"
        dest = tmp_path / "concat.txt"
        with pytest.raises(M4BError):
            write_concat_list([f], dest)

    def test_rejected_path_error_names_the_file(self, tmp_path: Path) -> None:
        f = tmp_path / "weird\ndir" / "track.mp3"
        dest = tmp_path / "concat.txt"
        with pytest.raises(M4BError, match="rename"):
            write_concat_list([f], dest)


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


def _popen_factory(returncode: int = 0, stderr: str = ""):
    """Return a Popen side_effect that writes the ``.partial`` output file.

    encode() writes to a sibling ``<output>.partial`` path and atomically
    replaces *output* with it on success via os.replace — a real ffmpeg
    process creates that file, so the mock must too, or os.replace raises
    FileNotFoundError. The partial path is always the mocked command's last
    argument.
    """

    def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
        if returncode == 0:
            Path(cmd[-1]).write_bytes(b"FAKE-M4B")
        return _popen_mock(returncode=returncode, stderr=stderr)

    return _fake_popen


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
            Path(cmd[-1]).write_bytes(b"FAKE-M4B")
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

    def test_explicit_mp4_muxer_flag_present(self, tmp_path: Path) -> None:
        """Regression test: the ".partial" staging suffix (e.g. "out.m4b.partial")
        defeats ffmpeg's extension-based muxer auto-detection — confirmed live
        with a real ffmpeg binary, which failed with "Unable to choose an
        output format" before "-f mp4" was added. Must never regress.

        The command also has an earlier "-f concat" (input demuxer), so this
        checks the LAST "-f" flag, which sets the output muxer.
        """
        cmd = self._run_encode(tmp_path)
        last_f_idx = len(cmd) - 1 - cmd[::-1].index("-f")
        assert cmd[last_f_idx + 1] == "mp4"

    def test_output_path_last_arg(self, tmp_path: Path) -> None:
        _, _, _, output = _make_paths(tmp_path)
        concat, meta = tmp_path / "concat.txt", tmp_path / "meta.txt"
        captured: list[list[str]] = []

        def _fake_popen(cmd: list[str], **_: object) -> MagicMock:
            captured.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"FAKE-M4B")
            return _popen_mock()

        with patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_popen):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        # Final arg is the ".partial" staging path, not output itself —
        # encode() renames it onto output only after returncode 0.
        assert captured[0][-1] == str(output) + ".partial"
        assert output.exists()

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
    def test_nonzero_returncode_raises_m4berror(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="ffmpeg: error details"),
        ):
            with pytest.raises(M4BError, match="ffmpeg exited"):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

    def test_stderr_included_in_error_message(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="unique_error_string_xyz"),
        ):
            with pytest.raises(M4BError, match="unique_error_string_xyz"):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

    def test_ffmpeg_not_found_raises_m4berror(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(M4BError, match="not found"):
                encode(concat, meta, None, output, "96k", 1, "/nonexistent/ffmpeg")

    def test_failed_encode_does_not_leave_partial_file(self, tmp_path: Path) -> None:
        """A failed encode must clean up the .partial staging file."""
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="boom"),
        ):
            with pytest.raises(M4BError):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        assert not output.with_name(output.name + ".partial").exists()

    def test_failed_reencode_preserves_existing_good_output(
        self, tmp_path: Path
    ) -> None:
        """A pre-existing good file at output must survive a failed re-encode."""
        concat, meta, _, output = _make_paths(tmp_path)
        output.write_bytes(b"PREVIOUS-GOOD-M4B")

        with patch(
            "m4bmaker.encoder.subprocess.Popen",
            return_value=_popen_mock(returncode=1, stderr="boom"),
        ):
            with pytest.raises(M4BError):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        assert output.read_bytes() == b"PREVIOUS-GOOD-M4B"

    def test_cancel_event_raises_encode_cancelled(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)
        cancel_event = threading.Event()
        cancel_event.set()  # already cancelled before encode() polls

        proc = _popen_mock(returncode=-9)
        proc.poll.return_value = None  # still "running" until killed

        with patch("m4bmaker.encoder.subprocess.Popen", return_value=proc):
            with pytest.raises(EncodeCancelled, match="cancelled"):
                encode(
                    concat,
                    meta,
                    None,
                    output,
                    "96k",
                    1,
                    "ffmpeg",
                    cancel_event=cancel_event,
                )

        proc.kill.assert_called_once()
        assert not output.with_name(output.name + ".partial").exists()

    def test_cancel_event_does_not_touch_existing_output(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)
        output.write_bytes(b"PREVIOUS-GOOD-M4B")
        cancel_event = threading.Event()
        cancel_event.set()

        proc = _popen_mock(returncode=-9)
        proc.poll.return_value = None

        with patch("m4bmaker.encoder.subprocess.Popen", return_value=proc):
            with pytest.raises(EncodeCancelled):
                encode(
                    concat,
                    meta,
                    None,
                    output,
                    "96k",
                    1,
                    "ffmpeg",
                    cancel_event=cancel_event,
                )

        assert output.read_bytes() == b"PREVIOUS-GOOD-M4B"

    def test_keyboard_interrupt_kills_child_and_cleans_partial(
        self, tmp_path: Path
    ) -> None:
        """A KeyboardInterrupt propagating out of the poll loop must kill the
        ffmpeg child, remove the partial file, and re-raise — never silently
        swallowed, never leaving an orphaned process or partial file."""
        concat, meta, _, output = _make_paths(tmp_path)

        proc = _popen_mock(returncode=0)
        proc.poll.side_effect = KeyboardInterrupt

        with patch("m4bmaker.encoder.subprocess.Popen", return_value=proc):
            with pytest.raises(KeyboardInterrupt):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        proc.kill.assert_called_once()
        assert not output.with_name(output.name + ".partial").exists()

    def test_keyboard_interrupt_preserves_existing_good_output(
        self, tmp_path: Path
    ) -> None:
        concat, meta, _, output = _make_paths(tmp_path)
        output.write_bytes(b"PREVIOUS-GOOD-M4B")

        proc = _popen_mock(returncode=0)
        proc.poll.side_effect = KeyboardInterrupt

        with patch("m4bmaker.encoder.subprocess.Popen", return_value=proc):
            with pytest.raises(KeyboardInterrupt):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

        assert output.read_bytes() == b"PREVIOUS-GOOD-M4B"


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

        with (
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_popen_factory()),
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

        with (
            patch("m4bmaker.encoder.subprocess.Popen", side_effect=_popen_factory()),
            patch("sys.stdout.isatty", return_value=True),
        ):
            encode(concat, meta, None, output, "96k", 1, "ffmpeg", total_ms=0)
        captured = capsys.readouterr()
        # Clear-line sequence should have been written
        assert "\r" in captured.out
