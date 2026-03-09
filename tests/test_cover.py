"""Tests for m4bmaker.cover — cover image detection and selection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from m4bmaker.cover import _image_area, find_cover

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_image(path: Path) -> Path:
    """Write a minimal PNG-like stub (real Pillow won't open it, but path exists)."""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return path


# ---------------------------------------------------------------------------
# _image_area
# ---------------------------------------------------------------------------


class TestImageArea:
    def test_returns_pixel_area_via_pillow(self, tmp_path: Path) -> None:
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")

        mock_img = MagicMock()
        mock_img.__enter__ = lambda s: s
        mock_img.__exit__ = MagicMock(return_value=False)
        mock_img.size = (800, 600)

        with patch("PIL.Image.open", return_value=mock_img):
            area = _image_area(img)

        assert area == 800 * 600

    def test_returns_zero_on_ioerror(self, tmp_path: Path) -> None:
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")

        with patch("PIL.Image.open", side_effect=OSError("bad file")):
            area = _image_area(img)

        assert area == 0

    def test_returns_zero_when_pillow_missing(self, tmp_path: Path) -> None:
        import sys

        img = tmp_path / "cover.jpg"
        img.write_bytes(b"\x00")

        # Temporarily hide PIL so the lazy import raises ImportError.
        with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
            area = _image_area(img)

        assert area == 0


# ---------------------------------------------------------------------------
# CLI override
# ---------------------------------------------------------------------------


class TestCliOverride:
    def test_override_path_returned_directly(self, tmp_path: Path) -> None:
        img = write_image(tmp_path / "custom.jpg")
        result = find_cover(tmp_path, cli_override=img)
        assert result == img

    def test_override_bypasses_directory_scan(self, tmp_path: Path) -> None:
        write_image(tmp_path / "big.jpg")
        override = write_image(tmp_path / "custom_cover.png")
        result = find_cover(tmp_path, cli_override=override)
        assert result == override

    def test_missing_override_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.jpg"
        with pytest.raises(FileNotFoundError, match="nope.jpg"):
            find_cover(tmp_path, cli_override=missing)


# ---------------------------------------------------------------------------
# No images
# ---------------------------------------------------------------------------


class TestNoImages:
    def test_returns_none_when_no_images(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"\x00")
        result = find_cover(tmp_path)
        assert result is None

    def test_returns_none_for_empty_directory(self, tmp_path: Path) -> None:
        result = find_cover(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# Single image
# ---------------------------------------------------------------------------


class TestSingleImage:
    def test_single_jpg_returned(self, tmp_path: Path) -> None:
        img = write_image(tmp_path / "cover.jpg")
        result = find_cover(tmp_path)
        assert result == img

    def test_single_png_returned(self, tmp_path: Path) -> None:
        img = write_image(tmp_path / "cover.png")
        result = find_cover(tmp_path)
        assert result == img

    def test_single_jpeg_returned(self, tmp_path: Path) -> None:
        img = write_image(tmp_path / "cover.jpeg")
        result = find_cover(tmp_path)
        assert result == img

    def test_ignores_non_image_files(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"\x00")
        img = write_image(tmp_path / "cover.jpg")
        result = find_cover(tmp_path)
        assert result == img


# ---------------------------------------------------------------------------
# Multiple images — largest resolution auto-picked
# ---------------------------------------------------------------------------


class TestMultipleImages:
    def test_largest_by_pillow_area_is_chosen(self, tmp_path: Path) -> None:
        small = write_image(tmp_path / "small.jpg")
        large = write_image(tmp_path / "large.jpg")

        # Patch _image_area so we control the sizes without needing real images.
        areas = {small: 100 * 100, large: 1000 * 1000}

        with patch("m4bmaker.cover._image_area", side_effect=lambda p: areas[p]):
            result = find_cover(tmp_path)

        assert result == large

    def test_tie_broken_by_filename(self, tmp_path: Path) -> None:
        """Equal areas: the lexicographically larger filename wins."""
        write_image(tmp_path / "a_cover.jpg")
        b = write_image(tmp_path / "b_cover.jpg")

        with patch("m4bmaker.cover._image_area", return_value=500):
            result = find_cover(tmp_path)

        # max() on equal area uses the second key: filename (str comparison)
        assert result == b

    def test_pillow_unavailable_falls_back_gracefully(self, tmp_path: Path) -> None:
        """If Pillow raises, _image_area returns 0; largest-name wins."""
        write_image(tmp_path / "a.jpg")
        b = write_image(tmp_path / "b.jpg")

        # _image_area returns 0 for all → tie broken by name → "b.jpg" wins
        with patch("m4bmaker.cover._image_area", return_value=0):
            result = find_cover(tmp_path)

        assert result == b

    def test_three_images_largest_chosen(self, tmp_path: Path) -> None:
        imgs = {
            write_image(tmp_path / "s.jpg"): 50 * 50,
            write_image(tmp_path / "m.jpg"): 500 * 500,
            write_image(tmp_path / "l.jpg"): 2000 * 2000,
        }
        large = tmp_path / "l.jpg"
        with patch("m4bmaker.cover._image_area", side_effect=lambda p: imgs[p]):
            result = find_cover(tmp_path)
        assert result == large
