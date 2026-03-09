"""Tests for m4bmaker.chapters — duration probing, chapter building, FFMETADATA."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.chapters import (
    Chapter,
    _strip_chapter_prefix,
    build_chapters,
    get_duration,
    write_ffmetadata,
)

# ---------------------------------------------------------------------------
# _strip_chapter_prefix
# ---------------------------------------------------------------------------


class TestStripChapterPrefix:
    @pytest.mark.parametrize(
        "stem, expected",
        [
            ("01 - Prologue", "Prologue"),
            ("1.Intro", "Intro"),
            ("02_Part One", "Part One"),
            ("003 Chapter Name", "Chapter Name"),
            ("10-Finale", "Finale"),
            ("NoPrefix", "NoPrefix"),
            ("Just Text", "Just Text"),
            ("01", "01"),  # pure number → fall back to original
            ("01 ", "01 "),  # trailing space after strip leaves empty -> fallback
        ],
    )
    def test_strip(self, stem: str, expected: str) -> None:
        assert _strip_chapter_prefix(stem) == expected


# ---------------------------------------------------------------------------
# get_duration
# ---------------------------------------------------------------------------


def _ffprobe_stdout(duration: float) -> str:
    return json.dumps({"format": {"duration": str(duration)}})


class TestGetDuration:
    def test_parses_duration_correctly(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = _ffprobe_stdout(123.456)

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
            dur = get_duration(stub, "ffprobe")

        assert abs(dur - 123.456) < 1e-9

    def test_nonzero_exit_raises_system_exit(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe", stderr="err"),
        ):
            with pytest.raises(SystemExit, match="ffprobe failed"):
                get_duration(stub, "ffprobe")

    def test_bad_json_raises_system_exit(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = "NOT JSON{"

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit, match="could not parse"):
                get_duration(stub, "ffprobe")

    def test_missing_duration_key_raises_system_exit(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"format": {}})  # missing "duration"

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit, match="could not parse"):
                get_duration(stub, "ffprobe")


# ---------------------------------------------------------------------------
# build_chapters
# ---------------------------------------------------------------------------


class TestBuildChapters:
    def _patch_duration(self, duration: float) -> MagicMock:
        mock_result = MagicMock()
        mock_result.stdout = _ffprobe_stdout(duration)
        return mock_result

    def test_single_file_starts_at_zero(self, tmp_path: Path) -> None:
        stub = tmp_path / "01 - Prologue.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            return_value=self._patch_duration(60.0),
        ):
            chapters = build_chapters([stub], "ffprobe")

        assert len(chapters) == 1
        assert chapters[0].start_ms == 0
        assert chapters[0].end_ms == 60_000
        assert chapters[0].title == "Prologue"

    def test_multiple_files_cumulative_timestamps(self, tmp_path: Path) -> None:
        files = [tmp_path / f"0{i}.mp3" for i in range(1, 4)]
        for f in files:
            f.write_bytes(b"\x00")

        durations = [10.0, 20.0, 30.0]
        call_count = 0

        def _side_effect(cmd: list[str], **_: object) -> MagicMock:
            nonlocal call_count
            result = MagicMock()
            result.stdout = _ffprobe_stdout(durations[call_count])
            call_count += 1
            return result

        with patch("m4bmaker.chapters.subprocess.run", side_effect=_side_effect):
            chapters = build_chapters(files, "ffprobe")

        assert chapters[0].start_ms == 0
        assert chapters[0].end_ms == 10_000
        assert chapters[1].start_ms == 10_000
        assert chapters[1].end_ms == 30_000
        assert chapters[2].start_ms == 30_000
        assert chapters[2].end_ms == 60_000

    def test_chapter_titles_stripped_of_prefix(self, tmp_path: Path) -> None:
        stub = tmp_path / "03_Introduction.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            return_value=self._patch_duration(5.0),
        ):
            chapters = build_chapters([stub], "ffprobe")

        assert chapters[0].title == "Introduction"

    def test_long_audiobook_no_integer_overflow(self, tmp_path: Path) -> None:
        """20 h: 20 * 3600 * 1000 ms = 72_000_000 — well within int range."""
        stub = tmp_path / "marathon.mp3"
        stub.write_bytes(b"\x00")

        twenty_hours_sec = 20 * 3600.0
        with patch(
            "m4bmaker.chapters.subprocess.run",
            return_value=self._patch_duration(twenty_hours_sec),
        ):
            chapters = build_chapters([stub], "ffprobe")

        assert chapters[0].end_ms == 72_000_000
        assert isinstance(chapters[0].end_ms, int)


# ---------------------------------------------------------------------------
# write_ffmetadata
# ---------------------------------------------------------------------------


class TestWriteFFMetadata:
    def _make_chapters(self) -> list[Chapter]:
        return [
            Chapter(title="Intro", start_ms=0, end_ms=10_000),
            Chapter(title="Chapter One", start_ms=10_000, end_ms=30_000),
        ]

    def test_file_starts_with_ffmetadata1(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(self._make_chapters(), {}, dest)
        content = dest.read_text()
        assert content.startswith(";FFMETADATA1")

    def test_global_tags_written(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = {"title": "My Book", "author": "J. Smith", "narrator": "B. Jones"}
        write_ffmetadata(self._make_chapters(), meta, dest)
        content = dest.read_text()
        assert "title=My Book" in content
        assert "artist=J. Smith" in content
        assert "composer=B. Jones" in content

    def test_genre_tag_written(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = {
            "title": "My Book",
            "author": "J. Smith",
            "narrator": "B. Jones",
            "genre": "Science Fiction",
        }
        write_ffmetadata(self._make_chapters(), meta, dest)
        content = dest.read_text()
        assert "genre=Science Fiction" in content

    def test_genre_omitted_when_empty(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = {"title": "T", "author": "A", "narrator": "N", "genre": ""}
        write_ffmetadata(self._make_chapters(), meta, dest)
        content = dest.read_text()
        assert "genre=" not in content

    def test_chapter_count_correct(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(self._make_chapters(), {}, dest)
        content = dest.read_text()
        assert content.count("[CHAPTER]") == 2

    def test_chapter_timestamps_correct(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(title="Only", start_ms=0, end_ms=5_500)]
        write_ffmetadata(chapters, {}, dest)
        content = dest.read_text()
        assert "TIMEBASE=1/1000" in content
        assert "START=0" in content
        assert "END=5500" in content

    def test_chapter_titles_written(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(self._make_chapters(), {}, dest)
        content = dest.read_text()
        assert "title=Intro" in content
        assert "title=Chapter One" in content

    def test_empty_meta_fields_omitted(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(
            self._make_chapters(), {"title": "", "author": "", "narrator": ""}, dest
        )
        content = dest.read_text()
        assert "title=" not in content.split("\n")[1]  # line 1 after ;FFMETADATA1
        assert "artist=" not in content
        assert "composer=" not in content

    def test_file_is_utf8(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(title="Ça va — chapter", start_ms=0, end_ms=1000)]
        meta = {"title": "Über Book", "author": "", "narrator": ""}
        write_ffmetadata(chapters, meta, dest)
        raw = dest.read_bytes()
        raw.decode("utf-8")  # must not raise
