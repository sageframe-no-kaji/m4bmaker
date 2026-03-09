"""Background workers for folder loading and audiobook conversion.

Both workers are QThread subclasses that emit typed signals so the GUI
thread never blocks.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from m4bmaker.models import Book
from m4bmaker.pipeline import load_audiobook, run_pipeline


class LoadWorker(QThread):
    """Scan a folder and build a :class:`Book` (may be slow for many files)."""

    finished = Signal(object)  # Book
    error = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    def run(self) -> None:
        try:
            ffprobe = shutil.which("ffprobe") or "ffprobe"
            book = load_audiobook(self._folder, ffprobe)
            self.finished.emit(book)
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class ConvertWorker(QThread):
    """Run :func:`run_pipeline` off the UI thread."""

    progress = Signal(str, float)  # message, 0.0–1.0
    finished = Signal(object)  # PipelineResult
    error = Signal(str)

    def __init__(
        self,
        book: Book,
        output_path: Path,
        bitrate: str = "96k",
        stereo: bool = False,
        sample_rate: int | None = None,
    ) -> None:
        super().__init__()
        self._book = book
        self._output_path = output_path
        self._bitrate = bitrate
        self._stereo = stereo
        self._sample_rate = sample_rate

    def run(self) -> None:
        try:
            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            ffprobe = shutil.which("ffprobe") or "ffprobe"
            result = run_pipeline(
                book=self._book,
                output_path=self._output_path,
                bitrate=self._bitrate,
                stereo=self._stereo,
                sample_rate=self._sample_rate,
                cover=self._book.cover,
                progress_callback=self._on_progress,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
            self.finished.emit(result)
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    def _on_progress(self, message: str, fraction: float) -> None:
        self.progress.emit(message, fraction)


class PreflightWorker(QThread):
    """Run audio preflight analysis off the UI thread."""

    finished = Signal(object)  # AudioAnalysis
    error = Signal(str)

    def __init__(self, files: list) -> None:
        super().__init__()
        self._files = files

    def run(self) -> None:
        try:
            ffprobe = shutil.which("ffprobe") or "ffprobe"
            from m4bmaker.preflight import run_preflight

            analysis = run_preflight(self._files, ffprobe)
            self.finished.emit(analysis)
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class LoadM4bWorker(QThread):
    """Load chapters and metadata from an existing .m4b file."""

    finished = Signal(object)  # tuple (Book, float total_duration_s)
    error = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            ffprobe = shutil.which("ffprobe") or "ffprobe"
            from m4bmaker.m4b_editor import load_m4b_chapters
            from m4bmaker.metadata import extract_metadata
            from m4bmaker.models import BookMetadata

            chapters, total_duration = load_m4b_chapters(self._path, ffprobe)
            raw_meta = extract_metadata(self._path)
            metadata = BookMetadata(
                title=raw_meta.get("title", ""),
                author=raw_meta.get("author", ""),
                narrator=raw_meta.get("narrator", ""),
                genre=raw_meta.get("genre", ""),
            )
            from m4bmaker.cover import extract_cover_from_audio

            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            cover_path = extract_cover_from_audio(self._path, ffmpeg)
            book = Book(files=[self._path], chapters=chapters, metadata=metadata, cover=cover_path)
            self.finished.emit((book, total_duration))
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class SaveChaptersWorker(QThread):
    """Rewrite chapter metadata in an .m4b file without re-encoding."""

    finished = Signal(object)  # Path (dest)
    error = Signal(str)

    def __init__(
        self,
        source: Path,
        chapters: list,
        total_duration: float,
        dest: Path,
    ) -> None:
        super().__init__()
        self._source = source
        self._chapters = chapters
        self._total_duration = total_duration
        self._dest = dest

    def run(self) -> None:
        try:
            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            from m4bmaker.m4b_editor import save_m4b_chapters

            save_m4b_chapters(
                self._source,
                self._chapters,
                self._total_duration,
                self._dest,
                ffmpeg,
            )
            self.finished.emit(self._dest)
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class SplitWorker(QThread):
    """Export each chapter of an .m4b file as a separate audio file (stream-copy)."""

    progress = Signal(str, float)  # message, 0.0–1.0
    finished = Signal(object)      # output_dir: Path
    error = Signal(str)

    def __init__(self, source: Path, chapters: list, total_duration: float, output_dir: Path) -> None:
        super().__init__()
        self._source = source
        self._chapters = chapters
        self._total_duration = total_duration
        self._output_dir = output_dir

    def run(self) -> None:
        try:
            import subprocess as _sp

            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            self._output_dir.mkdir(parents=True, exist_ok=True)
            total = len(self._chapters)
            ext = self._source.suffix or ".m4a"

            for i, ch in enumerate(self._chapters):
                start = ch.start_time
                end = self._chapters[i + 1].start_time if i + 1 < total else self._total_duration

                safe_title = "".join(
                    c if c.isalnum() or c in " ._-" else "_" for c in ch.title
                ).strip() or f"chapter_{i + 1:02d}"
                out_file = self._output_dir / f"{i + 1:02d} - {safe_title}{ext}"

                self.progress.emit(f"Splitting {i + 1}/{total}: {ch.title}", i / total)

                cmd = [
                    ffmpeg, "-y",
                    "-ss", str(start),
                    "-to", str(end),
                    "-i", str(self._source),
                    "-c", "copy",
                    str(out_file),
                ]
                result = _sp.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg failed on chapter {i + 1}: {result.stderr.strip()}"
                    )

            self.progress.emit("Split complete.", 1.0)
            self.finished.emit(self._output_dir)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
