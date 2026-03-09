"""Integration tests — wire the full pipeline with mocked subprocess calls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.__main__ import _output_path, main

# ---------------------------------------------------------------------------
# _output_path helpers
# ---------------------------------------------------------------------------


class TestOutputPath:
    def test_title_and_author(self, tmp_path: Path) -> None:
        meta = {"title": "Dune", "author": "Frank Herbert", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert p == tmp_path / "Dune - Frank Herbert.m4b"

    def test_title_only(self, tmp_path: Path) -> None:
        meta = {"title": "Dune", "author": "", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert p == tmp_path / "Dune.m4b"

    def test_no_title_fallback(self, tmp_path: Path) -> None:
        meta = {"title": "", "author": "", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert p == tmp_path / "audiobook.m4b"

    def test_slash_sanitised_in_title(self, tmp_path: Path) -> None:
        meta = {"title": "A/B", "author": "Author", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert "/" not in p.name

    def test_slash_sanitised_in_author(self, tmp_path: Path) -> None:
        meta = {"title": "Title", "author": "A/B", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert p.name == "Title - A-B.m4b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_mp3(path: Path) -> Path:
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 128)
    return path


def _ffmpeg_result() -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    return result


def _run_pipeline(
    tmp_path: Path,
    num_files: int = 3,
    duration: float = 10.0,
    extra_argv: list[str] | None = None,
    title: str = "Test Book",
    author: str = "Test Author",
    narrator: str = "Test Voice",
) -> tuple[list[str], list[list[str]]]:
    """
    Build stub MP3s, mock all external calls, and run main().

    Strategy:
      - Patch ``m4bmaker.chapters.get_duration`` to return a fixed float.
      - Patch ``m4bmaker.encoder.subprocess.run`` for the ffmpeg encode call.
      - Patch ``m4bmaker.utils.shutil.which`` for tool detection.

    Returns (first_ffmpeg_cmd, all_ffmpeg_cmds).
    """
    from m4bmaker.cli import parse_args as real_parse_args

    for i in range(1, num_files + 1):
        _make_stub_mp3(tmp_path / f"0{i} - Chapter {i}.mp3")

    argv = (
        [str(tmp_path)]
        + (extra_argv or [])
        + [
            "--title",
            title,
            "--author",
            author,
            "--narrator",
            narrator,
            "--no-prompt",
        ]
    )
    parsed = real_parse_args(argv)

    ffmpeg_cmds: list[list[str]] = []

    def _fake_ffmpeg_run(cmd: list[str], **kwargs: object) -> MagicMock:
        ffmpeg_cmds.append(cmd)
        return _ffmpeg_result()

    with (
        patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("m4bmaker.chapters.get_duration", return_value=duration),
        patch("m4bmaker.encoder.subprocess.run", side_effect=_fake_ffmpeg_run),
        patch("m4bmaker.__main__.parse_args", return_value=parsed),
    ):
        main()

    first_cmd = ffmpeg_cmds[0] if ffmpeg_cmds else []
    return first_cmd, ffmpeg_cmds


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_ffmpeg_called_exactly_once(self, tmp_path: Path) -> None:
        _, calls = _run_pipeline(tmp_path)
        assert len(calls) == 1

    def test_aac_codec_in_ffmpeg_call(self, tmp_path: Path) -> None:
        cmd, _ = _run_pipeline(tmp_path)
        assert "-c:a" in cmd
        assert "aac" in cmd

    def test_default_bitrate_96k(self, tmp_path: Path) -> None:
        cmd, _ = _run_pipeline(tmp_path)
        idx = cmd.index("-b:a")
        assert cmd[idx + 1] == "96k"

    def test_stereo_flag_sets_2_channels(self, tmp_path: Path) -> None:
        cmd, _ = _run_pipeline(tmp_path, extra_argv=["--stereo"])
        idx = cmd.index("-ac")
        assert cmd[idx + 1] == "2"

    def test_default_mono_channel(self, tmp_path: Path) -> None:
        cmd, _ = _run_pipeline(tmp_path)
        idx = cmd.index("-ac")
        assert cmd[idx + 1] == "1"

    def test_output_path_contains_title_and_author(self, tmp_path: Path) -> None:
        cmd, _ = _run_pipeline(tmp_path)
        last_arg = cmd[-1]
        assert "Test Book" in last_arg
        assert "Test Author" in last_arg
        assert last_arg.endswith(".m4b")

    def test_ffmetadata_written_with_correct_chapter_count(
        self, tmp_path: Path
    ) -> None:
        from m4bmaker.cli import parse_args as real_parse_args

        num_files = 3
        for i in range(1, num_files + 1):
            _make_stub_mp3(tmp_path / f"0{i}.mp3")

        argv = [
            str(tmp_path),
            "--title",
            "T",
            "--author",
            "A",
            "--narrator",
            "N",
            "--no-prompt",
        ]
        parsed = real_parse_args(argv)

        written: list[str] = []
        _orig = Path.write_text

        def _capture(
            self_path: Path, text: str, *args: object, **kwargs: object
        ) -> None:
            if "ffmetadata" in str(self_path):
                written.append(text)
            _orig(self_path, text, *args, **kwargs)  # type: ignore[call-arg]

        with (
            patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("m4bmaker.chapters.get_duration", return_value=5.0),
            patch("m4bmaker.encoder.subprocess.run", return_value=_ffmpeg_result()),
            patch("m4bmaker.__main__.parse_args", return_value=parsed),
            patch.object(Path, "write_text", _capture),
        ):
            main()

        assert written, "ffmetadata file was never written"
        assert written[0].count("[CHAPTER]") == num_files

    def test_concat_list_contains_all_audio_paths(self, tmp_path: Path) -> None:
        from m4bmaker.cli import parse_args as real_parse_args

        num_files = 3
        audio_files = [
            _make_stub_mp3(tmp_path / f"0{i}.mp3") for i in range(1, num_files + 1)
        ]

        argv = [
            str(tmp_path),
            "--title",
            "T",
            "--author",
            "A",
            "--narrator",
            "N",
            "--no-prompt",
        ]
        parsed = real_parse_args(argv)

        written: list[str] = []
        _orig = Path.write_text

        def _capture(
            self_path: Path, text: str, *args: object, **kwargs: object
        ) -> None:
            if "concat" in str(self_path):
                written.append(text)
            _orig(self_path, text, *args, **kwargs)  # type: ignore[call-arg]

        with (
            patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("m4bmaker.chapters.get_duration", return_value=5.0),
            patch("m4bmaker.encoder.subprocess.run", return_value=_ffmpeg_result()),
            patch("m4bmaker.__main__.parse_args", return_value=parsed),
            patch.object(Path, "write_text", _capture),
        ):
            main()

        assert written, "concat file was never written"
        for f in audio_files:
            assert str(f.resolve()) in written[0]

    def test_fallback_to_audiobook_m4b_when_no_title(self, tmp_path: Path) -> None:
        """When metadata has no title, _output_path falls back to audiobook.m4b."""
        meta = {"title": "", "author": "A", "narrator": "N"}
        p = _output_path(tmp_path, meta)
        assert p.name == "audiobook.m4b"


# ---------------------------------------------------------------------------
# _hints_from_dirname
# ---------------------------------------------------------------------------


class TestHintsDirname:
    def test_author_title_pattern(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _hints_from_dirname

        d = tmp_path / "Frank Herbert - Dune"
        d.mkdir()
        hints = _hints_from_dirname(d)
        assert hints["author"] == "Frank Herbert"
        assert hints["title"] == "Dune"

    def test_title_only_when_no_separator(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _hints_from_dirname

        d = tmp_path / "Just A Name"
        d.mkdir()
        hints = _hints_from_dirname(d)
        assert hints["title"] == "Just A Name"
        assert "author" not in hints

    def test_strips_whitespace_around_separator(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _hints_from_dirname

        d = tmp_path / "Author Name  -  Book Title"
        d.mkdir()
        hints = _hints_from_dirname(d)
        assert hints["author"] == "Author Name"
        assert hints["title"] == "Book Title"


# ---------------------------------------------------------------------------
# _resolve_cover
# ---------------------------------------------------------------------------


class TestResolveCover:
    def test_url_arg_downloads_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        expected = tmp_path / "cover.jpg"
        with patch("m4bmaker.__main__.download_cover", return_value=expected):
            result = _resolve_cover(
                "https://example.com/c.jpg", tmp_path, tmp_path, False
            )
        assert result == expected

    def test_local_path_arg_calls_find_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("m4bmaker.__main__.find_cover", return_value=img) as mock_fc:
            result = _resolve_cover(str(img), tmp_path, tmp_path, False)
        mock_fc.assert_called_once()
        assert result == img

    def test_auto_detects_when_no_arg(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("m4bmaker.__main__.find_cover", return_value=img):
            result = _resolve_cover(None, tmp_path, tmp_path, False)
        assert result == img

    def test_interactive_prompts_when_no_cover_found(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        expected = tmp_path / "prompted.jpg"
        with (
            patch("m4bmaker.__main__.find_cover", return_value=None),
            patch("m4bmaker.__main__._prompt_cover", return_value=expected) as mock_p,
        ):
            result = _resolve_cover(None, tmp_path, tmp_path, True)
        mock_p.assert_called_once_with(tmp_path)
        assert result == expected

    def test_non_interactive_returns_none_when_no_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        with patch("m4bmaker.__main__.find_cover", return_value=None):
            result = _resolve_cover(None, tmp_path, tmp_path, False)
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_cover_url
# ---------------------------------------------------------------------------


class TestFetchCoverUrl:
    def test_downloads_successfully(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _fetch_cover_url

        expected = tmp_path / "d.jpg"
        with patch("m4bmaker.__main__.download_cover", return_value=expected):
            result = _fetch_cover_url("https://example.com/c.jpg", tmp_path, False)
        assert result == expected

    def test_non_interactive_exits_on_failure(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _fetch_cover_url

        with patch(
            "m4bmaker.__main__.download_cover", side_effect=ValueError("not image")
        ):
            with pytest.raises(SystemExit):
                _fetch_cover_url("https://example.com/c.html", tmp_path, False)

    def test_interactive_accepts_local_path_on_retry(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _fetch_cover_url

        local = tmp_path / "cover.jpg"
        local.write_bytes(b"\x00")
        with (
            patch("m4bmaker.__main__.download_cover", side_effect=ValueError("bad")),
            patch("builtins.input", return_value=str(local)),
        ):
            result = _fetch_cover_url("https://fail.com/x.html", tmp_path, True)
        assert result == local

    def test_interactive_skips_on_empty_input(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _fetch_cover_url

        with (
            patch("m4bmaker.__main__.download_cover", side_effect=ValueError("bad")),
            patch("builtins.input", return_value=""),
        ):
            result = _fetch_cover_url("https://fail.com/x.html", tmp_path, True)
        assert result is None

    def test_interactive_retries_new_url(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _fetch_cover_url

        expected = tmp_path / "d.jpg"
        call_count = [0]

        def _dl(url: str, dest: Path) -> Path:
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("first fail")
            return expected

        with (
            patch("m4bmaker.__main__.download_cover", side_effect=_dl),
            patch("builtins.input", return_value="https://example.com/new.jpg"),
        ):
            result = _fetch_cover_url("https://example.com/first.jpg", tmp_path, True)
        assert result == expected


# ---------------------------------------------------------------------------
# _prompt_cover
# ---------------------------------------------------------------------------


class TestPromptCover:
    def test_skips_on_empty_input(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _prompt_cover

        with patch("builtins.input", return_value=""):
            result = _prompt_cover(tmp_path)
        assert result is None

    def test_returns_existing_local_path(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _prompt_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("builtins.input", return_value=str(img)):
            result = _prompt_cover(tmp_path)
        assert result == img

    def test_downloads_url(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _prompt_cover

        expected = tmp_path / "d.jpg"
        with (
            patch("builtins.input", return_value="https://example.com/c.jpg"),
            patch("m4bmaker.__main__.download_cover", return_value=expected),
        ):
            result = _prompt_cover(tmp_path)
        assert result == expected

    def test_download_error_prompts_again_then_skip(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _prompt_cover

        inputs = iter(["https://example.com/c.jpg", ""])
        with (
            patch("builtins.input", side_effect=inputs),
            patch("m4bmaker.__main__.download_cover", side_effect=ValueError("bad")),
        ):
            result = _prompt_cover(tmp_path)
        assert result is None

    def test_nonexistent_path_prompts_again_then_skip(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _prompt_cover

        inputs = iter([str(tmp_path / "nope.jpg"), ""])
        with patch("builtins.input", side_effect=inputs):
            result = _prompt_cover(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# Full pipeline — cover image in directory
# ---------------------------------------------------------------------------


class TestPipelineWithCover:
    def test_cover_in_directory_is_embedded(self, tmp_path: Path) -> None:
        """Cover image auto-detected in directory appears in ffmpeg command."""
        (tmp_path / "cover.jpg").write_bytes(b"\x00")
        cmd, _ = _run_pipeline(tmp_path)
        assert str(tmp_path / "cover.jpg") in cmd
