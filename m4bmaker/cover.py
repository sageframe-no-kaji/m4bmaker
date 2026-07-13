"""Cover image detection and selection."""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from m4bmaker.errors import M4BError
from m4bmaker.utils import get_temp_root, subprocess_flags

IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})

_MAX_DOWNLOAD_BYTES: int = 20 * 1024 * 1024  # 20 MB safety cap


def _mkdtemp_under_root(prefix: str) -> Path:
    """Create a subdir under the per-process temp root and return its path."""
    import tempfile as _tempfile

    return Path(_tempfile.mkdtemp(prefix=prefix, dir=get_temp_root()))


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

    Validates that the server reports an ``image/*`` Content-Type. Only
    ``https://`` URLs are supported.

    Raises:
        M4BError: If *url* is not https, the server returns a non-image
            Content-Type, or the response exceeds the 20 MB safety cap.
        urllib.error.URLError: On network or HTTP errors.
    """
    if not url.startswith("https://"):
        raise M4BError(f"Cover URL must use https:// (http is not supported): {url}")

    req = urllib.request.Request(url, headers={"User-Agent": "m4bmaker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        content_type: str = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise M4BError(
                f"URL did not return an image "
                f"(Content-Type: {content_type!r}): {url}"
            )
        ext = (
            _ext_from_content_type(content_type)
            or Path(urllib.parse.urlparse(url).path).suffix
            or ".jpg"
        )
        # Read one byte past the cap so oversize responses are detected
        # instead of silently truncated.
        body = resp.read(_MAX_DOWNLOAD_BYTES + 1)
        if len(body) > _MAX_DOWNLOAD_BYTES:
            raise M4BError(f"Cover image exceeds the 20 MB size limit: {url}")
        dest = dest_dir / f"downloaded_cover{ext}"
        dest.write_bytes(body)
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
    # Attempt 1: ffmpeg video-stream extraction (works for most containers)
    try:
        tmp_dir = _mkdtemp_under_root("cover_")
        dest = tmp_dir / "cover.jpg"
        subprocess.run(  # noqa: S603
            [
                ffmpeg,
                "-y",
                "-i",
                str(file),
                "-an",
                "-vcodec",
                "copy",
                str(dest),
            ],
            capture_output=True,
            timeout=15,
            **subprocess_flags(),
        )
        if dest.exists() and dest.stat().st_size > 100:
            return dest
    except Exception:  # noqa: BLE001
        pass

    # Attempt 2: mutagen — handles .m4b/.m4a with iTunes-style covr atom
    try:
        from mutagen.mp4 import MP4

        # mutagen's py.typed marker exists but MP4.__init__ isn't fully
        # annotated, so mypy sees this constructor call as untyped.
        audio: Any = MP4(str(file))  # type: ignore[no-untyped-call]
        covr = audio.tags.get("covr") if audio.tags else None
        if covr:
            cover_data = bytes(covr[0])
            tmp_dir = _mkdtemp_under_root("cover_")
            dest = tmp_dir / "cover.jpg"
            dest.write_bytes(cover_data)
            if dest.stat().st_size > 100:
                return dest
    except Exception:  # noqa: BLE001
        pass

    # Attempt 3: mutagen — handles MP3 ID3 APIC (attached picture) frames
    try:
        from mutagen.id3 import ID3

        # mutagen's py.typed marker exists but ID3.__init__/getall aren't
        # fully annotated, so mypy sees these calls as untyped.
        tags: Any = ID3(str(file))  # type: ignore[no-untyped-call]
        apic_frames = tags.getall("APIC")
        if apic_frames:
            # Prefer front cover (picture type 3) if present, else take the first
            frame = next((f for f in apic_frames if f.type == 3), apic_frames[0])
            ext = ".jpg" if "jpeg" in frame.mime.lower() else ".png"
            tmp_dir = _mkdtemp_under_root("cover_")
            dest = tmp_dir / f"cover{ext}"
            dest.write_bytes(frame.data)
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

    if not directory.is_dir():
        return None

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
