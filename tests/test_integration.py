"""Integration tests — wire the full pipeline with mocked subprocess calls."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.__main__ import _output_path, _confirm_output, main

# ---------------------------------------------------------------------------
# _output_path helpers
# ---------------------------------------------------------------------------


class TestOutputPath:
    def test_title_and_author_organized(self, tmp_path: Path) -> None:
        meta = {"title": "Dune", "author": "Frank Herbert", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert p == tmp_path / "Frank Herbert" / "Dune" / "Frank Herbert - Dune.m4b"

    def test_title_and_author_flat(self, tmp_path: Path) -> None:
        meta = {"title": "Dune", "author": "Frank Herbert", "narrator": ""}
        p = _output_path(tmp_path, meta, flat=True)
        assert p == tmp_path / "Frank Herbert - Dune.m4b"

    def test_title_only_organized(self, tmp_path: Path) -> None:
        meta = {"title": "Dune", "author": "", "narrator": ""}
        p = _output_path(tmp_path, meta)
        assert p == tmp_path / "Dune" / "Dune.m4b"

    def test_title_only_flat(self, tmp_path: Path) -> None:
        meta = {"title": "Dune", "author": "", "narrator": ""}
        p = _output_path(tmp_path, meta, flat=True)
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
        assert p.name == "A-B - Title.m4b"


class TestConfirmOutput:
    def test_non_interactive_returns_proposed(self, tmp_path: Path) -> None:
        proposed = tmp_path / "out.m4b"
        result = _confirm_output(proposed, interactive=False)
        assert result == proposed

    def test_enter_confirms_proposed(self, tmp_path: Path) -> None:
        proposed = tmp_path / "out.m4b"
        with patch("builtins.input", return_value=""):
            result = _confirm_output(proposed, interactive=True)
        assert result == proposed

    def test_custom_path_accepted(self, tmp_path: Path) -> None:
        proposed = tmp_path / "out.m4b"
        custom = tmp_path / "custom.m4b"
        with patch("builtins.input", return_value=str(custom)):
            result = _confirm_output(proposed, interactive=True)
        assert result == custom.resolve()


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


def _make_popen_mock() -> MagicMock:
    """Return a mock subprocess.Popen process that succeeds immediately."""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = iter([])
    proc.stderr = iter([])
    proc.wait.return_value = 0
    return proc


def _fake_preflight_run(cmd: list[str], **kwargs: object) -> MagicMock:
    """Simulated ffprobe response for preflight analysis."""
    r = MagicMock()
    r.returncode = 0
    r.stdout = '{"streams": [{"sample_rate": "44100", "channels": 1}]}'
    return r


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
      - Patch ``m4bmaker.encoder.subprocess.Popen`` for the ffmpeg encode call.
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

    def _fake_ffmpeg_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        ffmpeg_cmds.append(cmd)
        return _make_popen_mock()

    with (
        patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("m4bmaker.chapters.get_duration", return_value=duration),
        patch("m4bmaker.pipeline.get_duration", return_value=duration),
        patch("m4bmaker.encoder.subprocess.Popen", side_effect=_fake_ffmpeg_popen),
        patch("m4bmaker.preflight.subprocess.run", side_effect=_fake_preflight_run),
        patch("m4bmaker.repair.needs_repair", return_value=False),
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

    def test_progress_flag_in_ffmpeg_command(self, tmp_path: Path) -> None:
        cmd, _ = _run_pipeline(tmp_path)
        assert "-progress" in cmd
        idx = cmd.index("-progress")
        assert cmd[idx + 1] == "pipe:1"
        assert "-nostdin" in cmd

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
            patch("m4bmaker.pipeline.get_duration", return_value=5.0),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
            patch("m4bmaker.preflight.subprocess.run", side_effect=_fake_preflight_run),
            patch("m4bmaker.repair.needs_repair", return_value=False),
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
            patch("m4bmaker.pipeline.get_duration", return_value=5.0),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
            patch("m4bmaker.preflight.subprocess.run", side_effect=_fake_preflight_run),
            patch("m4bmaker.repair.needs_repair", return_value=False),
            patch("m4bmaker.__main__.parse_args", return_value=parsed),
            patch.object(Path, "write_text", _capture),
        ):
            main()

        assert written, "concat file was never written"
        for f in audio_files:
            assert f.resolve().as_posix() in written[0]

    def test_fallback_to_audiobook_m4b_when_no_title(self, tmp_path: Path) -> None:
        """When metadata has no title, _output_path falls back to audiobook.m4b."""
        meta = {"title": "", "author": "A", "narrator": "N"}
        p = _output_path(tmp_path, meta)
        assert p.name == "audiobook.m4b"

    def test_default_output_uses_author_title_subfolders(self, tmp_path: Path) -> None:
        """Default (no --flat) produces Author/Title/Author - Title.m4b."""
        cmd, _ = _run_pipeline(tmp_path, title="My Book", author="Jane Doe")
        output = cmd[-1]
        assert "Jane Doe" in output
        assert "My Book" in output
        # Should contain subdir separators, not just a flat filename
        rel = output[len(str(tmp_path)) :]
        assert rel.count(os.sep) >= 3  # /Jane Doe/My Book/filename

    def test_flat_flag_produces_flat_output(self, tmp_path: Path) -> None:
        """--flat writes directly into the source dir without subfolders."""
        cmd, _ = _run_pipeline(
            tmp_path, title="My Book", author="Jane Doe", extra_argv=["--flat"]
        )
        output = cmd[-1]
        assert output.startswith(str(tmp_path))
        rel = output[len(str(tmp_path)) :]
        # Only one separator: /filename.m4b (or \filename.m4b on Windows)
        assert rel.count(os.sep) == 1
        assert rel.endswith(".m4b")

    def test_output_dir_flag_sets_base_directory(self, tmp_path: Path) -> None:
        """--output-dir redirects the auto-generated path to a different base."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        src = tmp_path / "src"
        src.mkdir()
        cmd, _ = _run_pipeline(
            src,
            title="Book",
            author="Author",
            extra_argv=["--output-dir", str(out_dir)],
        )
        output = cmd[-1]
        assert output.startswith(str(out_dir))

    def test_explicit_output_flag_bypasses_auto_path(self, tmp_path: Path) -> None:
        """--output overrides all auto-path logic."""
        explicit = tmp_path / "explicit.m4b"
        cmd, _ = _run_pipeline(tmp_path, extra_argv=["--output", str(explicit)])
        assert cmd[-1] == str(explicit)


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
            cover, user_specified = _resolve_cover(
                "https://example.com/c.jpg", tmp_path, tmp_path, False
            )
        assert cover == expected
        assert user_specified is True

    def test_local_path_arg_calls_find_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("m4bmaker.__main__.find_cover", return_value=img) as mock_fc:
            cover, user_specified = _resolve_cover(str(img), tmp_path, tmp_path, False)
        mock_fc.assert_called_once()
        assert cover == img
        assert user_specified is True

    def test_auto_detects_when_no_arg(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("m4bmaker.__main__.find_cover", return_value=img):
            cover, user_specified = _resolve_cover(None, tmp_path, tmp_path, False)
        assert cover == img
        assert user_specified is False

    def test_interactive_prompts_when_no_cover_found(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        expected = tmp_path / "prompted.jpg"
        with (
            patch("m4bmaker.__main__.find_cover", return_value=None),
            patch("m4bmaker.__main__._prompt_cover", return_value=expected) as mock_p,
        ):
            cover, user_specified = _resolve_cover(None, tmp_path, tmp_path, True)
        mock_p.assert_called_once_with(tmp_path)
        assert cover == expected
        assert user_specified is True

    def test_non_interactive_returns_none_when_no_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _resolve_cover

        with patch("m4bmaker.__main__.find_cover", return_value=None):
            cover, user_specified = _resolve_cover(None, tmp_path, tmp_path, False)
        assert cover is None
        assert user_specified is False


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

    def test_interactive_retries_bad_local_path_then_skips(
        self, tmp_path: Path
    ) -> None:
        """Entering a non-existent local path logs an error and re-prompts."""
        from m4bmaker.__main__ import _fetch_cover_url

        inputs = iter([str(tmp_path / "ghost.jpg"), ""])
        with (
            patch("m4bmaker.__main__.download_cover", side_effect=ValueError("bad")),
            patch("builtins.input", side_effect=inputs),
        ):
            result = _fetch_cover_url("https://fail.com/x.html", tmp_path, True)
        assert result is None


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
# _probe_progress
# ---------------------------------------------------------------------------


class TestProbeProgress:
    def test_non_tty_logs_file_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        from m4bmaker.__main__ import _probe_progress

        with patch("sys.stdout.isatty", return_value=False):
            _probe_progress(1, 3, "track01.mp3")
        captured = capsys.readouterr()
        assert "1/3" in captured.out or "track01" in captured.out

    def test_tty_renders_bar(self, capsys: pytest.CaptureFixture[str]) -> None:
        from m4bmaker.__main__ import _probe_progress

        with patch("sys.stdout.isatty", return_value=True):
            _probe_progress(1, 3, "track01.mp3")
        captured = capsys.readouterr()
        assert "Probing" in captured.out

    def test_tty_last_file_writes_newline(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from m4bmaker.__main__ import _probe_progress

        with patch("sys.stdout.isatty", return_value=True):
            _probe_progress(3, 3, "track03.mp3")
        captured = capsys.readouterr()
        assert "\n" in captured.out

    def test_tty_long_name_truncated(self, capsys: pytest.CaptureFixture[str]) -> None:
        from m4bmaker.__main__ import _probe_progress

        long_name = "a" * 40
        with patch("sys.stdout.isatty", return_value=True):
            _probe_progress(1, 3, long_name)
        captured = capsys.readouterr()
        # The ellipsis character indicates truncation
        assert "\u2026" in captured.out


# ---------------------------------------------------------------------------
# Full pipeline — cover image in directory
# ---------------------------------------------------------------------------


class TestPipelineWithCover:
    def test_cover_in_directory_is_embedded(self, tmp_path: Path) -> None:
        """Cover image auto-detected in directory appears in ffmpeg command."""
        (tmp_path / "cover.jpg").write_bytes(b"\x00")
        cmd, _ = _run_pipeline(tmp_path)
        assert str(tmp_path / "cover.jpg") in cmd


# ---------------------------------------------------------------------------
# _confirm_cover
# ---------------------------------------------------------------------------


class TestConfirmCover:
    def test_non_interactive_returns_cover_unchanged(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        result = _confirm_cover(img, tmp_path, interactive=False)
        assert result == img

    def test_non_interactive_returns_none_unchanged(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        result = _confirm_cover(None, tmp_path, interactive=False)
        assert result is None

    def test_enter_confirms_existing_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("builtins.input", return_value=""):
            result = _confirm_cover(img, tmp_path, interactive=True)
        assert result == img

    def test_enter_confirms_none(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        with patch("builtins.input", return_value=""):
            result = _confirm_cover(None, tmp_path, interactive=True)
        assert result is None

    def test_none_keyword_removes_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("builtins.input", return_value="none"):
            result = _confirm_cover(img, tmp_path, interactive=True)
        assert result is None

    def test_skip_keyword_removes_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")
        with patch("builtins.input", return_value="skip"):
            result = _confirm_cover(img, tmp_path, interactive=True)
        assert result is None

    def test_local_path_replaces_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        old = tmp_path / "old.jpg"
        old.write_bytes(b"\x00")
        new = tmp_path / "new.jpg"
        new.write_bytes(b"\x00")
        with patch("builtins.input", return_value=str(new)):
            result = _confirm_cover(old, tmp_path, interactive=True)
        assert result == new

    def test_url_input_downloads_cover(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        downloaded = tmp_path / "downloaded.jpg"
        with (
            patch("builtins.input", return_value="https://example.com/c.jpg"),
            patch("m4bmaker.__main__.download_cover", return_value=downloaded),
        ):
            result = _confirm_cover(None, tmp_path, interactive=True)
        assert result == downloaded

    def test_nonexistent_path_reprompts(self, tmp_path: Path) -> None:
        from m4bmaker.__main__ import _confirm_cover

        new = tmp_path / "real.jpg"
        new.write_bytes(b"\x00")
        inputs = iter([str(tmp_path / "ghost.jpg"), str(new)])
        with patch("builtins.input", side_effect=inputs):
            result = _confirm_cover(None, tmp_path, interactive=True)
        assert result == new

    def test_download_exception_reprompts(self, tmp_path: Path) -> None:
        """Exception from download_cover is caught and user is re-prompted."""
        from m4bmaker.__main__ import _confirm_cover

        real = tmp_path / "real.jpg"
        real.write_bytes(b"\x00")
        inputs = iter(["https://bad.com/fail.jpg", str(real)])
        with (
            patch("builtins.input", side_effect=inputs),
            patch(
                "m4bmaker.__main__.download_cover", side_effect=ValueError("no image")
            ),
        ):
            result = _confirm_cover(None, tmp_path, interactive=True)
        assert result == real


# ---------------------------------------------------------------------------
# _edit_chapters_inline
# ---------------------------------------------------------------------------


class TestEditChaptersInline:
    def test_enter_keeps_existing_title(self) -> None:
        from m4bmaker.__main__ import _edit_chapters_inline
        from m4bmaker.models import Chapter

        chapters = [Chapter(index=1, start_time=0.0, title="Prologue")]
        with patch("builtins.input", return_value=""):
            result = _edit_chapters_inline(chapters)
        assert result[0].title == "Prologue"

    def test_typed_value_replaces_title(self) -> None:
        from m4bmaker.__main__ import _edit_chapters_inline
        from m4bmaker.models import Chapter

        chapters = [Chapter(index=1, start_time=0.0, title="Old Title")]
        with patch("builtins.input", return_value="New Title"):
            result = _edit_chapters_inline(chapters)
        assert result[0].title == "New Title"

    def test_timestamps_preserved_unchanged(self) -> None:
        from m4bmaker.__main__ import _edit_chapters_inline
        from m4bmaker.models import Chapter

        chapters = [Chapter(index=1, start_time=1.0, title="Ch")]
        with patch("builtins.input", return_value="Renamed"):
            result = _edit_chapters_inline(chapters)
        assert result[0].start_time == 1.0

    def test_mixed_keep_and_replace(self) -> None:
        from m4bmaker.__main__ import _edit_chapters_inline
        from m4bmaker.models import Chapter

        chapters = [
            Chapter(index=1, start_time=0.0, title="Intro"),
            Chapter(index=2, start_time=1.0, title="Part One"),
            Chapter(index=3, start_time=2.0, title="Outro"),
        ]
        inputs = iter(["", "The Middle", ""])
        with patch("builtins.input", side_effect=inputs):
            result = _edit_chapters_inline(chapters)
        assert result[0].title == "Intro"
        assert result[1].title == "The Middle"
        assert result[2].title == "Outro"

    def test_returns_same_count(self) -> None:
        from m4bmaker.__main__ import _edit_chapters_inline
        from m4bmaker.models import Chapter

        chapters = [
            Chapter(index=i + 1, start_time=float(i), title=f"Ch {i}") for i in range(4)
        ]
        with patch("builtins.input", return_value=""):
            result = _edit_chapters_inline(chapters)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Chapter table + edit in pipeline
# ---------------------------------------------------------------------------


class TestChapterTableInPipeline:
    def test_table_suppressed_with_no_prompt(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Chapter table must NOT be shown when --no-prompt is set."""
        _run_pipeline(tmp_path)  # _run_pipeline always uses --no-prompt
        captured = capsys.readouterr()
        assert "\u250c" not in captured.out  # no ┌ box drawing

    def test_table_shown_on_interactive_tty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Chapter table IS shown when interactive and stdout is a TTY."""
        from m4bmaker.__main__ import _print_chapter_table
        from m4bmaker.models import Chapter

        chapters = [Chapter(index=1, start_time=0.0, title="Intro")]
        _print_chapter_table(chapters)
        captured = capsys.readouterr()
        assert "Intro" in captured.out
        assert "0:00:00" in captured.out
        assert "Chapters (1)" in captured.out

    def test_edit_prompt_not_shown_with_no_prompt(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The 'Edit chapter titles?' prompt must not appear in --no-prompt mode."""
        _run_pipeline(tmp_path)
        captured = capsys.readouterr()
        assert "Edit chapter titles" not in captured.out


# ---------------------------------------------------------------------------
# Interactive main() — chapter table + inline edit (lines 288-291)
# ---------------------------------------------------------------------------


class TestInteractiveChapterEdit:
    def test_chapter_table_and_edit_shown_in_interactive_tty(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With interactive=True and isatty=True, chapter table is printed and
        the 'Edit chapter titles?' prompt is shown; answering 'y' triggers
        _edit_chapters_inline through main()."""
        import sys

        from m4bmaker.__main__ import main
        from m4bmaker.cli import parse_args as real_parse_args

        _make_stub_mp3(tmp_path / "01 - Prologue.mp3")

        # No --no-prompt → interactive=True
        argv = [str(tmp_path), "--title", "T", "--author", "A", "--narrator", "N"]
        parsed = real_parse_args(argv)

        # Patch isatty on the live sys.stdout (capsys device) so the block
        # `if interactive and sys.stdout.isatty()` evaluates to True.
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        # Input sequence when interactive=True, isatty=True, no cover in dir:
        #   1  _prompt_cover (no cover auto-detected) → "" skip
        #   2  prompt_missing title    → "" keep "T"
        #   3  prompt_missing author   → "" keep "A"
        #   4  prompt_missing narrator → "" keep "N"
        #   5  prompt_missing genre    → "" skip
        #   6  _confirm_output         → "" keep proposed
        #   7  "Edit chapter titles?"  → "y"
        #   8  chapter 1 title edit    → "" keep "Prologue"
        inputs = iter(["", "", "", "", "", "", "y", ""])

        with (
            patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("m4bmaker.chapters.get_duration", return_value=10.0),
            patch("m4bmaker.pipeline.get_duration", return_value=10.0),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
            patch("m4bmaker.preflight.subprocess.run", side_effect=_fake_preflight_run),
            patch("m4bmaker.repair.needs_repair", return_value=False),
            patch("m4bmaker.__main__.parse_args", return_value=parsed),
            patch("builtins.input", side_effect=inputs),
        ):
            main()

        captured = capsys.readouterr()
        # _print_chapter_table calls print() which capsys captures
        assert "Chapters (1)" in captured.out
        assert "Prologue" in captured.out


# ---------------------------------------------------------------------------
# --chapters-file integration
# ---------------------------------------------------------------------------


class TestChaptersFileIntegration:
    def test_chapters_file_overrides_auto_chapters(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--chapters-file replaces the auto-detected chapters in main()."""
        from m4bmaker.__main__ import main
        from m4bmaker.cli import parse_args as real_parse_args

        _make_stub_mp3(tmp_path / "01.mp3")
        chapters_file = tmp_path / "chapters.txt"
        chapters_file.write_text(
            "00:00 Custom Intro\n05:00 Custom Middle\n", encoding="utf-8"
        )

        argv = [
            str(tmp_path),
            "--title",
            "T",
            "--author",
            "A",
            "--narrator",
            "N",
            "--no-prompt",
            "--chapters-file",
            str(chapters_file),
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
            patch("m4bmaker.chapters.get_duration", return_value=10.0),
            patch("m4bmaker.pipeline.get_duration", return_value=10.0),
            patch("m4bmaker.encoder.subprocess.Popen", return_value=_make_popen_mock()),
            patch("m4bmaker.preflight.subprocess.run", side_effect=_fake_preflight_run),
            patch("m4bmaker.repair.needs_repair", return_value=False),
            patch("m4bmaker.__main__.parse_args", return_value=parsed),
            patch.object(Path, "write_text", _capture),
        ):
            main()

        assert written, "ffmetadata was never written"
        assert "Custom Intro" in written[0]
        assert "Custom Middle" in written[0]
        # Two chapters from file, not one from the single audio file
        assert written[0].count("[CHAPTER]") == 2

        out = capsys.readouterr().out
        assert "Loaded 2 chapter(s) from chapters.txt" in out
