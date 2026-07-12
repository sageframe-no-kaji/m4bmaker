"""Tests for m4bmaker.utils — ffmpeg/ffprobe detection and logging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from m4bmaker.errors import M4BError
from m4bmaker.utils import (
    find_ffmpeg,
    find_ffprobe,
    get_temp_root,
    log,
    safe_input,
    sanitize_filename_component,
)


class TestFindFfmpeg:
    def test_returns_path_when_found(self) -> None:
        with patch("m4bmaker.utils._which", return_value="/usr/bin/ffmpeg"):
            result = find_ffmpeg()
        assert result == "/usr/bin/ffmpeg"

    def test_exits_when_not_found(self) -> None:
        with patch("m4bmaker.utils._which", return_value=None):
            with pytest.raises(SystemExit, match="ffmpeg not found"):
                find_ffmpeg()

    def test_exit_message_contains_install_hints(self) -> None:
        with patch("m4bmaker.utils._which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                find_ffmpeg()
        msg = str(exc_info.value)
        assert "brew install ffmpeg" in msg or "apt install ffmpeg" in msg


class TestFindFfprobe:
    def test_returns_path_when_found(self) -> None:
        with patch("m4bmaker.utils._which", return_value="/usr/bin/ffprobe"):
            result = find_ffprobe()
        assert result == "/usr/bin/ffprobe"

    def test_exits_when_not_found(self) -> None:
        with patch("m4bmaker.utils._which", return_value=None):
            with pytest.raises(SystemExit, match="ffprobe not found"):
                find_ffprobe()

    def test_exit_message_mentions_ffmpeg(self) -> None:
        with patch("m4bmaker.utils._which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                find_ffprobe()
        assert "ffmpeg" in str(exc_info.value)


class TestLog:
    def test_prints_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        log("hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.out


# ---------------------------------------------------------------------------
# sanitize_filename_component
# ---------------------------------------------------------------------------


class TestSanitizeFilenameComponent:
    def test_plain_string_unchanged(self) -> None:
        assert sanitize_filename_component("My Book Title") == "My Book Title"

    def test_strips_nul_byte(self) -> None:
        assert sanitize_filename_component("A\x00B") == "AB"

    def test_strips_control_characters(self) -> None:
        assert sanitize_filename_component("A\x01\x02B") == "AB"

    def test_strips_del_character(self) -> None:
        assert sanitize_filename_component("A\x7fB") == "AB"

    @pytest.mark.parametrize("char", ["/", "\\", ":", "*", "?", '"', "<", ">", "|"])
    def test_reserved_chars_replaced_with_dash(self, char: str) -> None:
        result = sanitize_filename_component(f"A{char}B")
        assert result == "A-B"
        assert char not in result

    def test_multiple_reserved_chars(self) -> None:
        assert sanitize_filename_component("A/B:C*D") == "A-B-C-D"

    def test_collapses_whitespace_runs(self) -> None:
        assert sanitize_filename_component("A    B") == "A B"

    def test_tabs_and_newlines_stripped_as_control_chars(self) -> None:
        # Tab/newline are control characters (\\x00-\\x1f) and are stripped
        # entirely, same as other control chars — not collapsed to a space.
        assert sanitize_filename_component("A\t\nB") == "AB"

    def test_strips_leading_trailing_dots(self) -> None:
        assert sanitize_filename_component("...Title...") == "Title"

    def test_strips_leading_trailing_spaces(self) -> None:
        assert sanitize_filename_component("  Title  ") == "Title"

    def test_strips_leading_trailing_dots_and_spaces_combined(self) -> None:
        assert sanitize_filename_component(" . Title . ") == "Title"

    def test_empty_string_becomes_untitled(self) -> None:
        assert sanitize_filename_component("") == "Untitled"

    def test_single_dot_becomes_untitled(self) -> None:
        assert sanitize_filename_component(".") == "Untitled"

    def test_double_dot_becomes_untitled(self) -> None:
        assert sanitize_filename_component("..") == "Untitled"

    def test_only_dots_and_spaces_becomes_untitled(self) -> None:
        assert sanitize_filename_component(" ... ") == "Untitled"

    def test_only_reserved_chars_does_not_crash(self) -> None:
        # "////" -> "----" after replacement, which is a valid (if odd)
        # filename component — no crash, no exception.
        result = sanitize_filename_component("////")
        assert result == "----"

    def test_truncates_to_120_chars(self) -> None:
        long_name = "A" * 200
        result = sanitize_filename_component(long_name)
        assert len(result) == 120

    def test_truncation_happens_after_cleanup(self) -> None:
        # 130 reserved chars -> 130 dashes -> truncated to 120.
        long_name = "/" * 130
        result = sanitize_filename_component(long_name)
        assert len(result) == 120
        assert result == "-" * 120

    def test_unicode_preserved(self) -> None:
        assert sanitize_filename_component("Café — Ëxämple") == "Café — Ëxämple"

    def test_windows_reserved_path_chars_all_covered(self) -> None:
        raw = 'a/b\\c:d*e?f"g<h>i|j'
        result = sanitize_filename_component(raw)
        for char in '/\\:*?"<>|':
            assert char not in result


# ---------------------------------------------------------------------------
# get_temp_root
# ---------------------------------------------------------------------------


class TestGetTempRoot:
    def test_returns_a_path(self) -> None:
        root = get_temp_root()
        assert isinstance(root, Path)

    def test_directory_exists(self) -> None:
        root = get_temp_root()
        assert root.is_dir()

    def test_same_root_returned_on_repeated_calls(self) -> None:
        first = get_temp_root()
        second = get_temp_root()
        assert first == second

    def test_root_created_lazily_via_mkdtemp(self) -> None:
        """Reset the module-level cache and verify mkdtemp is invoked once."""
        import m4bmaker.utils as utils_module

        original = utils_module._temp_root
        utils_module._temp_root = None
        try:
            with (
                patch(
                    "m4bmaker.utils.tempfile.mkdtemp",
                    return_value="/tmp/fake_m4bmaker_root",
                ) as mock_mkdtemp,
                patch("m4bmaker.utils.atexit.register") as mock_register,
            ):
                root1 = get_temp_root()
                root2 = get_temp_root()
            mock_mkdtemp.assert_called_once()
            mock_register.assert_called_once()
            assert root1 == root2 == Path("/tmp/fake_m4bmaker_root")
        finally:
            utils_module._temp_root = original


# ---------------------------------------------------------------------------
# safe_input
# ---------------------------------------------------------------------------


class TestSafeInput:
    def test_returns_input_value(self) -> None:
        with patch("builtins.input", return_value="hello"):
            assert safe_input("prompt: ") == "hello"

    def test_eof_error_raises_m4berror_with_hint(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(M4BError, match="--no-prompt"):
                safe_input("prompt: ")

    def test_eof_error_uses_custom_hint(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(M4BError, match="--custom-flag"):
                safe_input("prompt: ", no_prompt_hint="--custom-flag")

    def test_keyboard_interrupt_raises_m4berror(self) -> None:
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with pytest.raises(M4BError, match="Cancelled"):
                safe_input("prompt: ")
