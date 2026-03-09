"""Tests for m4bmaker.cli — argument parsing and defaults."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from m4bmaker.cli import parse_args

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_no_args_directory_defaults_to_cwd(self) -> None:
        args = parse_args([])
        assert args.directory == Path(os.getcwd())

    def test_no_args_output_dir_is_none(self) -> None:
        args = parse_args([])
        assert args.output_dir is None

    def test_no_args_flat_is_false(self) -> None:
        args = parse_args([])
        assert args.flat is False

    def test_no_args_output_is_none(self) -> None:
        args = parse_args([])
        assert args.output is None

    def test_no_args_title_is_none(self) -> None:
        args = parse_args([])
        assert args.title is None

    def test_no_args_author_is_none(self) -> None:
        args = parse_args([])
        assert args.author is None

    def test_no_args_narrator_is_none(self) -> None:
        args = parse_args([])
        assert args.narrator is None

    def test_no_args_cover_is_none(self) -> None:
        args = parse_args([])
        assert args.cover is None

    def test_no_args_bitrate_is_96k(self) -> None:
        args = parse_args([])
        assert args.bitrate == "96k"

    def test_no_args_stereo_is_false(self) -> None:
        args = parse_args([])
        assert args.stereo is False

    def test_no_args_no_prompt_is_false(self) -> None:
        args = parse_args([])
        assert args.no_prompt is False


# ---------------------------------------------------------------------------
# Positional argument
# ---------------------------------------------------------------------------


class TestDirectoryArg:
    def test_directory_parsed_as_path(self, tmp_path: Path) -> None:
        args = parse_args([str(tmp_path)])
        assert args.directory == tmp_path

    def test_directory_is_path_type(self, tmp_path: Path) -> None:
        args = parse_args([str(tmp_path)])
        assert isinstance(args.directory, Path)


# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------


class TestFlags:
    def test_output_long(self, tmp_path: Path) -> None:
        out = tmp_path / "out.m4b"
        args = parse_args(["--output", str(out)])
        assert args.output == out

    def test_output_short(self, tmp_path: Path) -> None:
        out = tmp_path / "out.m4b"
        args = parse_args(["-o", str(out)])
        assert args.output == out

    def test_title_long(self) -> None:
        args = parse_args(["--title", "My Book"])
        assert args.title == "My Book"

    def test_title_short(self) -> None:
        args = parse_args(["-t", "My Book"])
        assert args.title == "My Book"

    def test_author_long(self) -> None:
        args = parse_args(["--author", "Jane Doe"])
        assert args.author == "Jane Doe"

    def test_author_short(self) -> None:
        args = parse_args(["-a", "Jane Doe"])
        assert args.author == "Jane Doe"

    def test_narrator_long(self) -> None:
        args = parse_args(["--narrator", "Bob Smith"])
        assert args.narrator == "Bob Smith"

    def test_narrator_short(self) -> None:
        args = parse_args(["-n", "Bob Smith"])
        assert args.narrator == "Bob Smith"

    def test_genre_long(self) -> None:
        args = parse_args(["--genre", "Science Fiction"])
        assert args.genre == "Science Fiction"

    def test_genre_short(self) -> None:
        args = parse_args(["-g", "Fantasy"])
        assert args.genre == "Fantasy"

    def test_genre_default_none(self) -> None:
        args = parse_args([])
        assert args.genre is None

    def test_cover_long_is_str(self, tmp_path: Path) -> None:
        img = str(tmp_path / "cover.jpg")
        args = parse_args(["--cover", img])
        assert args.cover == img
        assert isinstance(args.cover, str)

    def test_cover_short_is_str(self, tmp_path: Path) -> None:
        img = str(tmp_path / "cover.jpg")
        args = parse_args(["-c", img])
        assert args.cover == img

    def test_cover_accepts_url(self) -> None:
        url = "https://example.com/cover.jpg"
        args = parse_args(["--cover", url])
        assert args.cover == url

    def test_bitrate_long(self) -> None:
        args = parse_args(["--bitrate", "128k"])
        assert args.bitrate == "128k"

    def test_bitrate_short(self) -> None:
        args = parse_args(["-b", "128k"])
        assert args.bitrate == "128k"

    def test_stereo_flag_sets_true(self) -> None:
        args = parse_args(["--stereo"])
        assert args.stereo is True

    def test_no_prompt_long(self) -> None:
        args = parse_args(["--no-prompt"])
        assert args.no_prompt is True

    def test_no_prompt_dest_attribute(self) -> None:
        """Ensure dest='no_prompt' means attr is args.no_prompt, not args.no-prompt."""
        args = parse_args(["--no-prompt"])
        assert hasattr(args, "no_prompt")
        assert not hasattr(args, "no-prompt")

    def test_output_dir_long(self, tmp_path: Path) -> None:
        args = parse_args(["--output-dir", str(tmp_path)])
        assert args.output_dir == tmp_path

    def test_output_dir_short(self, tmp_path: Path) -> None:
        args = parse_args(["-O", str(tmp_path)])
        assert args.output_dir == tmp_path

    def test_output_dir_default_none(self) -> None:
        args = parse_args([])
        assert args.output_dir is None

    def test_flat_flag_sets_true(self) -> None:
        args = parse_args(["--flat"])
        assert args.flat is True

    def test_flat_default_false(self) -> None:
        args = parse_args([])
        assert args.flat is False


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_unknown_flag_exits(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--unknown-flag-xyz"])

    def test_bitrate_is_string_not_int(self) -> None:
        """bitrate must stay as a raw string for ffmpeg (e.g. '96k', '128k')."""
        args = parse_args(["--bitrate", "96k"])
        assert isinstance(args.bitrate, str)
