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


def extract_cover_from_audio(file: Path, ffmpeg: str = "ffmpeg") -> Path | None:
    """Extract embedded cover art from *file* to a temp directory.

    Returns the path to the extracted image, or ``None`` if the file has no
    embedded cover or the extraction fails.

    Tries ffmpeg first (works for files with a video/image stream), then falls
    back to mutagen for .m4b/.m4a files where the art is stored in the iTunes
    ``covr`` atom (which ffmpeg reports as a ``bin_data`` data stream).
    """
    import subprocess
    import tempfile as _tempfile

    # Attempt 1: ffmpeg video-stream extraction (works for most containers)
    try:
        tmp_dir = Path(_tempfile.mkdtemp(prefix="m4bmaker_cover_"))
        dest = tmp_dir / "cover.jpg"
        subprocess.run(  # noqa: S603
            [
                ffmpeg, "-y", "-i", str(file),
                "-an", "-vcodec", "copy",
                str(dest),
            ],
            capture_output=True,
            timeout=15,
        )
        if dest.exists() and dest.stat().st_size > 100:
            return dest
    except Exception:  # noqa: BLE001
        pass

    # Attempt 2: mutagen — handles .m4b/.m4a with iTunes-style covr atom
    try:
        from mutagen.mp4 import MP4
        audio = MP4(str(file))
        covr = audio.tags.get("covr") if audio.tags else None
        if covr:
            cover_data = bytes(covr[0])
            tmp_dir = Path(_tempfile.mkdtemp(prefix="m4bmaker_cover_"))
            dest = tmp_dir / "cover.jpg"
            dest.write_bytes(cover_data)
            if dest.stat().st_size > 100:
                return dest
    except Exception:  # noqa: BLE001
        pass

    return None


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
