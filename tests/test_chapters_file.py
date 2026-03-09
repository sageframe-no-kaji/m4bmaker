"""Tests for m4bmaker.chapters_file — timestamp parser and chapter loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from m4bmaker.chapters_file import _parse_timestamp, load_chapters_file
from m4bmaker.models import Chapter

# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_mm_ss_zero(self) -> None:
        assert _parse_timestamp("0:00") == 0.0

    def test_mm_ss_seconds_only(self) -> None:
        assert _parse_timestamp("0:45") == 45.0

    def test_mm_ss_minutes_and_seconds(self) -> None:
        assert _parse_timestamp("10:37") == 637.0

    def test_mm_ss_large_minutes(self) -> None:
        # 99:59 → 5999 seconds
        assert _parse_timestamp("99:59") == 5999.0

    def test_h_mm_ss_zero(self) -> None:
        assert _parse_timestamp("0:00:00") == 0.0

    def test_h_mm_ss_full(self) -> None:
        # 1:19:17 → 3600 + 19*60 + 17 = 4757
        assert _parse_timestamp("1:19:17") == 4757.0

    def test_h_mm_ss_multi_digit_hour(self) -> None:
        assert _parse_timestamp("10:00:00") == 36000.0

    def test_seconds_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            _parse_timestamp("0:60")

    def test_minutes_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            _parse_timestamp("1:60:00")

    def test_non_integer_raises(self) -> None:
        with pytest.raises(ValueError, match="non-integer"):
            _parse_timestamp("0:xx")


# ---------------------------------------------------------------------------
# load_chapters_file — happy paths
# ---------------------------------------------------------------------------


class TestLoadChaptersFile:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "chapters.txt"
        p.write_text(content, encoding="utf-8")
        return p

    def test_basic_mm_ss_format(self, tmp_path: Path) -> None:
        f = self._write(
            tmp_path,
            "00:00 Opening Engagement\n10:37 The Surprise\n19:17 Port Mahon\n",
        )
        chapters = load_chapters_file(f)
        assert len(chapters) == 3
        assert chapters[0].title == "Opening Engagement"
        assert chapters[0].start_time == 0.0
        assert chapters[1].start_time == 637.0
        assert chapters[2].start_time == 1157.0

    def test_h_mm_ss_format(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "0:00:00 Prologue\n1:10:30 Chapter Two\n")
        chapters = load_chapters_file(f)
        assert chapters[0].start_time == 0.0
        assert chapters[1].start_time == 4230.0

    def test_mixed_formats(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 Intro\n1:30:00 Act Two\n")
        chapters = load_chapters_file(f)
        assert len(chapters) == 2
        assert chapters[1].start_time == 5400.0

    def test_indices_sequential_from_one(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 A\n05:00 B\n10:00 C\n")
        chapters = load_chapters_file(f)
        assert [c.index for c in chapters] == [1, 2, 3]

    def test_source_file_always_none(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 Ch\n")
        chapters = load_chapters_file(f)
        assert chapters[0].source_file is None

    def test_returns_chapter_objects(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 Only\n")
        chapters = load_chapters_file(f)
        assert isinstance(chapters[0], Chapter)

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "\n00:00 First\n\n05:00 Second\n\n")
        assert len(load_chapters_file(f)) == 2

    def test_comment_lines_skipped(self, tmp_path: Path) -> None:
        f = self._write(
            tmp_path,
            "# This is a comment\n00:00 First\n# another comment\n05:00 Second\n",
        )
        assert len(load_chapters_file(f)) == 2

    def test_title_with_extra_spaces_stripped(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00   Spaced Title  \n")
        assert load_chapters_file(f)[0].title == "Spaced Title"

    def test_title_with_colons_allowed(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 Part 1: The Beginning\n")
        assert load_chapters_file(f)[0].title == "Part 1: The Beginning"

    def test_utf8_title(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 Ça va — chapitre\n")
        assert load_chapters_file(f)[0].title == "Ça va — chapitre"


# ---------------------------------------------------------------------------
# load_chapters_file — error paths
# ---------------------------------------------------------------------------


class TestLoadChaptersFileErrors:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "chapters.txt"
        p.write_text(content, encoding="utf-8")
        return p

    def test_missing_file_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            load_chapters_file(tmp_path / "nonexistent.txt")

    def test_empty_file_exits(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "")
        with pytest.raises(SystemExit, match="no chapters"):
            load_chapters_file(f)

    def test_comments_only_exits(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "# just a comment\n# another\n")
        with pytest.raises(SystemExit, match="no chapters"):
            load_chapters_file(f)

    def test_malformed_line_no_timestamp_exits(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "not a valid line\n")
        with pytest.raises(SystemExit, match="malformed"):
            load_chapters_file(f)

    def test_malformed_line_missing_title_exits(self, tmp_path: Path) -> None:
        # Timestamp with no title after it
        f = self._write(tmp_path, "00:00\n")
        with pytest.raises(SystemExit, match="malformed"):
            load_chapters_file(f)

    def test_invalid_seconds_exits(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:60 Bad Chapter\n")
        with pytest.raises(SystemExit, match="invalid timestamp"):
            load_chapters_file(f)

    def test_invalid_minutes_exits(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "1:60:00 Bad Chapter\n")
        with pytest.raises(SystemExit, match="invalid timestamp"):
            load_chapters_file(f)

    def test_error_message_includes_line_number(self, tmp_path: Path) -> None:
        f = self._write(tmp_path, "00:00 Good\nbad line here\n")
        with pytest.raises(SystemExit) as exc_info:
            load_chapters_file(f)
        # SystemExit code is the error string
        assert "2" in str(exc_info.value)

    def test_partial_valid_then_bad_exits(self, tmp_path: Path) -> None:
        """Lines after a valid chapter are still validated."""
        f = self._write(tmp_path, "00:00 Good Chapter\nalso bad\n")
        with pytest.raises(SystemExit, match="malformed"):
            load_chapters_file(f)


# ---------------------------------------------------------------------------
# --chapters-file integration with CLI arg parser
# ---------------------------------------------------------------------------


class TestChaptersFileCLIArg:
    def test_chapters_file_arg_accepted(self, tmp_path: Path) -> None:
        from m4bmaker.cli import parse_args

        f = tmp_path / "ch.txt"
        f.write_text("00:00 Intro\n")
        args = parse_args([str(tmp_path), "--chapters-file", str(f)])
        assert args.chapters_file == f

    def test_chapters_file_defaults_to_none(self, tmp_path: Path) -> None:
        from m4bmaker.cli import parse_args

        args = parse_args(
            [
                str(tmp_path),
                "--no-prompt",
                "--title",
                "T",
                "--author",
                "A",
                "--narrator",
                "N",
            ]
        )
        assert args.chapters_file is None
