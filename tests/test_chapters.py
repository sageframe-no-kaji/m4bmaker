"""Tests for m4bmaker.chapters — duration probing, chapter building, FFMETADATA."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.chapters import (
    _escape_ffmeta,
    _probe_file,
    _strip_chapter_prefix,
    _format_time,
    build_chapters,
    format_chapter_table,
    get_duration,
    write_ffmetadata,
)
from m4bmaker.errors import M4BError
from m4bmaker.models import BookMetadata, Chapter

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

    def test_nonzero_exit_raises_m4berror(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe", stderr="err"),
        ):
            with pytest.raises(M4BError, match="ffprobe failed"):
                get_duration(stub, "ffprobe")

    def test_bad_json_raises_m4berror(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = "NOT JSON{"

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
            with pytest.raises(M4BError, match="could not parse"):
                get_duration(stub, "ffprobe")

    def test_missing_duration_key_raises_m4berror(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"format": {}})  # missing "duration"

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
            with pytest.raises(M4BError, match="could not parse"):
                get_duration(stub, "ffprobe")

    def test_timeout_raises_m4berror(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ffprobe", 120),
        ):
            with pytest.raises(M4BError, match="timed out"):
                get_duration(stub, "ffprobe")

    def test_ffprobe_not_found_raises_m4berror(self, tmp_path: Path) -> None:
        stub = tmp_path / "track.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            with pytest.raises(M4BError, match="not found"):
                get_duration(stub, "/nonexistent/ffprobe")


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
        assert chapters[0].index == 1
        assert chapters[0].start_time == 0.0
        assert chapters[0].title == "Prologue"
        assert chapters[0].source_file == stub

    def test_progress_fn_called_per_file(self, tmp_path: Path) -> None:
        stub = tmp_path / "01 - Prologue.mp3"
        stub.write_bytes(b"\x00")
        calls: list[tuple[int, int, str]] = []

        with patch(
            "m4bmaker.chapters.subprocess.run",
            return_value=self._patch_duration(60.0),
        ):
            build_chapters(
                [stub], "ffprobe", progress_fn=lambda i, t, n: calls.append((i, t, n))
            )

        assert calls == [(1, 1, stub.name)]

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

        assert chapters[0].start_time == 0.0
        assert chapters[1].start_time == 10.0
        assert chapters[2].start_time == 30.0
        assert chapters[0].index == 1
        assert chapters[1].index == 2
        assert chapters[2].index == 3

    def test_chapter_titles_stripped_of_prefix(self, tmp_path: Path) -> None:
        stub = tmp_path / "03_Introduction.mp3"
        stub.write_bytes(b"\x00")

        with patch(
            "m4bmaker.chapters.subprocess.run",
            return_value=self._patch_duration(5.0),
        ):
            chapters = build_chapters([stub], "ffprobe")

        assert chapters[0].title == "Introduction"

    def test_chapter_title_from_metadata_tag(self, tmp_path: Path) -> None:
        stub = tmp_path / "01 - track.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {"format": {"duration": "30.0", "tags": {"title": "Symphony No. 9"}}}
        )

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
            chapters = build_chapters([stub], "ffprobe")

        assert chapters[0].title == "Symphony No. 9"

    def test_chapter_title_falls_back_to_filename_when_no_tag(
        self, tmp_path: Path
    ) -> None:
        stub = tmp_path / "03_Introduction.mp3"
        stub.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"format": {"duration": "30.0"}})

        with patch("m4bmaker.chapters.subprocess.run", return_value=mock_result):
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

        assert chapters[0].start_time == 0.0
        assert chapters[0].source_file is not None
        assert isinstance(chapters[0].start_time, float)


# ---------------------------------------------------------------------------
# write_ffmetadata
# ---------------------------------------------------------------------------


class TestWriteFFMetadata:
    def _make_chapters(self) -> list[Chapter]:
        return [
            Chapter(index=1, start_time=0.0, title="Intro"),
            Chapter(index=2, start_time=10.0, title="Chapter One"),
        ]

    def test_file_starts_with_ffmetadata1(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(
            self._make_chapters(), BookMetadata(), dest, total_duration_s=30.0
        )
        content = dest.read_text()
        assert content.startswith(";FFMETADATA1")

    def test_global_tags_written(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = BookMetadata(title="My Book", author="J. Smith", narrator="B. Jones")
        write_ffmetadata(self._make_chapters(), meta, dest, total_duration_s=30.0)
        content = dest.read_text()
        assert "title=My Book" in content
        assert "artist=J. Smith" in content
        assert "composer=B. Jones" in content

    def test_genre_tag_written(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = BookMetadata(
            title="My Book",
            author="J. Smith",
            narrator="B. Jones",
            genre="Science Fiction",
        )
        write_ffmetadata(self._make_chapters(), meta, dest, total_duration_s=30.0)
        content = dest.read_text()
        assert "genre=Science Fiction" in content

    def test_genre_omitted_when_empty(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = BookMetadata(title="T", author="A", narrator="N", genre="")
        write_ffmetadata(self._make_chapters(), meta, dest, total_duration_s=30.0)
        content = dest.read_text()
        assert "genre=" not in content

    def test_chapter_count_correct(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(
            self._make_chapters(), BookMetadata(), dest, total_duration_s=30.0
        )
        content = dest.read_text()
        assert content.count("[CHAPTER]") == 2

    def test_chapter_timestamps_correct(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="Only")]
        write_ffmetadata(chapters, BookMetadata(), dest, total_duration_s=5.5)
        content = dest.read_text()
        assert "TIMEBASE=1/1000" in content
        assert "START=0" in content
        assert "END=5500" in content

    def test_chapter_titles_written(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(
            self._make_chapters(), BookMetadata(), dest, total_duration_s=30.0
        )
        content = dest.read_text()
        assert "title=Intro" in content
        assert "title=Chapter One" in content

    def test_empty_meta_fields_omitted(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        write_ffmetadata(
            self._make_chapters(),
            BookMetadata(title="", author="", narrator=""),
            dest,
            total_duration_s=30.0,
        )
        content = dest.read_text()
        assert "title=" not in content.split("\n")[1]  # line 1 after ;FFMETADATA1
        assert "artist=" not in content
        assert "composer=" not in content

    def test_file_is_utf8(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="Ça va — chapter")]
        meta = BookMetadata(title="Über Book", author="", narrator="")
        write_ffmetadata(chapters, meta, dest, total_duration_s=1.0)
        raw = dest.read_bytes()
        raw.decode("utf-8")  # must not raise

    def test_equals_in_title_escaped(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="A=B Chapter")]
        write_ffmetadata(chapters, BookMetadata(), dest, total_duration_s=5.0)
        content = dest.read_text()
        assert "title=A\\=B Chapter" in content

    def test_semicolon_in_title_escaped(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="Wait; then go")]
        write_ffmetadata(chapters, BookMetadata(), dest, total_duration_s=5.0)
        content = dest.read_text()
        assert "title=Wait\\; then go" in content

    def test_hash_in_title_escaped(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="Chapter #1")]
        write_ffmetadata(chapters, BookMetadata(), dest, total_duration_s=5.0)
        content = dest.read_text()
        assert "title=Chapter \\#1" in content

    def test_backslash_in_title_escaped_first(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="C:\\path")]
        write_ffmetadata(chapters, BookMetadata(), dest, total_duration_s=5.0)
        content = dest.read_text()
        assert "title=C:\\\\path" in content

    def test_newline_in_title_escaped(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        chapters = [Chapter(index=1, start_time=0.0, title="Line1\nLine2")]
        write_ffmetadata(chapters, BookMetadata(), dest, total_duration_s=5.0)
        content = dest.read_text()
        assert "title=Line1\\\nLine2" in content

    def test_special_chars_escaped_in_global_tags(self, tmp_path: Path) -> None:
        dest = tmp_path / "meta.txt"
        meta = BookMetadata(
            title="A=Title", author="B;Author", narrator="C#Narrator", genre="D\\Genre"
        )
        write_ffmetadata(self._make_chapters(), meta, dest, total_duration_s=30.0)
        content = dest.read_text()
        assert "title=A\\=Title" in content
        assert "artist=B\\;Author" in content
        assert "composer=C\\#Narrator" in content
        assert "genre=D\\\\Genre" in content


# ---------------------------------------------------------------------------
# _escape_ffmeta
# ---------------------------------------------------------------------------


class TestEscapeFFMeta:
    def test_equals_escaped(self) -> None:
        assert _escape_ffmeta("a=b") == "a\\=b"

    def test_semicolon_escaped(self) -> None:
        assert _escape_ffmeta("a;b") == "a\\;b"

    def test_hash_escaped(self) -> None:
        assert _escape_ffmeta("a#b") == "a\\#b"

    def test_backslash_escaped(self) -> None:
        assert _escape_ffmeta("a\\b") == "a\\\\b"

    def test_newline_escaped(self) -> None:
        assert _escape_ffmeta("a\nb") == "a\\\nb"

    def test_backslash_escaped_before_other_chars(self) -> None:
        # Backslash must be escaped first so its escape isn't re-escaped by
        # the subsequent '=' pass etc.
        assert _escape_ffmeta("a\\=b") == "a\\\\\\=b"

    def test_plain_string_unchanged(self) -> None:
        assert _escape_ffmeta("Plain Title") == "Plain Title"

    def test_empty_string(self) -> None:
        assert _escape_ffmeta("") == ""


# ---------------------------------------------------------------------------
# _format_chapter_ms
# ---------------------------------------------------------------------------


class TestFormatTime:
    def test_zero(self) -> None:
        assert _format_time(0.0) == "0:00:00"

    def test_seconds_only(self) -> None:
        assert _format_time(45.0) == "0:00:45"

    def test_minutes_and_seconds(self) -> None:
        assert _format_time(90.0) == "0:01:30"

    def test_full_hour(self) -> None:
        assert _format_time(3600.0) == "1:00:00"

    def test_complex_value(self) -> None:
        # 2h 43m 34s = 9814 seconds
        assert _format_time(9814.0) == "2:43:34"


# ---------------------------------------------------------------------------
# format_chapter_table
# ---------------------------------------------------------------------------


class TestFormatChapterTable:
    def test_empty_returns_placeholder(self) -> None:
        result = format_chapter_table([])
        assert "no chapters" in result

    def test_single_chapter_contains_title(self) -> None:
        ch = Chapter(index=1, start_time=0.0, title="Prologue")
        result = format_chapter_table([ch])
        assert "Prologue" in result
        assert "0:00:00" in result

    def test_multiple_chapters_all_present(self) -> None:
        chapters = [
            Chapter(index=1, start_time=0.0, title="Intro"),
            Chapter(index=2, start_time=60.0, title="The Storm"),
            Chapter(index=3, start_time=180.0, title="Aftermath"),
        ]
        result = format_chapter_table(chapters)
        assert "Intro" in result
        assert "The Storm" in result
        assert "Aftermath" in result
        assert "0:01:00" in result
        assert "0:03:00" in result

    def test_long_title_truncated(self) -> None:
        long_title = "A" * 50
        ch = Chapter(index=1, start_time=0.0, title=long_title)
        result = format_chapter_table([ch])
        # Should be truncated with ellipsis, not show all 50 chars
        assert long_title not in result
        assert "\u2026" in result

    def test_box_drawing_characters_present(self) -> None:
        ch = Chapter(index=1, start_time=0.0, title="Ch")
        result = format_chapter_table([ch])
        assert "\u250c" in result  # ┌
        assert "\u2514" in result  # └
        assert "\u2502" in result  # │

    def test_correct_row_count(self) -> None:
        chapters = [
            Chapter(index=i + 1, start_time=float(i), title=f"Ch {i}") for i in range(5)
        ]
        lines = format_chapter_table(chapters).splitlines()
        # 3 header lines (top, header, sep) + 5 data rows + 1 bottom = 9
        assert len(lines) == 9


# ---------------------------------------------------------------------------
# Embedded chapters carried over from source files (#28)
# ---------------------------------------------------------------------------


def _probe_json(duration: float, chapters: list[tuple[float, str | None]]) -> str:
    return json.dumps(
        {
            "format": {"duration": str(duration)},
            "chapters": [
                {"start_time": str(start), **({"tags": {"title": t}} if t else {})}
                for start, t in chapters
            ],
        }
    )


def _run_returning(outputs: dict[str, str]):
    """subprocess.run stub answering ffprobe per file name (last cmd arg)."""

    def run(cmd, **_kw):
        result = MagicMock()
        result.stdout = outputs[Path(cmd[-1]).name]
        return result

    return run


class TestEmbeddedChapters:
    def test_probe_requests_and_parses_chapters(self, tmp_path: Path) -> None:
        stub = tmp_path / "book.m4b"
        seen: list[list[str]] = []

        def run(cmd, **_kw):
            seen.append(cmd)
            result = MagicMock()
            result.stdout = _probe_json(90.0, [(0.0, "One"), (45.0, None)])
            return result

        with patch("m4bmaker.chapters.subprocess.run", side_effect=run):
            probe = _probe_file(stub, "ffprobe")

        assert "-show_chapters" in seen[0]
        assert probe.chapters == [(0.0, "One"), (45.0, None)]

    def test_probe_skips_marker_without_start(self, tmp_path: Path) -> None:
        data = json.dumps(
            {
                "format": {"duration": "90"},
                "chapters": [{"tags": {"title": "No start"}}, {"start_time": "x"}],
            }
        )
        with patch(
            "m4bmaker.chapters.subprocess.run", return_value=MagicMock(stdout=data)
        ):
            probe = _probe_file(tmp_path / "b.m4b", "ffprobe")
        assert probe.chapters == []

    def test_two_chaptered_books_keep_all_chapters_shifted(
        self, tmp_path: Path
    ) -> None:
        a, b = tmp_path / "a.m4b", tmp_path / "b.m4b"
        outputs = {
            "a.m4b": _probe_json(60.0, [(0.0, "A1"), (20.0, "A2"), (40.0, "A3")]),
            "b.m4b": _probe_json(30.0, [(0.0, "B1"), (10.0, "B2")]),
        }
        with patch(
            "m4bmaker.chapters.subprocess.run", side_effect=_run_returning(outputs)
        ):
            chapters = build_chapters([a, b], "ffprobe")

        assert [c.title for c in chapters] == ["A1", "A2", "A3", "B1", "B2"]
        assert [c.start_time for c in chapters] == [0.0, 20.0, 40.0, 60.0, 70.0]
        assert [c.file_offset for c in chapters] == [0.0, 20.0, 40.0, 0.0, 10.0]
        assert [c.source_file for c in chapters] == [a, a, a, b, b]
        assert [c.index for c in chapters] == [1, 2, 3, 4, 5]

    def test_mixed_chaptered_and_plain_files(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a.m4b", tmp_path / "02 - Epilogue.mp3"
        outputs = {
            "a.m4b": _probe_json(60.0, [(0.0, "A1"), (30.0, "A2")]),
            "02 - Epilogue.mp3": _probe_json(15.0, []),
        }
        with patch(
            "m4bmaker.chapters.subprocess.run", side_effect=_run_returning(outputs)
        ):
            chapters = build_chapters([a, b], "ffprobe")

        assert [(c.title, c.start_time) for c in chapters] == [
            ("A1", 0.0),
            ("A2", 30.0),
            ("Epilogue", 60.0),
        ]

    def test_first_marker_pinned_to_file_start(self, tmp_path: Path) -> None:
        """Audio before the first marker must still belong to a chapter."""
        a = tmp_path / "a.m4b"
        outputs = {"a.m4b": _probe_json(60.0, [(2.5, "One"), (30.0, "Two")])}
        with patch(
            "m4bmaker.chapters.subprocess.run", side_effect=_run_returning(outputs)
        ):
            chapters = build_chapters([a], "ffprobe")
        assert [c.start_time for c in chapters] == [0.0, 30.0]

    def test_markers_past_end_dropped_and_sorted(self, tmp_path: Path) -> None:
        a = tmp_path / "a.m4b"
        outputs = {
            "a.m4b": _probe_json(
                60.0, [(30.0, "Two"), (0.0, "One"), (60.0, "End"), (99.0, "Past")]
            )
        }
        with patch(
            "m4bmaker.chapters.subprocess.run", side_effect=_run_returning(outputs)
        ):
            chapters = build_chapters([a], "ffprobe")
        assert [c.title for c in chapters] == ["One", "Two"]

    def test_untitled_markers_take_numbered_file_title(self, tmp_path: Path) -> None:
        a = tmp_path / "01 - Dune.m4b"
        outputs = {"01 - Dune.m4b": _probe_json(60.0, [(0.0, None), (30.0, None)])}
        with patch(
            "m4bmaker.chapters.subprocess.run", side_effect=_run_returning(outputs)
        ):
            chapters = build_chapters([a], "ffprobe")
        assert [c.title for c in chapters] == ["Dune 1", "Dune 2"]

    def test_single_untitled_marker_takes_plain_file_title(
        self, tmp_path: Path
    ) -> None:
        a = tmp_path / "01 - Dune.m4b"
        outputs = {"01 - Dune.m4b": _probe_json(60.0, [(0.0, None)])}
        with patch(
            "m4bmaker.chapters.subprocess.run", side_effect=_run_returning(outputs)
        ):
            chapters = build_chapters([a], "ffprobe")
        assert [(c.title, c.file_offset) for c in chapters] == [("Dune", 0.0)]


_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None, reason="ffmpeg/ffprobe not installed"
)
class TestEmbeddedChaptersRealFiles:
    """Real ffmpeg-built M4Bs: proves ffprobe's chapter output is read right."""

    @staticmethod
    def _chaptered_m4b(path: Path, seconds: int, marks: list[tuple[int, str]]):
        meta = path.with_suffix(".ffmeta")
        bounds = [s for s, _ in marks] + [seconds]
        lines = [";FFMETADATA1"]
        for (start, title), end in zip(marks, bounds[1:]):
            lines += [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start * 1000}",
                f"END={end * 1000}",
                f"title={title}",
            ]
        meta.write_text("\n".join(lines) + "\n")
        subprocess.run(
            [_FFMPEG, "-y", "-v", "error",
             "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=22050:cl=mono",
             "-i", str(meta), "-map_chapters", "1",
             "-c:a", "aac", "-t", str(seconds), str(path)],
            check=True,
            timeout=30,
        )  # fmt: skip
        return path

    def test_two_real_books_merge_with_all_chapters(self, tmp_path: Path) -> None:
        a = self._chaptered_m4b(tmp_path / "a.m4b", 6, [(0, "A1"), (3, "A2")])
        b = self._chaptered_m4b(tmp_path / "b.m4b", 4, [(0, "B1"), (2, "B2")])

        chapters = build_chapters([a, b], _FFPROBE)

        assert [c.title for c in chapters] == ["A1", "A2", "B1", "B2"]
        starts = [c.start_time for c in chapters]
        # AAC priming pads each file slightly, so allow a small tolerance.
        assert starts == pytest.approx([0.0, 3.0, 6.0, 8.0], abs=0.1)
