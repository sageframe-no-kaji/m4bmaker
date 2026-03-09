"""Tests for m4bmaker.scanner — directory scan and natural sort."""

from __future__ import annotations

from pathlib import Path

import pytest

from m4bmaker.scanner import AUDIO_EXTENSIONS, scan_audio_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def touch(directory: Path, name: str) -> Path:
    p = directory / name
    p.write_bytes(b"\x00")
    return p


# ---------------------------------------------------------------------------
# Extension filtering
# ---------------------------------------------------------------------------


class TestExtensionFiltering:
    def test_finds_mp3(self, tmp_path: Path) -> None:
        touch(tmp_path, "track.mp3")
        result = scan_audio_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "track.mp3"

    def test_finds_all_supported_extensions(self, tmp_path: Path) -> None:
        names = ["a.mp3", "b.m4a", "c.aac", "d.flac", "e.wav", "f.ogg"]
        for n in names:
            touch(tmp_path, n)
        result = scan_audio_files(tmp_path)
        found_exts = {p.suffix.lower() for p in result}
        assert found_exts == AUDIO_EXTENSIONS

    def test_ignores_image_files(self, tmp_path: Path) -> None:
        touch(tmp_path, "01.mp3")
        touch(tmp_path, "cover.jpg")
        touch(tmp_path, "cover.png")
        result = scan_audio_files(tmp_path)
        assert all(p.suffix.lower() in AUDIO_EXTENSIONS for p in result)

    def test_ignores_text_and_other_files(self, tmp_path: Path) -> None:
        touch(tmp_path, "01.mp3")
        touch(tmp_path, "README.md")
        touch(tmp_path, "notes.txt")
        touch(tmp_path, "data.json")
        result = scan_audio_files(tmp_path)
        assert len(result) == 1

    def test_case_insensitive_extension_matching(self, tmp_path: Path) -> None:
        touch(tmp_path, "track.MP3")
        touch(tmp_path, "track2.FLAC")
        result = scan_audio_files(tmp_path)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Natural sort order
# ---------------------------------------------------------------------------


class TestNaturalSort:
    def test_natural_sort_not_lexicographic(self, tmp_path: Path) -> None:
        """01, 02, 10 — NOT 01, 10, 02 (lexicographic)."""
        for n in ("10 - Ten.mp3", "02 - Two.mp3", "01 - One.mp3"):
            touch(tmp_path, n)
        result = scan_audio_files(tmp_path)
        assert [p.name for p in result] == [
            "01 - One.mp3",
            "02 - Two.mp3",
            "10 - Ten.mp3",
        ]

    def test_natural_sort_with_varying_digit_widths(self, tmp_path: Path) -> None:
        for n in ("9.mp3", "100.mp3", "10.mp3", "1.mp3", "2.mp3"):
            touch(tmp_path, n)
        result = scan_audio_files(tmp_path)
        assert [p.name for p in result] == [
            "1.mp3",
            "2.mp3",
            "9.mp3",
            "10.mp3",
            "100.mp3",
        ]

    def test_single_file_returned_as_list(self, tmp_path: Path) -> None:
        touch(tmp_path, "only.mp3")
        result = scan_audio_files(tmp_path)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------


class TestErrorConditions:
    def test_empty_directory_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            scan_audio_files(tmp_path)
        assert "no supported audio files" in str(exc_info.value).lower()

    def test_directory_with_only_images_exits(self, tmp_path: Path) -> None:
        touch(tmp_path, "cover.jpg")
        with pytest.raises(SystemExit):
            scan_audio_files(tmp_path)

    def test_nonexistent_directory_exits(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit) as exc_info:
            scan_audio_files(missing)
        assert "not found" in str(exc_info.value).lower()

    def test_exit_message_lists_supported_formats(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            scan_audio_files(tmp_path)
        msg = str(exc_info.value).lower()
        assert ".mp3" in msg or "supported" in msg
