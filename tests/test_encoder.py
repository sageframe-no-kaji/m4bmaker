"""Tests for m4bmaker.encoder — concat list writing and ffmpeg encode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.encoder import encode, write_concat_list

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
            assert str(f.resolve()) in content

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
        assert str(f.resolve()) in content
        # Resolve makes it absolute; no relative component
        assert content.startswith("file '/")

    def test_apostrophe_in_path_escaped(self, tmp_path: Path) -> None:
        f = tmp_path / "it's a track.mp3"
        f.write_bytes(b"\x00")
        dest = tmp_path / "concat.txt"
        write_concat_list([f], dest)
        content = dest.read_text()
        assert "'\\''" in content  # the ffmpeg escape sequence

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
# encode — command construction
# ---------------------------------------------------------------------------


def _make_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    concat = tmp_path / "concat.txt"
    meta = tmp_path / "meta.txt"
    cover = tmp_path / "cover.jpg"
    output = tmp_path / "out.m4b"
    for p in (concat, meta, cover):
        p.write_bytes(b"\x00")
    return concat, meta, cover, output


class TestEncodeCommandConstruction:
    def _run_encode(
        self,
        tmp_path: Path,
        cover: Path | None = None,
        bitrate: str = "96k",
        channels: int = 1,
    ) -> list[list[str]]:
        """Run encode() with a mocked subprocess.run and capture all calls."""
        concat, meta, _cover, output = _make_paths(tmp_path)
        calls: list[list[str]] = []

        def _fake_run(cmd: list[str], **_: object) -> MagicMock:
            calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("m4bmaker.encoder.subprocess.run", side_effect=_fake_run):
            encode(concat, meta, cover, output, bitrate, channels, "ffmpeg")

        return calls

    def test_aac_codec_in_command(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path)
        cmd = calls[0]
        assert "-c:a" in cmd
        assert "aac" in cmd

    def test_default_bitrate_96k(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path, bitrate="96k")
        cmd = calls[0]
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "96k"

    def test_custom_bitrate_128k(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path, bitrate="128k")
        cmd = calls[0]
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "128k"

    def test_mono_default_channels(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path, channels=1)
        cmd = calls[0]
        idx = cmd.index("-ac")
        assert cmd[idx + 1] == "1"

    def test_stereo_channels(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path, channels=2)
        cmd = calls[0]
        idx = cmd.index("-ac")
        assert cmd[idx + 1] == "2"

    def test_no_cover_excludes_map_2v(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path, cover=None)
        cmd = calls[0]
        assert "2:v" not in cmd

    def test_cover_present_includes_map_2v(self, tmp_path: Path) -> None:
        _, _, cover, _ = _make_paths(tmp_path)
        calls = self._run_encode(tmp_path, cover=cover)
        cmd = calls[0]
        assert "2:v" in cmd
        assert "-disposition:v" in cmd
        assert "attached_pic" in cmd

    def test_cover_input_added_to_command(self, tmp_path: Path) -> None:
        _, _, cover, _ = _make_paths(tmp_path)
        calls = self._run_encode(tmp_path, cover=cover)
        cmd = calls[0]
        assert str(cover) in cmd

    def test_map_metadata_and_chapters_from_input_1(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path)
        cmd = calls[0]
        assert "-map_metadata" in cmd
        idx_m = cmd.index("-map_metadata")
        assert cmd[idx_m + 1] == "1"
        assert "-map_chapters" in cmd
        idx_c = cmd.index("-map_chapters")
        assert cmd[idx_c + 1] == "1"

    def test_faststart_flag_present(self, tmp_path: Path) -> None:
        calls = self._run_encode(tmp_path)
        cmd = calls[0]
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_output_path_last_arg(self, tmp_path: Path) -> None:
        _, _, _, output = _make_paths(tmp_path)
        concat, meta = tmp_path / "concat.txt", tmp_path / "meta.txt"

        def _fake_run(cmd: list[str], **_: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            return result

        with patch(
            "m4bmaker.encoder.subprocess.run", side_effect=_fake_run
        ) as mock_run:
            encode(concat, meta, None, output, "96k", 1, "ffmpeg")
            called_cmd = mock_run.call_args[0][0]

        assert called_cmd[-1] == str(output)


# ---------------------------------------------------------------------------
# encode — error handling
# ---------------------------------------------------------------------------


class TestEncodeErrorHandling:
    def test_nonzero_returncode_exits(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ffmpeg: error details here"

        with patch("m4bmaker.encoder.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit, match="ffmpeg exited"):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

    def test_stderr_included_in_exit_message(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "unique_error_string_xyz"

        with patch("m4bmaker.encoder.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit, match="unique_error_string_xyz"):
                encode(concat, meta, None, output, "96k", 1, "ffmpeg")

    def test_ffmpeg_not_found_exits(self, tmp_path: Path) -> None:
        concat, meta, _, output = _make_paths(tmp_path)

        with patch(
            "m4bmaker.encoder.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(SystemExit, match="not found"):
                encode(concat, meta, None, output, "96k", 1, "/nonexistent/ffmpeg")
