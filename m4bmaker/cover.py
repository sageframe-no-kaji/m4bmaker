"""Cover image detection and selection."""

from __future__ import annotations

from pathlib import Path

IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})


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
