"""Cover image detection and selection."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})

_MAX_DOWNLOAD_BYTES: int = 20 * 1024 * 1024  # 20 MB safety cap


def is_url(s: str) -> bool:
    """Return ``True`` if *s* looks like an http or https URL."""
    return s.startswith("http://") or s.startswith("https://")


def _ext_from_content_type(content_type: str) -> str:
    """Map a MIME type to a file extension (with leading dot).

    Returns an empty string for unrecognised types.
    """
    ct = content_type.split(";")[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(ct, "")


def download_cover(url: str, dest_dir: Path) -> Path:
    """Download the image at *url* to *dest_dir* and return the local path.

    Validates that the server reports an ``image/*`` Content-Type.

    Raises:
        ValueError: If the server returns a non-image Content-Type.
        urllib.error.URLError: On network or HTTP errors.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "m4bmaker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        content_type: str = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ValueError(
                f"URL did not return an image "
                f"(Content-Type: {content_type!r}): {url}"
            )
        ext = (
            _ext_from_content_type(content_type)
            or Path(urllib.parse.urlparse(url).path).suffix
            or ".jpg"
        )
        dest = dest_dir / f"downloaded_cover{ext}"
        dest.write_bytes(resp.read(_MAX_DOWNLOAD_BYTES))
    return dest


def _image_area(path: Path) -> int:
    """Return pixel area (width * height) for *path*, 0 on any error."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
            return w * h
    except Exception:
        return 0


def find_cover(directory: Path, cli_override: Path | None = None) -> Path | None:
    """Return the cover image to embed, or None if none is found.

    Resolution priority:
    1. *cli_override* — if provided, used directly (must exist).
    2. Single image in *directory* — returned as-is.
    3. Multiple images — the one with the largest pixel area is chosen
       automatically (uses Pillow; falls back to first file if Pillow
       is unavailable).
    """
    if cli_override is not None:
        if not cli_override.is_file():
            raise FileNotFoundError(f"Cover image not found: {cli_override}")
        return cli_override

    candidates: list[Path] = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Auto-pick the largest by pixel area; ties broken by name for determinism.
    return max(candidates, key=lambda p: (_image_area(p), p.name))
