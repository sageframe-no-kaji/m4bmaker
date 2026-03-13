"""Input repair / normalization — detect and clean damaged MP3 files.

This module provides a lightweight repair step that runs *before* encoding.
Only files that actually need repair are touched; all others pass through
unchanged.  Audio is never re-encoded; the repair step uses stream-copy.

Detection heuristics (via ``ffprobe``)
--------------------------------------
1. **Embedded cover / non-audio streams** — video stream present → embedded
   artwork needs stripping so the concat demuxer does not choke.
2. **Corruption markers** — ffprobe stderr contains known error strings
   (``Header missing``, ``Invalid data``, ``corrupt``, ``moov atom``) that
   indicate frame-level damage.

Repair strategy
---------------
- Use ``ffmpeg -fflags +discardcorrupt -err_detect ignore_err -map 0:a
  -c:a copy`` to remux audio-only, skipping corrupt frames.
- Store cleaned copies in a caller-supplied temporary directory; the
  originals are never modified.
- Return a :class:`RepairResult` describing how many files were repaired.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from m4bmaker.utils import subprocess_flags

# ffprobe stderr strings that indicate corruption / structural damage
_CORRUPTION_MARKERS = (
    "header missing",
    "invalid data",
    "corrupt",
    "moov atom",
    "error",
    "could not find codec",
)


# ── data models ───────────────────────────────────────────────────────────────


@dataclass
class RepairResult:
    """Summary of the repair pass."""

    total: int  # number of input files checked
    repaired: int = 0  # number of files that needed repair
    repaired_paths: list[tuple[Path, Path]] = field(
        default_factory=list
    )  # [(original, cleaned), …]
    error_paths: list[tuple[Path, str]] = field(
        default_factory=list
    )  # [(path, error_msg), …]

    @property
    def needed_repair(self) -> bool:
        """True if at least one file was repaired."""
        return self.repaired > 0


# ── detection ─────────────────────────────────────────────────────────────────


def needs_repair(path: Path, ffprobe: str) -> bool:
    """Return True if *path* has embedded non-audio streams or corruption.

    Uses two checks:
    1. ``ffprobe -show_streams`` — detect video / image streams (embedded art).
    2. ``ffprobe`` stderr output — detect ffprobe error/warning messages that
       indicate structural damage.
    """
    cmd = [
        ffprobe,
        "-v",
        "error",  # only emit errors, not info
        "-print_format",
        "json",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", **subprocess_flags())
    except OSError:
        # ffprobe not found or not executable — assume no repair needed
        return False

    # 1. Check for non-audio streams (embedded cover art is codec_type=video)
    try:
        import json

        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") not in ("audio", "data", "subtitle"):
                return True
    except Exception:  # noqa: BLE001
        pass

    # 2. Check stderr for corruption markers
    stderr_lower = result.stderr.lower()
    return any(marker in stderr_lower for marker in _CORRUPTION_MARKERS)


# ── repair ────────────────────────────────────────────────────────────────────


def repair_file(source: Path, dest_dir: Path, ffmpeg: str) -> Path:
    """Remux *source* to a cleaned copy in *dest_dir*, audio-only, stream-copy.

    Returns the path to the cleaned file.  Raises :exc:`subprocess.CalledProcessError`
    on ffmpeg failure (caller decides whether to abort or warn).
    """
    cleaned = dest_dir / source.name
    # Ensure unique name if two source files share the same base name
    if cleaned.exists():
        cleaned = dest_dir / f"{source.stem}_repaired{source.suffix}"

    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-fflags",
        "+discardcorrupt",
        "-err_detect",
        "ignore_err",
        "-i",
        str(source),
        "-map",
        "0:a",  # audio track only — drops embedded cover art
        "-c:a",
        "copy",  # stream copy; no re-encoding
        str(cleaned),
    ]
    subprocess.run(cmd, capture_output=True, encoding="utf-8", check=True, **subprocess_flags())
    return cleaned


# ── pass orchestration ────────────────────────────────────────────────────────


def run_repair(
    files: list[Path],
    tmp_dir: Path,
    ffmpeg: str,
    ffprobe: str,
    progress_callback: object = None,  # Callable[[str], None] | None
) -> RepairResult:
    """Detect and repair files that need cleaning.

    *progress_callback*, if provided, is called with a human-readable string
    at each significant step (intended for both CLI and GUI status updates).

    Returns a :class:`RepairResult`.  The caller should replace any repaired
    entries in ``book.files`` with the cleaned copies from
    ``result.repaired_paths``.
    """
    repair_dir = tmp_dir / "repaired"
    repair_dir.mkdir(parents=True, exist_ok=True)

    result = RepairResult(total=len(files))

    def _cb(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)  # type: ignore[operator]

    needs: list[Path] = []
    for path in files:
        if needs_repair(path, ffprobe):
            needs.append(path)

    if not needs:
        return result

    result.repaired = len(needs)
    _cb(f"Repairing {len(needs)} damaged audio file(s)…")

    for path in needs:
        try:
            cleaned = repair_file(path, repair_dir, ffmpeg)
            result.repaired_paths.append((path, cleaned))
        except (subprocess.CalledProcessError, OSError) as exc:
            stderr = getattr(exc, "stderr", None) or str(exc)
            result.error_paths.append((path, stderr.strip()))
            _cb(f"  Warning: could not repair {path.name} — {stderr[:80].strip()}")

    return result


def apply_repair(files: list[Path], result: RepairResult) -> list[Path]:
    """Return a new file list with repaired copies substituted in.

    Preserves the original order.  Files that were not repaired are
    returned as-is; repaired files are replaced with the cleaned copy.
    """
    mapping: dict[Path, Path] = {
        orig: cleaned for orig, cleaned in result.repaired_paths
    }
    return [mapping.get(p, p) for p in files]


def format_repair_report(result: RepairResult) -> str:
    """Return a multi-line CLI summary of the repair pass."""
    if not result.needed_repair:
        return ""
    lines = [
        "Repairing input audio files…",
        f"{result.repaired} file(s) contained corrupted frames or embedded artwork.",
        "Cleaned copies created before encoding.",
    ]
    if result.error_paths:
        lines.append(
            f"  ({len(result.error_paths)} file(s) could not be repaired and will be used as-is)"
        )
    return "\n".join(lines)
