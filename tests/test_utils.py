"""Tests for m4bmaker.utils — ffmpeg/ffprobe detection and logging."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from m4bmaker.utils import find_ffmpeg, find_ffprobe, log


class TestFindFfmpeg:
    def test_returns_path_when_found(self) -> None:
        with patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffmpeg"):
            result = find_ffmpeg()
        assert result == "/usr/bin/ffmpeg"

    def test_exits_when_not_found(self) -> None:
        with patch("m4bmaker.utils.shutil.which", return_value=None):
            with pytest.raises(SystemExit, match="ffmpeg not found"):
                find_ffmpeg()

    def test_exit_message_contains_install_hints(self) -> None:
        with patch("m4bmaker.utils.shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                find_ffmpeg()
        msg = str(exc_info.value)
        assert "brew install ffmpeg" in msg or "apt install ffmpeg" in msg


class TestFindFfprobe:
    def test_returns_path_when_found(self) -> None:
        with patch("m4bmaker.utils.shutil.which", return_value="/usr/bin/ffprobe"):
            result = find_ffprobe()
        assert result == "/usr/bin/ffprobe"

    def test_exits_when_not_found(self) -> None:
        with patch("m4bmaker.utils.shutil.which", return_value=None):
            with pytest.raises(SystemExit, match="ffprobe not found"):
                find_ffprobe()

    def test_exit_message_mentions_ffmpeg(self) -> None:
        with patch("m4bmaker.utils.shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                find_ffprobe()
        assert "ffmpeg" in str(exc_info.value)


class TestLog:
    def test_prints_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        log("hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.out
